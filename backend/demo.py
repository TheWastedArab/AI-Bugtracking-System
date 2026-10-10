"""Seed explicit synthetic accounts and a demo project. Never imports benchmark users."""
import argparse
import secrets
from sqlalchemy import select
from .db import SessionLocal
from .models import Bug, DeveloperProfile, Membership, Project, User
from .security import hash_password


def seed(password):
    with SessionLocal() as db:
        if db.scalar(select(User.id).where(User.email == 'admin@example.com')):
            raise ValueError('Demo already exists; existing accounts were left unchanged')
        users = []
        for name, role in [('admin','admin'),('manager','manager'),('developer','reporter'),('reporter','reporter')]:
            user = User(email=f'{name}@example.com', name=name.title(), password_hash=hash_password(password), active=True, global_role=role)
            db.add(user)
            users.append(user)
        db.flush()
        project = Project(name='Checkout Demo')
        db.add(project)
        db.flush()
        for user, role in zip(users, ['manager','manager','developer','reporter']):
            db.add(Membership(project_id=project.id,user_id=user.id,role=role))
            if role in ('developer','manager'):
                db.add(DeveloperProfile(project_id=project.id,user_id=user.id,skills=['python','checkout','payment'],components=['checkout','general']))
        db.add(Bug(project_id=project.id,reporter_id=users[3].id,title='Checkout crashes when basket is empty',
                   description='The checkout screen crashes when an empty basket is submitted.',steps='Empty the basket and press Checkout',
                   environment='Synthetic example · Windows',component='checkout',severity='High',triage={'mode':'synthetic-demo','message':'This is a synthetic demonstration record.'}))
        db.commit()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--password', help='Optional explicit demo password; otherwise generated')
    args = parser.parse_args()
    password = args.password or ('Demo!' + secrets.token_urlsafe(12) + '7A')
    seed(password)
    print('Demo accounts: admin@example.com, manager@example.com, developer@example.com, reporter@example.com')
    print('Temporary local demo password: ' + password)
