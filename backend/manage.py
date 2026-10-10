"""Explicit local administration; never expose this as a public endpoint."""
import argparse
from sqlalchemy import select
from .db import SessionLocal
from .models import User


def main():
    parser = argparse.ArgumentParser(description='Activate a local test account and assign its global role')
    parser.add_argument('email')
    parser.add_argument('--role', choices=['reporter', 'manager', 'admin'], default='reporter')
    args = parser.parse_args()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == args.email.lower()))
        if user is None:
            parser.error('Register this account through the API first')
        user.active = True
        user.global_role = args.role
        db.commit()
    print('Local account activated. This does not verify email ownership.')


if __name__ == '__main__':
    main()
