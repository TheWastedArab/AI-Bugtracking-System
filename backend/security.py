import os
import secrets
from datetime import timedelta
import bcrypt
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
from .db import get_db
from .models import LoginSession, User, now

bearer = HTTPBearer(auto_error=False)


def signing_key():
    key = os.environ.get('JWT_SECRET', '')
    if len(key) < 32:
        raise RuntimeError('Set JWT_SECRET to a random secret of at least 32 characters')
    return key


def hash_password(password):
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def check_password(password, hashed):
    return len(password.encode()) <= 72 and bcrypt.checkpw(password.encode(), hashed.encode())


def issue_token(db, user):
    session = LoginSession(id=secrets.token_hex(32), user_id=user.id)
    db.add(session)
    db.commit()
    # Server-side session enforces sliding idle expiry and immediate logout.
    return jwt.encode({'sub': str(user.id), 'sid': session.id, 'iat': now(), 'iss': 'capstone-triage'}, signing_key(), algorithm='HS256')


def current_session(credentials: HTTPAuthorizationCredentials = Depends(bearer), db: Session = Depends(get_db)):
    try:
        if credentials is None:
            raise ValueError()
        payload = jwt.decode(credentials.credentials, signing_key(), algorithms=['HS256'], issuer='capstone-triage', options={'require': ['sub', 'sid', 'iat', 'iss']})
        session = db.get(LoginSession, payload['sid'])
        if not session or str(session.user_id) != payload['sub'] or now() - session.last_seen >= timedelta(hours=8):
            raise ValueError()
        user = db.get(User, session.user_id)
        if not user or not user.active:
            raise ValueError()
    except (jwt.InvalidTokenError, ValueError, TypeError):
        raise HTTPException(401, 'Invalid or expired session')
    session.last_seen = now()
    db.commit()
    return session


def current_user(session=Depends(current_session), db: Session = Depends(get_db)):
    return db.get(User, session.user_id)
