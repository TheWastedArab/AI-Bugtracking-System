from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError
from .db import get_db
from .models import Audit, Bug, Comment, LoginSession, Membership, Project, User
from .schemas import BugCreate, BugUpdate, CommentInput, Login, MemberInput, ProjectCreate, Registration, Severity, Status
from .security import check_password, current_session, current_user, hash_password, issue_token, signing_key
from .accounts import GENERIC_MESSAGE, queue_verification, router as accounts_router
from . import ai
from .notifications import notify
from .services import enrich, ensure_profile, protect_last_manager, validate_duplicate
from .limits import auth_limit


@asynccontextmanager
async def lifespan(app):
    signing_key()
    import os
    from pathlib import Path
    try:
        model_path = os.getenv('SEMANTIC_MODEL_PATH')
        if model_path:
            ai.semantic_model(model_path)
        severity_path = Path(os.getenv('SEVERITY_MODEL', 'artifacts/severity.joblib'))
        if severity_path.is_file():
            ai.severity_model(str(severity_path.resolve()), severity_path.stat().st_mtime_ns)
    except Exception:
        pass  # Request-level inference reports degraded functionality explicitly.
    yield


app = FastAPI(title='Capstone Bug Triage API', version='1.0.0', lifespan=lifespan)
app.include_router(accounts_router)


@app.exception_handler(StaleDataError)
async def stale_write(request, exc):
    return JSONResponse(status_code=409, content={'detail': 'Record changed concurrently. Refresh and retry.'})
Db = Depends(get_db)
Actor = Depends(current_user)
LEVELS = {'reporter': 1, 'developer': 2, 'manager': 3, 'admin': 4}
STATES = ['Open', 'In Progress', 'Resolved', 'Verified', 'Closed']


def access(db, user, project_id, minimum='reporter', lock=False):
    query = select(Project).where(Project.id == project_id)
    project = db.scalar(query.with_for_update() if lock else query)
    member = db.scalar(select(Membership).where(Membership.project_id == project_id, Membership.user_id == user.id))
    role = 'admin' if user.global_role == 'admin' else member.role if member else ''
    if not project or LEVELS.get(role, 0) < LEVELS[minimum]:
        raise HTTPException(403, 'Access denied')
    return project


def find_bug(db, user, project_id, bug_id, minimum='reporter', lock=False):
    access(db, user, project_id, minimum, lock=lock)
    bug = db.get(Bug, bug_id)
    if not bug or bug.project_id != project_id:
        raise HTTPException(403, 'Access denied')
    return bug


def audit(db, user, project_id, action, details, bug_id=None):
    db.add(Audit(actor_id=user.id, project_id=project_id, bug_id=bug_id, action=action, details=details))


@app.get('/health')
def health():
    return {'status': 'ok', 'ai': 'local-models-with-fallback'}


@app.post('/auth/register', status_code=202, dependencies=[Depends(auth_limit)])
def register(data: Registration, db: Session = Db):
    user = User(email=str(data.email).lower(), name=data.name, password_hash=hash_password(data.password))
    db.add(user)
    try:
        db.flush()
        queue_verification(db, user, user.email)
        db.commit()
    except IntegrityError:
        db.rollback()
    return GENERIC_MESSAGE


@app.post('/auth/login', dependencies=[Depends(auth_limit)])
def login(data: Login, db: Session = Db):
    user = db.scalar(select(User).where(User.email == str(data.email).lower()))
    if not user or not check_password(data.password, user.password_hash) or not user.active:
        raise HTTPException(401, 'Invalid credentials or inactive account')
    return {'access_token': issue_token(db, user), 'token_type': 'bearer', 'idle_timeout_seconds': 28800}


@app.post('/auth/logout', status_code=204)
def logout(session: LoginSession = Depends(current_session), db: Session = Db):
    db.delete(session)
    db.commit()


@app.get('/auth/me')
def me(user: User = Actor):
    return {'id': user.id, 'email': user.email, 'name': user.name, 'global_role': user.global_role, 'preferences': user.preferences}


@app.post('/projects', status_code=201)
def create_project(data: ProjectCreate, db: Session = Db, user: User = Actor):
    if user.global_role not in ('manager', 'admin'):
        raise HTTPException(403, 'Access denied')
    project = Project(name=data.name)
    db.add(project)
    db.flush()
    db.add(Membership(project_id=project.id, user_id=user.id, role='manager'))
    ensure_profile(db, project.id, user.id, 'manager')
    audit(db, user, project.id, 'project_created', {'name': data.name})
    db.commit()
    return project


@app.get('/projects')
def projects(db: Session = Db, user: User = Actor):
    query = select(Project)
    if user.global_role != 'admin':
        query = query.join(Membership).where(Membership.user_id == user.id)
    return db.scalars(query.order_by(Project.id)).all()


@app.put('/projects/{project_id}/members')
def set_member(project_id: int, data: MemberInput, db: Session = Db, user: User = Actor):
    access(db, user, project_id, 'manager', lock=True)
    target = db.get(User, data.user_id)
    if not target or not target.active:
        raise HTTPException(400, 'An active user is required')
    member = db.scalar(select(Membership).where(Membership.project_id == project_id, Membership.user_id == data.user_id))
    protect_last_manager(db, project_id, member, data.role)
    old_role = member.role if member else None
    if member is None:
        member = Membership(project_id=project_id, user_id=data.user_id, role=data.role)
        db.add(member)
    member.role = data.role
    ensure_profile(db, project_id, data.user_id, data.role)
    audit(db, user, project_id, 'membership_changed', {'user_id': data.user_id, 'before': old_role, 'after': data.role})
    db.commit()
    return member


@app.post('/projects/{project_id}/archive', status_code=204)
def archive(project_id: int, db: Session = Db, user: User = Actor):
    project = access(db, user, project_id, 'manager', lock=True)
    project.archived = True
    audit(db, user, project_id, 'project_archived', {})
    db.commit()


@app.post('/projects/{project_id}/bugs', status_code=201)
def create_bug(project_id: int, data: BugCreate, db: Session = Db, user: User = Actor):
    project = access(db, user, project_id, lock=True)
    if project.archived:
        raise HTTPException(409, 'Archived projects do not accept new bugs')
    validate_duplicate(db, project_id, data.duplicate_of)
    bug = Bug(project_id=project_id, reporter_id=user.id, **data.model_dump())
    label, mode, warning = ai.severity(data.title + ' ' + data.description, ai.settings(db))
    bug.severity = label
    bug.triage = {'mode': mode, 'message': warning}
    db.add(bug)
    db.flush()
    audit(db, user, project_id, 'bug_created', data.model_dump(), bug.id)
    if bug.severity == 'Critical':
        notify(db, bug, 'critical', user.id)
    db.commit()
    return {'bug': bug, 'triage': bug.triage, 'assignment': ai.recommendations(db, bug)}


@app.get('/projects/{project_id}/bugs')
def bugs(project_id: int, q: str = Query('', max_length=200), status: Status | None = None,
         severity: Severity | None = None, assignee_id: int | None = None,
         created_from: datetime | None = None, created_to: datetime | None = None,
         offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
         db: Session = Db, user: User = Actor):
    access(db, user, project_id)
    query = select(Bug).where(Bug.project_id == project_id)
    def utc(value):
        return value.astimezone(timezone.utc).replace(tzinfo=None) if value and value.tzinfo else value
    created_from, created_to = utc(created_from), utc(created_to)
    if created_from and created_to and created_from > created_to:
        raise HTTPException(422, 'created_from must precede created_to')
    if created_from:
        query = query.where(Bug.created_at >= created_from)
    if created_to:
        query = query.where(Bug.created_at < created_to)
    if q:
        query = query.where(or_(Bug.title.icontains(q, autoescape=True), Bug.description.icontains(q, autoescape=True)))
    for column, value in [(Bug.status, status), (Bug.severity, severity), (Bug.assignee_id, assignee_id)]:
        if value is not None:
            query = query.where(column == value)
    return db.scalars(query.order_by(Bug.id.desc()).offset(offset).limit(limit)).all()


@app.get('/projects/{project_id}/bugs/{bug_id}')
def bug_detail(project_id: int, bug_id: int, db: Session = Db, user: User = Actor):
    bug = find_bug(db, user, project_id, bug_id)
    return {'bug': bug, 'audit': db.scalars(select(Audit).where(Audit.bug_id == bug_id).order_by(Audit.id)).all(),
            'comments': db.scalars(select(Comment).where(Comment.bug_id == bug_id).order_by(Comment.id)).all(),
            'assignment': ai.recommendations(db, bug)}


@app.patch('/projects/{project_id}/bugs/{bug_id}')
def update_bug(project_id: int, bug_id: int, data: BugUpdate, db: Session = Db, user: User = Actor):
    bug = find_bug(db, user, project_id, bug_id, 'developer', lock=True)
    changes = data.model_dump(exclude_unset=True)
    expected_version = changes.pop('version', None)
    if expected_version is not None and expected_version != bug.version:
        raise HTTPException(409, 'Record changed. Refresh before updating.')
    if any(value is None and key not in ('assignee_id', 'duplicate_of') for key, value in changes.items()):
        raise HTTPException(422, 'Only assignee_id and duplicate_of may be null')
    if 'duplicate_of' in changes:
        validate_duplicate(db, project_id, changes['duplicate_of'], bug.id)
    if 'status' in changes and changes['status'] != bug.status:
        if STATES.index(changes['status']) != STATES.index(bug.status) + 1:
            raise HTTPException(409, 'Status must follow Open, In Progress, Resolved, Verified, Closed')
    if 'assignee_id' in changes:
        if bug.status in ('Verified', 'Closed') and changes['assignee_id'] != bug.assignee_id:
            raise HTTPException(409, 'Verified resolution history retains its original assignee')
        access(db, user, project_id, 'manager')
        if changes['assignee_id'] is not None:
            member = db.scalar(select(Membership).where(Membership.project_id == project_id, Membership.user_id == changes['assignee_id']))
            target = db.get(User, changes['assignee_id'])
            if not member or not target or not target.active:
                raise HTTPException(400, 'Assignee must be an active project member')
    detail = {k: {'before': getattr(bug, k), 'after': v} for k, v in changes.items() if getattr(bug, k) != v}
    for key, value in changes.items():
        setattr(bug, key, value)
    if 'status' in detail and bug.status == 'Resolved':
        from .models import now
        bug.resolved_at = now()
    if detail:
        audit(db, user, project_id, 'bug_updated', detail, bug.id)
        for field, event in [('status', 'status'), ('assignee_id', 'assignment')]:
            if field in detail:
                notify(db, bug, event, user.id)
        if 'severity' in detail and bug.severity == 'Critical':
            notify(db, bug, 'critical', user.id)
        enrich(db, bug)
    db.commit()
    return bug


@app.post('/projects/{project_id}/bugs/{bug_id}/comments', status_code=201)
def add_comment(project_id: int, bug_id: int, data: CommentInput, db: Session = Db, user: User = Actor):
    bug = find_bug(db, user, project_id, bug_id, 'developer', lock=True)
    comment = Comment(bug_id=bug_id, author_id=user.id, body=data.body)
    db.add(comment)
    db.flush()
    audit(db, user, project_id, 'comment_added', {'comment_id': comment.id}, bug_id)
    notify(db, bug, 'comment', user.id)
    db.commit()
    return comment


from .routes import router as product_router
app.include_router(product_router)
