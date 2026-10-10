"""Durable outbox delivery. Preview is the default and makes no network calls."""
import argparse
import os
from pathlib import Path
import smtplib
import ssl
from email.message import EmailMessage
from urllib.request import Request, urlopen
from sqlalchemy import select
from .db import SessionLocal
from .models import Outbox, now


def deliver(item):
    transport = os.getenv('MAIL_TRANSPORT', 'preview')
    if transport == 'preview':
        folder = Path(os.getenv('MAIL_PREVIEW_DIR', '.mail-preview'))
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f'{item.id:08d}.eml'
        target.write_text(f'To: {item.recipient}\nSubject: {item.subject}\nChannel: {item.channel}\n\n{item.body}', encoding='utf-8')
        return
    if transport != 'smtp':
        raise ValueError('MAIL_TRANSPORT must be preview or smtp')
    if item.channel == 'push':
        url = os.environ['NTFY_URL'].rstrip('/')
        if not url.startswith('https://') or 'ntfy.sh' in url.lower():
            raise ValueError('Use an HTTPS self-hosted ntfy URL')
        request = Request(url, data=item.body.encode(), method='POST', headers={'Authorization': 'Bearer ' + os.environ['NTFY_TOKEN']})
        with urlopen(request, timeout=10) as response:
            response.read(1024)
        return
    message = EmailMessage()
    message['From'] = os.environ['SMTP_FROM']
    message['To'] = item.recipient
    message['Subject'] = item.subject
    message.set_content(item.body)
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    host = os.environ['SMTP_HOST']
    mode = os.getenv('SMTP_SECURITY', 'starttls')
    if mode not in ('ssl', 'starttls'):
        raise ValueError('SMTP_SECURITY must be ssl or starttls')
    port = int(os.getenv('SMTP_PORT', '465' if mode == 'ssl' else '587'))
    connection = smtplib.SMTP_SSL(host, port, timeout=10, context=context) if mode == 'ssl' else smtplib.SMTP(host, port, timeout=10)
    with connection as server:
        if mode == 'starttls':
            server.starttls(context=context)
        if os.getenv('SMTP_USER'):
            server.login(os.environ['SMTP_USER'], os.environ['SMTP_PASSWORD'])
        server.send_message(message)


def drain(factory=SessionLocal, limit=100):
    delivered = 0
    # Row locks allow several PostgreSQL workers; use only one worker with SQLite.
    with factory() as db:
        items = db.scalars(select(Outbox).where(Outbox.delivered_at.is_(None), Outbox.attempts < 5)
                           .order_by(Outbox.id).limit(limit).with_for_update(skip_locked=True)).all()
        for item in items:
            item.attempts += 1
            try:
                deliver(item)
                item.delivered_at = now()
                item.error = None
                # Verification codes need not remain in delivered database rows.
                item.body = '[delivered]'
                delivered += 1
            except Exception as exc:
                item.error = type(exc).__name__  # Never store credentials or message bodies in errors.
        db.commit()
    return delivered


if __name__ == '__main__':
    argparse.ArgumentParser(description='Deliver pending mail; default is local .mail-preview files').parse_args()
    print(f'Delivered {drain()} outbox items')
