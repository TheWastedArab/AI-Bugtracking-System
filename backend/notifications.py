from sqlalchemy import select
from .models import Membership, Notification, Outbox, User, Watch


def notify(db, bug, event, actor_id):
    recipients = {bug.reporter_id}
    if bug.assignee_id:
        recipients.add(bug.assignee_id)
    recipients.update(db.scalars(select(Watch.user_id).where(Watch.bug_id == bug.id)))
    if event == 'critical':
        recipients.update(db.scalars(select(Membership.user_id).where(Membership.project_id == bug.project_id, Membership.role == 'manager')))
    members = set(db.scalars(select(Membership.user_id).where(Membership.project_id == bug.project_id)))
    message = f'Bug #{bug.id}: {bug.title} ({event})'
    for user_id in recipients & members:
        user = db.get(User, user_id)
        if not user or not user.active:
            continue
        db.add(Notification(user_id=user_id, project_id=bug.project_id, bug_id=bug.id, event=event, message=message))
        if user.preferences.get(event, True):
            db.add(Outbox(recipient=user.email, subject=f'Bug #{bug.id}: {event}', body=message))
    if event == 'critical':
        db.add(Outbox(channel='push', recipient='critical', subject='Critical bug reported', body=message))
