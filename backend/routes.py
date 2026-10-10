import io
import os
from pathlib import Path
import subprocess
import tempfile
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from fastapi.responses import Response
from PIL import Image
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from . import ai
from .db import get_db
from .main import access, audit, find_bug
from .models import Attachment, Audit, Bug, Configuration, DeveloperProfile, LoginSession, Membership, ModelState, Notification, Project, Resolution, SystemAudit, User, Verification, Watch, now
from .schemas import AdminUserUpdate, BugCreate, ProfileUpdate, ProjectCreate, SettingsInput
from .security import current_user
from .services import ensure_profile, protect_last_manager

router = APIRouter()
Db = Depends(get_db)
Actor = Depends(current_user)


def admin(user):
    if user.global_role != 'admin':
        raise HTTPException(403, 'Administrator access required')


@router.patch('/projects/{project_id}')
def rename_project(project_id: int, data: ProjectCreate, db: Session = Db, user: User = Actor):
    project = access(db, user, project_id, 'manager', lock=True)
    audit(db, user, project_id, 'project_renamed', {'before': project.name, 'after': data.name})
    project.name = data.name
    db.commit()
    return project


@router.get('/projects/{project_id}/members')
def members(project_id: int, db: Session = Db, user: User = Actor):
    access(db, user, project_id)
    return [{'user_id': u.id, 'name': u.name, 'role': m.role} for m, u in db.execute(
        select(Membership, User).join(User).where(Membership.project_id == project_id).order_by(User.id))]


@router.delete('/projects/{project_id}/members/{user_id}', status_code=204)
def remove_member(project_id: int, user_id: int, db: Session = Db, user: User = Actor):
    access(db, user, project_id, 'manager', lock=True)
    member = db.scalar(select(Membership).where(Membership.project_id == project_id, Membership.user_id == user_id))
    if not member:
        raise HTTPException(404, 'Membership not found')
    protect_last_manager(db, project_id, member, None)
    active_bugs = db.scalars(select(Bug).where(Bug.project_id == project_id, Bug.assignee_id == user_id, Bug.status.not_in(['Verified', 'Closed']))).all()
    for bug in active_bugs:
        bug.assignee_id = None
        audit(db, user, project_id, 'bug_updated', {'assignee_id': {'before': user_id, 'after': None}}, bug.id)
    ensure_profile(db, project_id, user_id, 'removed')
    audit(db, user, project_id, 'membership_removed', {'user_id': user_id, 'role': member.role})
    db.delete(member)
    db.commit()


@router.get('/projects/{project_id}/audit')
def project_audit(project_id: int, offset: int = Query(0, ge=0), db: Session = Db, user: User = Actor):
    access(db, user, project_id, 'manager')
    return db.scalars(select(Audit).where(Audit.project_id == project_id).order_by(Audit.id.desc()).offset(offset).limit(100)).all()


@router.post('/projects/{project_id}/duplicates')
def duplicate_check(project_id: int, data: BugCreate, db: Session = Db, user: User = Actor):
    access(db, user, project_id)
    try:
        return ai.duplicates(db, project_id, data.title + ' ' + data.description)
    except Exception:
        return {'mode': 'unavailable', 'candidates': [], 'warning': 'Duplicate detection unavailable; you can still submit.'}


@router.get('/projects/{project_id}/dashboard')
def dashboard(project_id: int, db: Session = Db, user: User = Actor):
    access(db, user, project_id)
    counts = dict(db.execute(select(Bug.status, func.count()).where(Bug.project_id == project_id).group_by(Bug.status)).all())
    critical = db.scalar(select(func.count(Bug.id)).where(Bug.project_id == project_id, Bug.severity == 'Critical', Bug.status != 'Closed'))
    today = now().replace(hour=0, minute=0, second=0, microsecond=0)
    monday = today - timedelta(days=today.weekday())
    weeks = []
    for index in range(7, -1, -1):
        start = monday - timedelta(weeks=index)
        end = start + timedelta(weeks=1)
        values = []
        for column in (Bug.created_at, Bug.resolved_at):
            values.append(db.scalar(select(func.count(Bug.id)).where(Bug.project_id == project_id, column >= start, column < end)))
        weeks.append({'week': start.date().isoformat(), 'reported': values[0], 'resolved': values[1]})
    # Dialect-independent aggregation; timestamps are stored as naive UTC.
    resolved = db.execute(select(Bug.severity, Bug.created_at, Bug.resolved_at).where(Bug.project_id == project_id, Bug.resolved_at.is_not(None))).all()
    averages = {}
    for severity in ('Low', 'Medium', 'High', 'Critical', 'Unclassified'):
        durations = [(end - start).total_seconds() for label, start, end in resolved if label == severity]
        averages[severity] = sum(durations) / len(durations) if durations else None
    return {'counts': counts, 'critical': critical, 'weeks': weeks, 'average_resolution_seconds': averages, 'model': ai.model_status(db, project_id)}


@router.get('/projects/{project_id}/profiles')
def profiles(project_id: int, db: Session = Db, user: User = Actor):
    access(db, user, project_id)
    rows = db.scalars(select(DeveloperProfile).where(DeveloperProfile.project_id == project_id)).all()
    return [{'profile': p, 'name': db.get(User, p.user_id).name, 'workload': ai.workload(db, project_id, p.user_id),
             'history': db.scalars(select(Resolution).where(Resolution.project_id == project_id, Resolution.user_id == p.user_id).order_by(Resolution.id.desc()).limit(100)).all()} for p in rows]


@router.put('/admin/projects/{project_id}/profiles/{user_id}')
def edit_profile(project_id: int, user_id: int, data: ProfileUpdate, db: Session = Db, user: User = Actor):
    admin(user)
    access(db, user, project_id)
    member = db.scalar(select(Membership).where(Membership.project_id == project_id, Membership.user_id == user_id, Membership.role.in_(['developer', 'manager'])))
    if not member:
        raise HTTPException(400, 'A developer or manager membership is required')
    profile = db.scalar(select(DeveloperProfile).where(DeveloperProfile.project_id == project_id, DeveloperProfile.user_id == user_id))
    if profile is None:
        profile = DeveloperProfile(project_id=project_id, user_id=user_id)
        db.add(profile)
    before = {key: getattr(profile, key) for key in data.model_dump()}
    for key, value in data.model_dump().items():
        setattr(profile, key, value)
    audit(db, user, project_id, 'profile_updated', {'user_id': user_id, 'before': before, 'after': data.model_dump()})
    db.commit()
    return profile


@router.get('/admin/users')
def users(offset: int = Query(0, ge=0), db: Session = Db, user: User = Actor):
    admin(user)
    return [{'id': u.id, 'name': u.name, 'email': u.email, 'active': u.active, 'global_role': u.global_role} for u in db.scalars(select(User).order_by(User.id).offset(offset).limit(100))]


@router.patch('/admin/users/{user_id}')
def edit_user(user_id: int, data: AdminUserUpdate, db: Session = Db, user: User = Actor):
    admin(user)
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(404, 'User not found')
    if target.id == user.id and (not data.active or data.global_role != 'admin'):
        raise HTTPException(409, 'Administrators cannot deactivate or demote themselves')
    target.active, target.global_role = data.active, data.global_role
    db.execute(delete(LoginSession).where(LoginSession.user_id == user_id))
    db.execute(delete(Verification).where(Verification.user_id == user_id))
    db.add(SystemAudit(actor_id=user.id, action='user_updated', details={'user_id': user_id, **data.model_dump()}))
    db.commit()
    return {'id': target.id, 'active': target.active, 'global_role': target.global_role}


@router.get('/admin/settings')
def read_settings(db: Session = Db, user: User = Actor):
    admin(user)
    return ai.settings(db)


@router.put('/admin/settings')
def write_settings(data: SettingsInput, db: Session = Db, user: User = Actor):
    admin(user)
    row = db.get(Configuration, 'triage')
    if row is None:
        row = Configuration(key='triage', value=data.model_dump())
        db.add(row)
    else:
        row.value = data.model_dump()
    db.add(SystemAudit(actor_id=user.id, action='settings_updated', details=data.model_dump()))
    db.commit()
    return row.value


@router.get('/admin/models')
def models(db: Session = Db, user: User = Actor):
    admin(user)
    return [{'project_id': p.id, 'name': p.name, **ai.model_status(db, p.id)} for p in db.scalars(select(Project))]


@router.get('/notifications')
def notifications(db: Session = Db, user: User = Actor):
    allowed = select(Membership.project_id).where(Membership.user_id == user.id)
    query = select(Notification).where(Notification.user_id == user.id, Notification.project_id.in_(allowed))
    unread = db.scalar(select(func.count()).select_from(query.where(Notification.read.is_(False)).subquery()))
    return {'unread': unread, 'items': db.scalars(query.order_by(Notification.id.desc()).limit(100)).all()}


@router.post('/notifications/{notification_id}/read', status_code=204)
def read_notification(notification_id: int, db: Session = Db, user: User = Actor):
    item = db.get(Notification, notification_id)
    if not item or item.user_id != user.id:
        raise HTTPException(403, 'Access denied')
    access(db, user, item.project_id)
    item.read = True
    db.commit()


@router.put('/projects/{project_id}/bugs/{bug_id}/watch', status_code=204)
def watch(project_id: int, bug_id: int, enabled: bool = True, db: Session = Db, user: User = Actor):
    find_bug(db, user, project_id, bug_id)
    item = db.scalar(select(Watch).where(Watch.bug_id == bug_id, Watch.user_id == user.id))
    if enabled and item is None:
        db.add(Watch(bug_id=bug_id, user_id=user.id))
    elif not enabled and item:
        db.delete(item)
    db.commit()


def inspect_attachment(name, payload):
    if not name or len(name) > 200 or any(c in name for c in '/\\\r\n\x00') or name in ('.', '..'):
        raise HTTPException(422, 'Use a plain filename without path components')
    extension = Path(name).suffix.lower()
    if extension in ('.txt', '.log'):
        try:
            text = payload.decode('utf-8')
            if '\x00' in text:
                raise ValueError()
        except (UnicodeError, ValueError):
            raise HTTPException(422, 'Logs must contain UTF-8 text')
        media_type = 'text/plain'
    elif extension in ('.png', '.jpg', '.jpeg'):
        try:
            with Image.open(io.BytesIO(payload)) as image:
                if image.width * image.height > 25000000 or image.format not in ('PNG', 'JPEG'):
                    raise ValueError()
                media_type = 'image/png' if image.format == 'PNG' else 'image/jpeg'
                if (image.format == 'PNG') != (extension == '.png'):
                    raise ValueError()
                image.verify()
        except Exception:
            raise HTTPException(422, 'Invalid or oversized screenshot')
    else:
        raise HTTPException(422, 'Allowed attachments: PNG, JPEG, TXT, LOG')
    scanner = os.getenv('CLAMSCAN_PATH')
    clam_host = os.getenv('CLAMAV_HOST')
    if clam_host:
        import socket
        import struct
        try:
            with socket.create_connection((clam_host, int(os.getenv('CLAMAV_PORT','3310'))), timeout=30) as connection:
                connection.sendall(b'zINSTREAM\x00')
                for offset in range(0, len(payload), 65536):
                    chunk = payload[offset:offset+65536]
                    connection.sendall(struct.pack('!I',len(chunk)) + chunk)
                connection.sendall(struct.pack('!I',0))
                response = b''
                while not response.endswith(b'\x00') and len(response) < 4096:
                    part = connection.recv(4096)
                    if not part:
                        break
                    response += part
            if b'FOUND' in response:
                raise HTTPException(422,'Attachment rejected by malware scanner')
            if response.rstrip(b'\x00\n') != b'stream: OK':
                raise HTTPException(503,'Attachment scanner unavailable')
            scan = 'clamav-clean'
        except OSError:
            raise HTTPException(503,'Attachment scanner unavailable')
    elif scanner:
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'attachment'
            target.write_bytes(payload)
            try:
                result = subprocess.run([scanner, '--no-summary', str(target)], capture_output=True, timeout=30)
            except (OSError, subprocess.TimeoutExpired):
                raise HTTPException(503, 'Attachment scanner unavailable')
            if result.returncode == 1:
                raise HTTPException(422, 'Attachment rejected by malware scanner')
            if result.returncode != 0:
                raise HTTPException(503, 'Attachment scanner unavailable')
        scan = 'clamav-clean'
    elif os.getenv('ALLOW_UNSCANNED_ATTACHMENTS', 'false').lower() == 'true':
        scan = 'development-unscanned'
    else:
        raise HTTPException(503, 'Configure CLAMSCAN_PATH before uploading attachments')
    return media_type, scan


@router.post('/projects/{project_id}/bugs/{bug_id}/attachments', status_code=201)
def upload(project_id: int, bug_id: int, file: UploadFile, db: Session = Db, user: User = Actor):
    bug = find_bug(db, user, project_id, bug_id)
    member = db.scalar(select(Membership).where(Membership.project_id == project_id, Membership.user_id == user.id))
    if bug.reporter_id != user.id and user.global_role != 'admin' and member.role == 'reporter':
        raise HTTPException(403, 'Only the reporter or a developer may attach files')
    payload = file.file.read(10 * 1024 * 1024 + 1)
    if not payload or len(payload) > 10 * 1024 * 1024:
        raise HTTPException(413, 'Attachments must contain 1 byte to 10 MB')
    media_type, scan = inspect_attachment(file.filename, payload)
    item = Attachment(bug_id=bug_id, user_id=user.id, filename=file.filename, media_type=media_type, content=payload, scan_status=scan)
    db.add(item)
    db.flush()
    audit(db, user, project_id, 'attachment_added', {'attachment_id': item.id, 'filename': item.filename, 'scan_status': scan}, bug_id)
    db.commit()
    return {'id': item.id, 'filename': item.filename, 'scan_status': scan}


@router.get('/projects/{project_id}/bugs/{bug_id}/attachments')
def attachments(project_id: int, bug_id: int, db: Session = Db, user: User = Actor):
    find_bug(db, user, project_id, bug_id)
    return [dict(row._mapping) for row in db.execute(select(Attachment.id, Attachment.filename, Attachment.scan_status).where(Attachment.bug_id == bug_id))]


@router.get('/projects/{project_id}/bugs/{bug_id}/attachments/{attachment_id}')
def download(project_id: int, bug_id: int, attachment_id: int, db: Session = Db, user: User = Actor):
    find_bug(db, user, project_id, bug_id)
    item = db.get(Attachment, attachment_id)
    if not item or item.bug_id != bug_id:
        raise HTTPException(403, 'Access denied')
    from urllib.parse import quote
    return Response(item.content, media_type=item.media_type, headers={'Content-Disposition': "attachment; filename*=UTF-8''" + quote(item.filename, safe=''), 'X-Content-Type-Options': 'nosniff'})
