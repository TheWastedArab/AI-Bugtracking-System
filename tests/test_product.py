import hashlib
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
import pytest
from sqlalchemy import select
from test_api import setup, create_bug
from backend import ai
from backend.mail import drain
from backend.models import Bug, DeveloperProfile, Outbox, Resolution, User, Verification, now


def make_admin(factory):
    with factory() as db:
        db.get(User, 1).global_role = 'admin'
        db.commit()


def latest_code(factory):
    with factory() as db:
        item = db.scalar(select(Outbox).where(Outbox.subject == 'Verify your Bug Triage email').order_by(Outbox.id.desc()))
        return item.body.split('\n\n')[1]


def test_email_verification_and_change(setup, tmp_path, monkeypatch):
    c, h, project, factory = setup
    payload = {'name': 'A New User', 'email': 'fresh@example.com', 'password': ' Spaces123! '}
    assert c.post('/auth/register', json=payload).status_code == 202
    code = latest_code(factory)
    assert c.post('/auth/verify', json={'token': 'x'*43}).status_code == 400
    assert c.post('/auth/resend', json={'email': payload['email']}).status_code == 202
    assert latest_code(factory) == code  # Two-minute resend cooldown.
    assert c.post('/auth/verify', json={'token': code}).status_code == 200
    assert c.post('/auth/verify', json={'token': code}).status_code == 400
    assert c.post('/auth/login', json={'email': payload['email'], 'password': 'Spaces123!'}).status_code == 401
    assert c.post('/auth/login', json={'email': payload['email'], 'password': payload['password']}).status_code == 200
    assert c.patch('/auth/me', headers=h['manager'], json={'email': 'changed@example.com'}).status_code == 401
    changed = c.patch('/auth/me', headers=h['manager'], json={'name': 'Updated Manager', 'email': 'changed@example.com', 'current_password': 'Testing123!', 'preferences': {'comment': False}})
    assert changed.json()['email_change_pending'] is True
    assert changed.json()['email'] == 'manager@example.com'
    code = latest_code(factory)
    monkeypatch.setenv('MAIL_PREVIEW_DIR', str(tmp_path))
    assert drain(factory) >= 2
    assert list(tmp_path.glob('*.eml'))
    assert c.post('/auth/verify', json={'token': code}).status_code == 200
    assert c.get('/auth/me', headers=h['manager']).status_code == 401
    assert c.post('/auth/login', json={'email': 'changed@example.com', 'password': 'Testing123!'}).status_code == 200


def test_expired_verification_and_resend(setup):
    c, h, project, factory = setup
    c.post('/auth/register', json={'name': 'Expired', 'email': 'expired@example.com', 'password': 'Testing123!'})
    code = latest_code(factory)
    with factory() as db:
        item = db.get(Verification, hashlib.sha256(code.encode()).hexdigest())
        item.expires_at = now() - timedelta(seconds=1)
        item.created_at = now() - timedelta(minutes=3)
        db.commit()
    assert c.post('/auth/verify', json={'token': code}).status_code == 400
    c.post('/auth/resend', json={'email': 'expired@example.com'})
    new_code = latest_code(factory)
    assert new_code != code
    assert c.post('/auth/verify', json={'token': new_code}).status_code == 200
    assert c.patch('/auth/me', headers=h['manager'], json={'name': None}).status_code == 422


def test_membership_lifecycle_and_project_history(setup):
    c, h, p, factory = setup
    bug = create_bug(c, h, p)
    path = f'/projects/{p}'
    assert c.patch(path, headers=h['reporter'], json={'name':'No'}).status_code == 403
    assert c.patch(path, headers=h['manager'], json={'name':'Renamed'}).json()['name'] == 'Renamed'
    assert c.delete(path+'/members/1', headers=h['manager']).status_code == 409
    assert c.put(path+'/members', headers=h['manager'], json={'user_id':1,'role':'reporter'}).status_code == 409
    assert c.patch(path+f'/bugs/{bug}', headers=h['manager'], json={'assignee_id':3}).status_code == 200
    assert c.delete(path+'/members/3', headers=h['manager']).status_code == 204
    assert c.get(path+f'/bugs/{bug}', headers=h['developer']).status_code == 403
    assert c.get(path+f'/bugs/{bug}', headers=h['manager']).json()['bug']['assignee_id'] is None
    with factory() as db:
        profile = db.scalar(select(DeveloperProfile).where(DeveloperProfile.user_id == 3))
        assert profile.active is False
    logs = c.get(path+'/audit', headers=h['manager']).json()
    assert any(row['action'] == 'membership_removed' for row in logs)
    assert any(row['details'].get('before') is None for row in logs if row['action']=='membership_changed')
    assert len(c.get(path+'/members', headers=h['manager']).json()) == 2


def test_profile_recommendation_enrichment_and_dashboard(setup):
    c,h,p,factory=setup
    make_admin(factory)
    profile={'skills':['checkout','Python'],'components':['general'],'capacity':1,'availability':'Available','active':True}
    assert c.put(f'/admin/projects/{p}/profiles/3',headers=h['reporter'],json=profile).status_code==403
    assert c.put(f'/admin/projects/{p}/profiles/3',headers=h['manager'],json=profile).status_code==200
    bug=create_bug(c,h,p)
    path=f'/projects/{p}/bugs/{bug}'
    detail=c.get(path,headers=h['manager']).json()
    assert detail['assignment']['mode']=='rule-based'
    assert detail['assignment']['recommendations'][0]['user_id']==3
    version=detail['bug']['version']
    assert c.patch(path,headers=h['manager'],json={'assignee_id':3,'version':version}).status_code==200
    assert c.patch(path,headers=h['manager'],json={'severity':'High','version':version}).status_code==409
    assert c.get(path,headers=h['manager']).json()['assignment']['recommendations']==[]
    for status in ['In Progress','Resolved','Verified']:
        assert c.patch(path,headers=h['developer'],json={'status':status}).status_code==200
    with factory() as db:
        history=db.scalar(select(Resolution).where(Resolution.bug_id==bug))
        assert history.user_id==3 and history.resolution_seconds>=0
    assert c.patch(path,headers=h['manager'],json={'status':'Verified'}).status_code==200
    assert c.patch(path,headers=h['manager'],json={'assignee_id':2}).status_code==409
    dashboard=c.get(f'/projects/{p}/dashboard',headers=h['reporter']).json()
    assert dashboard['counts']['Verified']==1
    assert dashboard['model']['remaining']==99
    assert len(dashboard['weeks'])==8
    profiles=c.get(f'/projects/{p}/profiles',headers=h['manager']).json()
    assert next(x for x in profiles if x['profile']['user_id']==3)['workload']==0
    assert c.get('/admin/models',headers=h['manager']).status_code==200


def test_duplicate_filters_notifications_and_admin(setup):
    c,h,p,factory=setup
    make_admin(factory)
    assert c.put('/admin/settings',headers=h['manager'],json={'rule_severity':True}).status_code==200
    assert c.get('/admin/settings',headers=h['manager']).json()['rule_severity'] is True
    payload={'title':'Storage outage','description':'Storage outage prevents every checkout operation','steps':'Checkout','environment':'Windows'}
    response=c.post(f'/projects/{p}/bugs',headers=h['reporter'],json=payload)
    assert response.json()['bug']['severity']=='Critical'
    bug=response.json()['bug']['id'];path=f'/projects/{p}/bugs/{bug}'
    result=c.post(f'/projects/{p}/duplicates',headers=h['reporter'],json=payload).json()
    assert result['candidates'][0]['id']==bug
    assert result['candidates'][0]['similarity_percent'] is None
    assert c.patch(path,headers=h['developer'],json={'duplicate_of':bug}).status_code==409
    assert c.patch(path,headers=h['developer'],json={'duplicate_of':999}).status_code==400
    assert c.get(f'/projects/{p}/bugs?created_from=2099-01-01T00:00:00Z',headers=h['reporter']).json()==[]
    assert c.get(f'/projects/{p}/bugs?created_from=2099-01-01&created_to=2000-01-01',headers=h['reporter']).status_code==422
    assert c.put(path+'/watch',headers=h['developer']).status_code==204
    c.post(path+'/comments',headers=h['developer'],json={'body':'Investigating'})
    inbox=c.get('/notifications',headers=h['reporter']).json()
    assert inbox['unread']>=2
    item=inbox['items'][0]['id']
    assert c.post(f'/notifications/{item}/read',headers=h['outsider']).status_code==403
    assert c.post(f'/notifications/{item}/read',headers=h['reporter']).status_code==204
    assert c.put(path+'/watch?enabled=false',headers=h['developer']).status_code==204
    assert c.get('/admin/users',headers=h['manager']).status_code==200
    assert c.patch('/admin/users/1',headers=h['manager'],json={'active':False,'global_role':'reporter'}).status_code==409
    assert c.patch('/admin/users/4',headers=h['manager'],json={'active':False,'global_role':'reporter'}).status_code==200
    assert c.get('/auth/me',headers=h['outsider']).status_code==401


def test_attachment_validation_and_access(setup,monkeypatch):
    c,h,p,factory=setup
    bug=create_bug(c,h,p);path=f'/projects/{p}/bugs/{bug}/attachments'
    assert c.post(path,headers=h['reporter'],files={'file':('safe.log',b'Error log')}).status_code==503
    monkeypatch.setenv('ALLOW_UNSCANNED_ATTACHMENTS','true')
    for name,data in [('../bad.txt',b'log'),('malware.exe',b'MZ'),('bad.log',b'\x00'),('fake.png',b'bad')]:
        assert c.post(path,headers=h['reporter'],files={'file':(name,data)}).status_code==422
    result=c.post(path,headers=h['reporter'],files={'file':('safe.log',b'Error log')})
    assert result.status_code==201
    item=result.json()['id']
    assert len(c.get(path,headers=h['reporter']).json())==1
    assert c.get(path+f'/{item}',headers=h['outsider']).status_code==403
    response=c.get(path+f'/{item}',headers=h['developer'])
    assert response.content==b'Error log'
    assert response.headers['x-content-type-options']=='nosniff'


def test_model_failure_and_mail_retry(setup,monkeypatch):
    c,h,p,factory=setup
    assert ai.severity('a crash',{'rule_severity':True})[0]=='High'
    assert ai.severity('a typo',{'rule_severity':True})[0]=='Low'
    assert ai.severity('something',{'rule_severity':True})[0]=='Medium'
    with factory() as db:
        db.add(Outbox(recipient='test@example.com',subject='Test',body='Hello'))
        db.commit()
    with patch('backend.mail.deliver',side_effect=RuntimeError('secret must not be stored')):
        assert drain(factory)==0
    with factory() as db:
        item=db.scalar(select(Outbox))
        assert item.attempts==1 and item.error=='RuntimeError'
