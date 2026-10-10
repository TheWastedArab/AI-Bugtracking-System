from sqlalchemy import func, select
from fastapi import HTTPException
from .ai import model_status, tokens
from .models import Bug, DeveloperProfile, Membership, ModelState, Resolution, now


def ensure_profile(db, project_id, user_id, role):
    profile = db.scalar(select(DeveloperProfile).where(DeveloperProfile.project_id == project_id, DeveloperProfile.user_id == user_id))
    if role in ('developer', 'manager'):
        if profile is None:
            db.add(DeveloperProfile(project_id=project_id, user_id=user_id))
    elif profile:
        profile.active = False


def protect_last_manager(db, project_id, member, new_role):
    if member and member.role == 'manager' and new_role != 'manager':
        count = db.scalar(select(func.count(Membership.id)).where(Membership.project_id == project_id, Membership.role == 'manager'))
        if count <= 1:
            raise HTTPException(409, 'Add another project manager before removing or demoting the last manager')


def validate_duplicate(db, project_id, duplicate_id, bug_id=None):
    seen = {bug_id} if bug_id else set()
    while duplicate_id is not None:
        if duplicate_id in seen:
            raise HTTPException(409, 'Duplicate links may not form a cycle')
        seen.add(duplicate_id)
        candidate = db.get(Bug, duplicate_id)
        if not candidate or candidate.project_id != project_id:
            raise HTTPException(400, 'Duplicate must reference a bug in this project')
        duplicate_id = candidate.duplicate_of


def enrich(db, bug):
    if bug.status != 'Verified' or bug.assignee_id is None:
        return
    if db.scalar(select(Resolution.id).where(Resolution.bug_id == bug.id)):
        return
    db.add(Resolution(project_id=bug.project_id, user_id=bug.assignee_id, bug_id=bug.id,
                      component=bug.component, severity=bug.severity,
                      keywords=sorted(set(tokens(bug.title + ' ' + bug.description)))[:100],
                      resolution_seconds=max(0, ((bug.resolved_at or now()) - bug.created_at).total_seconds())))
    db.flush()
    state = db.get(ModelState, bug.project_id)
    if state is None:
        state = ModelState(project_id=bug.project_id)
        db.add(state)
    status = model_status(db, bug.project_id)
    if not status['cold_start'] and (not state.trained_at or status['verified_assigned_count'] - state.trained_count >= 200):
        state.status = 'training_due'
