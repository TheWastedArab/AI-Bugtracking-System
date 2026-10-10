import hashlib
import secrets
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .db import get_db
from .models import LoginSession, Outbox, SystemAudit, User, Verification, now
from .schemas import AccountUpdate, ResendInput, VerifyInput
from .security import check_password, current_user
from .limits import auth_limit

router = APIRouter(tags=['Accounts'], dependencies=[Depends(auth_limit)])
GENERIC_MESSAGE = {'message': 'If the account is eligible, a verification email has been queued.'}


def queue_verification(db, user, email):
    db.execute(delete(Verification).where(Verification.user_id == user.id))
    token = secrets.token_urlsafe(32)
    db.add(Verification(id=hashlib.sha256(token.encode()).hexdigest(), user_id=user.id,
                        email=email, expires_at=now() + timedelta(hours=1)))
    db.add(Outbox(recipient=email, subject='Verify your Bug Triage email', body=
                  'Enter this verification code in the Bug Triage extension (or POST it as token to /auth/verify).\n\n'
                  + token + '\n\nThis code expires in one hour. If you did not request it, ignore this message.'))


@router.post('/auth/verify')
def verify(data: VerifyInput, db: Session = Depends(get_db)):
    # Lock the account as well as the token so resend/verification are serialized.
    digest = hashlib.sha256(data.token.encode()).hexdigest()
    item = db.get(Verification, digest)
    if item is None:
        raise HTTPException(400, 'Invalid or expired verification code')
    user = db.scalar(select(User).where(User.id == item.user_id).with_for_update())
    item = db.scalar(select(Verification).where(Verification.id == digest).with_for_update().execution_options(populate_existing=True))
    if item is None or item.expires_at <= now():
        raise HTTPException(400, 'Invalid or expired verification code')
    user.email = item.email
    user.active = True
    db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
    db.execute(delete(Verification).where(Verification.user_id == user.id))
    db.add(SystemAudit(actor_id=user.id, action='email_verified', details={}))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'This email address is unavailable')
    return {'message': 'Email verified. Sign in to continue.'}


@router.post('/auth/resend', status_code=202)
def resend(data: ResendInput, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == str(data.email).lower()).with_for_update())
    if user and not user.active:
        previous = db.scalar(select(Verification).where(Verification.user_id == user.id))
        if previous is None or previous.created_at < now() - timedelta(minutes=2):
            queue_verification(db, user, user.email)
            db.commit()
    return GENERIC_MESSAGE


@router.patch('/auth/me')
def update_account(data: AccountUpdate, db: Session = Depends(get_db), actor: User = Depends(current_user)):
    user = db.scalar(select(User).where(User.id == actor.id).with_for_update().execution_options(populate_existing=True))
    if any(v is None for k, v in data.model_dump(exclude_unset=True).items()):
        raise HTTPException(422, 'Supplied account fields may not be null')
    changed = []
    if data.name is not None:
        user.name = data.name
        changed.append('name')
    if data.preferences is not None:
        user.preferences = data.preferences.model_dump()
        changed.append('preferences')
    pending = False
    if data.email and str(data.email).lower() != user.email:
        if not data.current_password or not check_password(data.current_password, user.password_hash):
            raise HTTPException(401, 'Current password is required for an email change')
        email = str(data.email).lower()
        if db.scalar(select(User.id).where(User.email == email)) is not None:
            raise HTTPException(409, 'This email address is unavailable')
        queue_verification(db, user, email)
        pending = True
        changed.append('email_change_requested')
    if changed:
        db.add(SystemAudit(actor_id=user.id, action='account_updated', details={'fields': changed}))
    db.commit()
    return {'id': user.id, 'name': user.name, 'email': user.email, 'preferences': user.preferences, 'email_change_pending': pending}
