# AI Bug Tracking System

First implementation milestone for the capstone: a local FastAPI backend with relational persistence, project access control, bug lifecycle operations, and audit history.

## Run locally on Windows

Python 3.12 or newer is required. From this folder:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\scripts\start.ps1
```

Open http://127.0.0.1:8000/docs for the interactive API. The start script applies migrations and uses a temporary signing key unless `JWT_SECRET` is supplied. Restarting with a new key invalidates existing tokens.

1. Use `POST /auth/register` to create your account.
2. In another terminal, activate that account for local development:

   ```powershell
   .\.venv\Scripts\python.exe -m backend.manage you@example.com --role manager
   ```

3. Use `POST /auth/login`, copy `access_token`, and paste it into **Authorize** in the API documentation.
4. Create a project, register/activate other test users, and add their user IDs through the members endpoint. `/auth/me` shows the signed-in user's ID.
5. Submit a bug, assign it as a manager, and progress it through Open → In Progress → Resolved → Verified → Closed. The detail endpoint includes its audit history and comments.

## Database

SQLite is the zero-install local development option; the deployment target is PostgreSQL. Set `DATABASE_URL` before migrations and startup, for example:

```powershell
$env:DATABASE_URL = 'postgresql+psycopg://triage:YOUR_PASSWORD@localhost:5432/triage'
$env:JWT_SECRET = 'YOUR_RANDOM_SECRET_OF_AT_LEAST_32_CHARACTERS'
.\.venv\Scripts\python.exe -m alembic upgrade head
```

Supply secrets through your environment, never source control. No tables are created implicitly on startup. Alembic owns the schema. PostgreSQL must be installed separately; it was not available on the implementation machine.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest --cov=backend --cov-report=term-missing
```

Tests exercise access isolation, role restrictions, invalid transitions, assignment validation, audit history, filtering, archive behavior, password validation, session revocation, and eight-hour idle expiry. They use an isolated in-memory SQLite database. PostgreSQL deployment and load targets still require integration testing.

## Scope and remaining work

Implemented: pending registration, bcrypt password hashes, JWT bearer login with database-backed idle expiry and logout, manager-created projects, project membership roles, bug creation/list/detail/update, sequential status transitions, manual severity/assignment, comments, and transactional audit entries. Administrators can access all projects. Bug deletion is intentionally absent to preserve history.

This is a development backend, not the complete capstone product. Email ownership verification and SMTP delivery are not implemented; the local activation command is an explicit testing aid. AI models are not integrated: submissions remain Unclassified and disclose degraded triage. Developer profiles, duplicate detection, recommendations, background jobs, attachments, notifications, dashboard, and VS Code extension remain to be built. Profile creation/enrichment required by FR-20/22 is not yet triggered by membership or verification.

Other gaps: project rename/member removal, profile editing, date-range search, production rate limiting and TLS termination, concurrency hardening, and performance evaluation. FastAPI currently emits OpenAPI 3.1; the report's strict 3.0 requirement needs a validated compatibility export. No accuracy, latency, availability, or regulatory-compliance claims have been established.

Next milestones and report ambiguities are tracked in [docs/implementation-plan.md](docs/implementation-plan.md). Framework references: [FastAPI JWT authentication](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/) and [Alembic migrations](https://alembic.sqlalchemy.org/en/latest/tutorial.html).
