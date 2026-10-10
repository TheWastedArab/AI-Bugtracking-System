# Implementation plan

The source report selects FastAPI, SQLAlchemy/Alembic, PostgreSQL, a TypeScript VS Code extension, local model inference, and self-hosted notifications. This implementation begins with its Sprint 3 backend foundation.

| Milestone | Work | Acceptance evidence |
| --- | --- | --- |
| Backend foundation (started) | Authentication, project roles, bug lifecycle, comments, audits, migrations | Automated API tests; local API demonstration |
| Backend completion | Email verification, profile editing, project rename/removal, date filters, PostgreSQL integration, concurrency control | Security and PostgreSQL integration tests |
| Severity and duplicates | Dataset ingestion and leakage-safe splits; TF-IDF ensemble; BM25 then MiniLM ranking; explicit fallback modes | Held-out evaluation, project isolation, latency measurements |
| Profiles and assignment | Admin-declared skills/components, capacity and availability, verified resolution history, project cold start, rule-based and trained recommendations | Capacity/new-developer tests; reproducible assignment evaluation |
| VS Code client | SecretStorage authentication, project/bug views, submission, debounced duplicate checks, assignment and audit views | Extension integration tests and user task study |
| Notifications and delivery | In-app events, SMTP, self-hosted ntfy, attachment validation/scanning, dashboard, CI and deployment | End-to-end, security, load and accessibility checks |

## Decisions to settle before later milestones

- FR-23 counts workload in Open/In Progress; FR-20 says not yet closed and the narrative decrements at Verified. Use FR-23 for recommendation capacity unless the team revises the requirement.
- FR-06 says transitions require authorized roles; the workflow allows a tester to verify while FR-03 limits reporters to view/submit. Current backend permits developers/managers/admins to transition. Decide whether verification needs a separate permission or reporter exception.
- Use the detailed NFR-02 budgets (1.5 seconds for duplicate/severity, 3 seconds for assignment), and measure the full submission path separately; earlier sections imply one global budget.
- FR-26 suppresses learned recommendations during cold start; FR-27 allows explicitly labelled rule-based suggestions. Reaching 100 verified assigned bugs should trigger training, but serving a learned model must wait for successful validation and atomic activation.
- Retain duplicate reports and link their originals as in Section 3.5; do not follow the earlier narrative suggesting duplicates are removed before storage.
- PostgreSQL full-text search is not itself BM25. The retrieval module needs an explicit BM25 implementation or a deliberately selected database extension.

## Team workflow

Use feature branches and pull requests. Human review, issue ownership, CodeRabbit and Snyk are described in the report but are not configured automatically by this initial local implementation. Do not mark report targets as achieved merely because the API endpoints exist.
