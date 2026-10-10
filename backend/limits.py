import hashlib
import time
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session
from .db import get_db
from .models import RateBucket


def auth_limit(request: Request, db: Session = Depends(get_db)):
    address = request.client.host if request.client else 'unknown'
    key = hashlib.sha256((address + '|' + request.url.path).encode()).hexdigest()
    window = int(time.time() // 60)
    if db.get_bind().dialect.name == 'postgresql':
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    statement = insert(RateBucket).values(key=key, window=window, hits=1)
    statement = statement.on_conflict_do_update(index_elements=['key','window'], set_={'hits': RateBucket.hits + 1}).returning(RateBucket.hits)
    hits = db.scalar(statement)
    db.commit()
    maximum = 10 if request.url.path in ('/auth/register','/auth/resend') else 30
    if hits > maximum:
        raise HTTPException(429, 'Too many authentication attempts. Try again shortly.', headers={'Retry-After':'60'})
