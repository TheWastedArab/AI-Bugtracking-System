# AI Bug Tracking System

A VS Code extension and private FastAPI service for reporting, duplicate suggestions, severity classification, developer recommendations, and auditable project management.

This is a local capstone prototype. Real Eclipse/Mozilla experiments are recorded in [docs/evaluation.md](docs/evaluation.md). The severity model **does not meet the report's 85% target**; predictions are labelled experimental. Production and research acceptance are not claimed.

## Start the existing workspace

Use `github-repo` as the source of truth. The sibling source folders outside it contain the earlier backend increment.

```powershell
cd 'C:\Users\muham\Desktop\Capstone 2\github-repo'
.\scripts\start.ps1
```

The script applies migrations, loads local models when present, and serves the API at `http://127.0.0.1:8000`. It can reuse the Python environment already installed in the parent folder. Keep the terminal running. Set a persistent random `JWT_SECRET` to retain sessions across restarts; otherwise the script creates a temporary signing key.

Install `extension/capstone-bug-triage-1.0.0.vsix` using **Extensions → … → Install from VSIX** in VS Code. Run **Bug Triage: Open Workspace** from the Command Palette. `bugTriage.apiUrl` defaults to the local API. Tokens use VS Code SecretStorage and are scoped to the API origin.

For a fresh clone, install Python 3.12+ and Node.js 22+, then:

```powershell
.\scripts\setup.ps1 -AI
cd extension
npm ci
npm run package
cd ..
.\scripts\start.ps1
```

AI dependencies are optional for basic project management. `requirements.lock.txt` locks the base backend; `requirements-ai.lock.txt` records the experimental environment. Dataset files, models, databases, mail previews, and secrets are excluded from Git.

## Accounts and email previews

1. Register in the extension. Registration queues a verification email.
2. Run the email worker in another terminal:

   ```powershell
   ..\.venv\Scripts\python.exe -m backend.worker
   ```

   For a fresh clone, use `.\.venv\Scripts\python.exe`. Delivery defaults to `.mail-preview/*.eml` files. Copy the code from the newest verification email into **Verify email**. Codes expire after one hour and cannot be reused. Preview mode sends no external email.

3. Sign in. An operator can bootstrap the first manager/administrator:

   ```powershell
   ..\.venv\Scripts\python.exe -m backend.manage you@example.com --role admin
   ```

   This local command can activate an account and is never a public API endpoint. Normal users verify email through the application.

4. Create a project, add members by account ID, and assign roles. `/auth/me` shows a user's ID; administrators can also use the Admin screen.

For synthetic demo accounts, run `python -m backend.demo`. It generates and prints a temporary password and refuses to overwrite an existing demo. Benchmark identities are never imported as login accounts.

## Implemented features

- Registration/verification, email changes requiring the current password, preferences, bcrypt, JWT sessions, eight-hour idle expiry, logout, and database-backed authentication throttling.
- Four API-enforced roles; project creation, rename, archive, membership changes, removal, and last-manager protection.
- Submission, search, status/severity/assignee/date filters, duplicate links, comments, attachment handling, sequential lifecycle, manual assignment/severity, version checks, and transactional audits.
- A 600 ms duplicate-check debounce, BM25 top-50 retrieval, and local MiniLM reranking. Missing semantic weights produce explicitly labelled lexical suggestions.
- TF-IDF/SVM/Random Forest/Naive Bayes severity classification. Missing/failed models leave bugs Unclassified; administrators can enable an explicit keyword fallback.
- Developer skills/components, availability, capacity, workload, verified-resolution history, project cold start, rule-based recommendations, and CNN-LSTM training/inference. Managers decide assignments.
- Dashboard counts/activity/resolution times, watch lists, in-app events, email previews, SMTP, and self-hosted ntfy integration.
- Validated screenshots/logs, 10 MB limits, project-scoped downloads, and ClamAV hooks. Uploads fail closed without a scanner. `ALLOW_UNSCANNED_ATTACHMENTS=true` is a labelled local-demo exception.

Run assignment training separately so it cannot delay notifications:

```powershell
..\.venv\Scripts\python.exe -m backend.worker --train
```

Use one training worker per deployment. Training becomes eligible after 100 verified assigned bugs, then every 200 additional verifications or 30 days. Failed training retains the previous artifact. At least two assignees with sufficient examples are required; the count threshold alone does not guarantee a usable model.

## Reproduce the real-data experiments

From this workspace's repository root:

```powershell
..\.venv\Scripts\python.exe -m backend.datasets '../msr2013-bug_dataset-master/data/v02/eclipse' data/eclipse.jsonl
..\.venv\Scripts\python.exe -m backend.datasets '../msr2013-bug_dataset-master/data/v02/mozilla' data/mozilla.jsonl
..\.venv\Scripts\python.exe -m backend.training severity data/eclipse.jsonl --output artifacts/severity.joblib --cv 10
..\.venv\Scripts\python.exe -m backend.training assignment data/eclipse.jsonl --output artifacts/eclipse-assignment.pt --limit 30000 --epochs 6
..\.venv\Scripts\python.exe scripts/download-model.py
```

The supplied dataset has titles and histories but lacks descriptions and duplicate-to-original IDs. The converter uses earliest observed titles/components, maps final severity into four classes, excludes enhancements, and pseudonymizes assignees. Chronological holdouts remove exact-text duplicates and exclude training outcomes recorded after the split boundary.

`eclipse-assignment.pt` is an **offline evaluation artifact** with benchmark developer identities. Do not install it as a live project's model. The worker trains project models from that project's verified history and user IDs. Load only trusted local model files; joblib/pickle artifacts are executable formats.

Duplicate evaluation requires a JSONL corpus with real `duplicate_of` links:

```powershell
..\.venv\Scripts\python.exe -m backend.evaluate_duplicates data/linked-duplicates.jsonl --model artifacts/all-MiniLM-L6-v2
```

The evaluator refuses to infer original IDs from DUPLICATE status alone.

## Tests and API

```powershell
..\.venv\Scripts\python.exe -m pytest --cov=backend --cov-fail-under=70
..\.venv\Scripts\python.exe -m alembic check
..\.venv\Scripts\python.exe -m backend.openapi_export
```

Interactive API docs are at `/docs`. [docs/openapi.json](docs/openapi.json) is the validated OpenAPI 3.0.3 export; the live schema is OpenAPI 3.1. CI checks SQLite tests, PostgreSQL API tests, migrations, extension compilation, and VSIX packaging. [Testing instructions](docs/testing.md) describe the browser-based webview smoke test and its limits.

See [deployment](docs/deployment.md), [requirements traceability](docs/implementation-plan.md), and [evaluation](docs/evaluation.md). Live SMTP/ntfy, Docker deployment, a running malware scanner, the five-person usability study, full accessibility review, production PostgreSQL load testing, and availability monitoring still require environment-specific acceptance. The measured concurrency degradation exceeds the report's 10% target.
