# Tests

Run `python -m pytest --cov=backend --cov-fail-under=70`. SQLite fixtures enable foreign keys. `TEST_DATABASE_URL` enables PostgreSQL fixtures: each test creates a random `test_...` schema and removes only that schema. Use a disposable database, never production.

Tests cover verification/replay/expiry, email changes/session revocation, throttling, access isolation, roles, membership removal, last-manager protection, stale edits, statuses/audits, notification ownership, profile enrichment, workload, attachment validation, outbox retries, dataset conversion, model serialization, and API compatibility. PyTorch and OpenAPI-validator tests require their optional packages; CI base tests skip unavailable optional tools.

## Webview

`tests/webview-smoke.cjs` runs the actual client JavaScript in headless Chromium against an isolated API. It simulates the VS Code message bridge and tests login, dashboard, duplicates, submission, assignment/status, comments, team, notifications, settings, and admin. Screenshots are captured for visual review.

Install Playwright separately for this optional test. Set `PLAYWRIGHT_MODULE` if it is outside normal module resolution, `CHROME_PATH` for an installed Chromium executable, `QA_API` (default port 8765), and `QA_PASSWORD`. Seed a disposable database with `backend.demo` first. This is not a VS Code Extension Host or OS-keychain test; manually install the VSIX for final host acceptance.

## Load and models

Training instructions are in the README. The measured CNN-LSTM experiment used an evenly spaced 30,000-record input sample and six epochs. Preserve metrics and sampling options.

`python -m backend.benchmark --password YOUR_TEST_PASSWORD --project 1` warms three endpoints, measures five sequential calls, then runs 50 concurrent calls. It **creates synthetic bugs** and must target a disposable QA project. Client connection setup is included. This is not a production SLA test.

Duplicate Recall@K/MRR/MAP requires real duplicate-to-original links. Future/missing originals are excluded and retrieval statistics are built from older reports only.

## Dependencies

The locked base Python dependencies had no known advisories in the recorded `pip-audit` check. That check did not cover the optional AI tree.

The VS Code packaging dependency tree reports a high-severity `braces` advisory through `secretlint`. Compatible `npm audit fix` did not resolve it. This is a build-tool dependency, excluded from the VSIX; the extension has no runtime npm dependencies. Recheck before building untrusted workspaces and update the packaging tool when a fixed chain is available.
