import argparse
from datetime import timedelta
from pathlib import Path
import time
from sqlalchemy import delete, select
from .ai import model_status
from .db import SessionLocal
from .mail import drain
from .models import Bug, ModelState, Project, RateBucket, Resolution, now


def train_due(factory=SessionLocal):
    from .training import train_assignment
    with factory() as db:
        projects = db.scalars(select(Project).where(Project.archived.is_(False))).all()
        ids = [p.id for p in projects]
    for project_id in ids:
        with factory() as db:
            state = db.get(ModelState, project_id)
            status = model_status(db, project_id)
            if status['cold_start']:
                continue
            if state is None:
                state = ModelState(project_id=project_id)
                db.add(state)
            due = state.trained_at is None or now() - state.trained_at >= timedelta(days=30) or status['verified_assigned_count'] - state.trained_count >= 200
            if not due:
                continue
            rows = []
            for history, bug in db.execute(select(Resolution, Bug).join(Bug, Resolution.bug_id == Bug.id).where(Resolution.project_id == project_id)):
                rows.append({'title': bug.title, 'description': bug.description, 'component': history.component,
                             'assignee': history.user_id, 'predicted_severity': history.severity,
                             'known_duplicate': bool(bug.duplicate_of), 'created_at': bug.created_at.timestamp(), 'fixed': True})
            state.status = 'training'
            db.commit()
        try:
            artifact = Path('artifacts') / f'project-{project_id}-{int(time.time())}.pt'
            train_assignment(rows, artifact)
            with factory() as db:
                state = db.get(ModelState, project_id)
                state.artifact = str(artifact.resolve())
                state.trained_at, state.trained_count, state.status, state.error = now(), len(rows), 'ready', None
                db.commit()
        except Exception as exc:
            with factory() as db:
                state = db.get(ModelState, project_id)
                state.status, state.error = 'training_failed', str(exc)[:500]
                db.commit()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Run one worker per deployment; restart safely after failures')
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--train', action='store_true', help='Run model training instead of notification delivery')
    args = parser.parse_args()
    while True:
        with SessionLocal() as cleanup:
            cleanup.execute(delete(RateBucket).where(RateBucket.window < int(time.time() // 60) - 60))
            cleanup.commit()
        if args.train:
            train_due()
        else:
            print(f'Delivered {drain()} notifications', flush=True)
        if args.once:
            break
        time.sleep(30)
