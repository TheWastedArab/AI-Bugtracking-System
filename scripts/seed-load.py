"""Prepare the dedicated artifacts/qa.db for a 50,000-record local load test."""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from datetime import datetime, timezone
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from backend.models import Bug, Project, User

engine=create_engine('sqlite:///./artifacts/qa.db')
with Session(engine) as db:
    project=db.scalar(select(Project).where(Project.name=='Checkout Demo'))
    reporter=db.scalar(select(User).where(User.email=='reporter@example.com'))
    if not project or not reporter:
        raise SystemExit('Seed backend.demo in artifacts/qa.db first')
    count=db.scalar(select(func.count(Bug.id)).where(Bug.project_id==project.id))
    needed=max(0,50000-count)
    batch=[]
    with open('data/eclipse.jsonl',encoding='utf-8') as source:
        for i,line in enumerate(source):
            if i>=needed:break
            record=json.loads(line)
            batch.append({'project_id':project.id,'reporter_id':reporter.id,'title':record['title'][:200],
                          'description':'Isolated benchmark title fixture: '+record['title'],
                          'steps':'Synthetic load test','environment':'Synthetic load test','component':record.get('component','general')[:100],
                          'severity':record['severity'],'status':'Open',
                          'created_at':datetime.fromtimestamp(record['created_at'],timezone.utc).replace(tzinfo=None),
                          'triage':{'mode':'benchmark-fixture'}})
            if len(batch)==1000:
                db.bulk_insert_mappings(Bug,batch);batch=[]
    if batch:db.bulk_insert_mappings(Bug,batch)
    db.commit()
    print('QA project bug count:',db.scalar(select(func.count(Bug.id)).where(Bug.project_id==project.id)))
