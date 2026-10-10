from datetime import timedelta
import os
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from backend.db import Base, get_db
from backend.main import app
from backend.models import LoginSession, Membership, User, now
from backend.security import hash_password


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv('JWT_SECRET', 'test-only-secret-that-is-at-least-32-characters')
    monkeypatch.setenv('SEVERITY_MODEL', 'artifacts/nonexistent-test-model.joblib')
    monkeypatch.delenv('SEMANTIC_MODEL_PATH', raising=False)
    database_url = os.getenv('TEST_DATABASE_URL')
    if database_url:
        schema = 'test_' + uuid.uuid4().hex
        owner = create_engine(database_url)
        with owner.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA {schema}'))
        engine = create_engine(database_url, connect_args={'options': f'-csearch_path={schema}'})
    else:
        engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        @event.listens_for(engine, 'connect')
        def foreign_keys(connection, _):
            connection.execute('PRAGMA foreign_keys=ON')
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    def database():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = database
    with factory() as db:
        hashed = hash_password('Testing123!')
        for name, role in [('manager', 'manager'), ('reporter', 'reporter'), ('developer', 'reporter'), ('outsider', 'reporter')]:
            db.add(User(email=f'{name}@example.com', name=name, password_hash=hashed, active=True, global_role=role))
        db.commit()
    with TestClient(app) as client:
        headers = {}
        for name in ['manager', 'reporter', 'developer', 'outsider']:
            response = client.post('/auth/login', json={'email': f'{name}@example.com', 'password': 'Testing123!'})
            assert response.status_code == 200
            headers[name] = {'Authorization': 'Bearer ' + response.json()['access_token']}
        project = client.post('/projects', json={'name': 'Checkout'}, headers=headers['manager']).json()['id']
        for user_id, role in [(2, 'reporter'), (3, 'developer')]:
            assert client.put(f'/projects/{project}/members', json={'user_id': user_id, 'role': role}, headers=headers['manager']).status_code == 200
        yield client, headers, project, factory
    app.dependency_overrides.clear()
    engine.dispose()
    if database_url:
        with owner.begin() as connection:
            connection.execute(text(f'DROP SCHEMA {schema} CASCADE'))
        owner.dispose()


def create_bug(client, headers, project):
    response = client.post(f'/projects/{project}/bugs', headers=headers['reporter'], json={
        'title': 'Checkout crashes', 'description': 'Checkout crashes when saving an empty shopping basket.',
        'steps': 'Open an empty basket and save', 'environment': 'Windows 11'})
    assert response.status_code == 201
    assert response.json()['bug']['severity'] == 'Unclassified'
    return response.json()['bug']['id']


def test_lifecycle_and_audit(setup):
    client, headers, project, _ = setup
    bug = create_bug(client, headers, project)
    path = f'/projects/{project}/bugs/{bug}'
    assert client.patch(path, headers=headers['developer'], json={'status': 'Closed'}).status_code == 409
    assert client.patch(path, headers=headers['reporter'], json={'status': 'In Progress'}).status_code == 403
    assert client.patch(path, headers=headers['developer'], json={'assignee_id': 3}).status_code == 403
    assert client.patch(path, headers=headers['manager'], json={'assignee_id': 4}).status_code == 400
    assert client.patch(path, headers=headers['manager'], json={'assignee_id': 3}).status_code == 200
    for state in ['In Progress', 'Resolved', 'Verified', 'Closed']:
        assert client.patch(path, headers=headers['developer'], json={'status': state}).status_code == 200
    assert client.post(path + '/comments', headers=headers['developer'], json={'body': 'Verified on Windows'}).status_code == 201
    detail = client.get(path, headers=headers['reporter']).json()
    assert detail['bug']['status'] == 'Closed'
    assert len(detail['audit']) == 7
    assert detail['comments'][0]['author_id'] == 3


def test_project_isolation_and_input_validation(setup):
    client, headers, project, _ = setup
    bug = create_bug(client, headers, project)
    path = f'/projects/{project}/bugs/{bug}'
    for resource in [f'/projects/{project}/bugs', path, '/projects/999/bugs']:
        response = client.get(resource, headers=headers['outsider'])
        assert response.status_code == 403
        assert response.json() == {'detail': 'Access denied'}
    assert client.get('/projects', headers=headers['outsider']).json() == []
    assert client.post('/projects', headers=headers['reporter'], json={'name': 'Forbidden'}).status_code == 403
    assert client.patch(path, headers=headers['developer'], json={'severity': None}).status_code == 422
    assert client.patch(path, headers=headers['developer'], json={'severity': 'Critical'}).status_code == 200
    assert client.get(f'/projects/{project}/bugs?q=Checkout&severity=Critical', headers=headers['reporter']).json()[0]['id'] == bug
    assert client.get(f'/projects/{project}/bugs?q=%25', headers=headers['reporter']).json() == []
    assert client.post(f'/projects/{project}/archive', headers=headers['manager']).status_code == 204
    assert client.post(f'/projects/{project}/bugs', headers=headers['reporter'], json={'title': 'Valid', 'description': 'A sufficiently detailed description', 'steps': 'Test', 'environment': 'Windows'}).status_code == 409


def test_sessions_and_registration(setup):
    client, headers, _, factory = setup
    assert client.get('/auth/me').status_code == 401
    assert client.get('/auth/me', headers={'Authorization': 'Bearer invalid'}).status_code == 401
    assert client.get('/auth/me', headers=headers['manager']).json()['global_role'] == 'manager'
    assert client.post('/auth/logout', headers=headers['manager']).status_code == 204
    assert client.get('/auth/me', headers=headers['manager']).status_code == 401
    with factory() as db:
        session = db.scalar(select(LoginSession).where(LoginSession.user_id == 2))
        session.last_seen = now() - timedelta(hours=9)
        db.commit()
    assert client.get('/auth/me', headers=headers['reporter']).status_code == 401
    payload = {'email': 'new@example.com', 'name': 'New user', 'password': 'Testing123!'}
    assert client.post('/auth/register', json=payload).status_code == 202
    assert client.post('/auth/register', json=payload).status_code == 202
    assert client.post('/auth/login', json={'email': payload['email'], 'password': payload['password']}).status_code == 401
    assert client.post('/auth/register', json={**payload, 'password': 'weak'}).status_code == 422
    assert client.post('/auth/register', json={**payload, 'global_role': 'admin'}).status_code == 422
    assert client.get('/health').json()['status'] == 'ok'
    assert client.get('/openapi.json').status_code == 200
