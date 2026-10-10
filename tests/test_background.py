from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import pytest
from sqlalchemy import select
from test_api import setup
from backend.mail import deliver
from backend.models import Bug, Configuration, ModelState, Outbox, Resolution, now
from backend.routes import inspect_attachment
from backend.training import predict_assignment, train_assignment
from backend.worker import train_due
from backend.evaluate_duplicates import evaluate


def test_duplicate_evaluator_requires_actual_links():
    rows=[{'id':'1','created_at':1,'title':'checkout crash','description':''},
          {'id':'2','created_at':2,'title':'checkout crash again','duplicate_of':'1'}]
    metrics=evaluate(rows)
    assert metrics['recall']['1']==1 and metrics['mrr']==1
    with pytest.raises(ValueError):evaluate(rows[:1])


def test_smtp_uses_tls_and_keeps_preview_local(tmp_path, monkeypatch):
    from backend.mail import deliver
    item=Outbox(id=1,channel='email',recipient='test@example.com',subject='Test',body='Synthetic message')
    monkeypatch.setenv('MAIL_TRANSPORT','smtp')
    monkeypatch.setenv('SMTP_HOST','smtp.example.com')
    monkeypatch.setenv('SMTP_FROM','noreply@example.com')
    monkeypatch.setenv('SMTP_USER','test')
    monkeypatch.setenv('SMTP_PASSWORD','test-password')
    with patch('backend.mail.smtplib.SMTP') as smtp:
        deliver(item)
        server=smtp.return_value.__enter__.return_value
        server.starttls.assert_called_once()
        server.send_message.assert_called_once()
    monkeypatch.setenv('SMTP_SECURITY','ssl')
    with patch('backend.mail.smtplib.SMTP_SSL') as smtp:
        deliver(item)
        smtp.return_value.__enter__.return_value.send_message.assert_called_once()
    monkeypatch.setenv('SMTP_SECURITY','none')
    with pytest.raises(ValueError):deliver(item)
    monkeypatch.setenv('MAIL_TRANSPORT','preview')
    monkeypatch.setenv('MAIL_PREVIEW_DIR',str(tmp_path))
    deliver(item)
    assert 'Synthetic message' in (tmp_path/'00000001.eml').read_text()


def test_scanner_fail_closed(monkeypatch):
    monkeypatch.setenv('CLAMSCAN_PATH','test-scanner')
    monkeypatch.delenv('CLAMAV_HOST',raising=False)
    with patch('backend.routes.subprocess.run',return_value=SimpleNamespace(returncode=0)):
        assert inspect_attachment('safe.log',b'log')==('text/plain','clamav-clean')
    from fastapi import HTTPException
    with patch('backend.routes.subprocess.run',return_value=SimpleNamespace(returncode=1)):
        with pytest.raises(HTTPException) as error:inspect_attachment('bad.log',b'log')
        assert error.value.status_code==422
    with patch('backend.routes.subprocess.run',return_value=SimpleNamespace(returncode=2)):
        with pytest.raises(HTTPException) as error:inspect_attachment('error.log',b'log')
        assert error.value.status_code==503


def test_model_training_failure_is_visible_and_keeps_old_model(setup,monkeypatch,tmp_path):
    c,h,p,factory=setup
    monkeypatch.chdir(tmp_path)
    with factory() as db:
        db.add(Configuration(key='triage',value={'cold_start_count':10}))
        for i in range(20):
            bug=Bug(project_id=p,reporter_id=2,assignee_id=3,title=f'Unique test problem {i}',description='A synthetic training example',steps='Test',environment='Test',status='Verified',created_at=now()-timedelta(days=30-i))
            db.add(bug);db.flush()
            db.add(Resolution(project_id=p,user_id=3,bug_id=bug.id,component='general',severity='Medium',keywords=['test'],resolution_seconds=60))
        db.commit()
    with patch('backend.training.train_assignment',side_effect=ValueError('Need two assignees')):
        train_due(factory)
    with factory() as db:
        state=db.get(ModelState,p)
        assert state.status=='training_failed' and state.artifact is None
        assert state.error=='Need two assignees'


def test_cnn_lstm_artifact_and_inference(tmp_path):
    pytest.importorskip('torch')
    rows=[{'title':f'Synthetic checkout issue {i}','description':'Payment fails' if i%2 else 'Basket fails',
           'component':'checkout','assignee':1 if i%2 else 3,'created_at':i+1,'fixed':True,
           'predicted_severity':'Medium','known_duplicate':False} for i in range(40)]
    output=tmp_path/'model.pt'
    metrics=train_assignment(rows,output,epochs=1)
    assert metrics['test_count']==8 and metrics['developer_classes']==2
    bug=SimpleNamespace(title='Payment issue',description='Payment fails',component='checkout',severity='Medium',duplicate_of=None)
    predictions=predict_assignment(str(output),bug)
    assert set(predictions)=={1,3}
    assert abs(sum(predictions.values())-1)<1e-5
