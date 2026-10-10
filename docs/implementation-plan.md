# Requirements implementation and acceptance

This matrix separates implemented behavior from outstanding acceptance evidence.

| Requirements | Behavior | Evidence or qualification |
| --- | --- | --- |
| FR-01–04 Accounts | Registration, verification, sessions, roles, name/email/preferences | API tests; live SMTP unverified |
| FR-05–09 Lifecycle | Submission, sequential states, search and filters, audits, comments | API/webview tests; 50,000-record synthetic SQLite test completed; latency/degradation targets not met |
| FR-10 Duplicates | Debounce, BM25 top 50, MiniLM top three, duplicate links | Local inference tested; linked ground truth missing |
| FR-11 Severity | TF-IDF ensemble, manual override, graceful fallback | Eclipse/Mozilla evaluation; 85% target not met |
| FR-12 Assignment | Top-three suggestions with reasons and manager decision | Rule-based API and CNN-LSTM tests |
| FR-13–14 Storage | Relational persistence, migrations, attachment validation/scanner hooks | PostgreSQL CI; live scanner acceptance outstanding |
| FR-15 Dashboard | Counts, weekly trend chart, mean resolution times | API/webview tests; refresh behavior documented in client |
| FR-16–17 Notifications | Outbox, SMTP, previews, ntfy, in-app unread events and watches | Preview/retry/TLS-mock tests; live SMTP/push unverified |
| FR-18–19 Projects | Create, rename, archive, membership changes/removal | Isolation and last-manager tests |
| FR-20–24 Profiles | Auto creation, declared skills/components, capacity, history and recommendations | API tests; workload counts Open/In Progress |
| FR-25–28 Cold start | Per-project threshold, manual/rule fallback, matching newcomer inclusion | API tests; usable training data required |
| FR-29 Retraining | Separate worker, 100/200/30-day triggers, atomic artifacts, visible failures | Training/inference tests; one training worker per deployment |
| NFR-01–03 Performance | Cached retrieval, startup loading, pagination, separate workers | Small local 50-request run; 10% degradation target not met |
| NFR-04–07 Security | bcrypt, scoped authorization, auth throttling, TLS deployment config, validation | Tests and dependency audit; no penetration-test claim |
| NFR-08–10 Reliability | DB sessions/outbox, pooled connections, AI fallbacks | Production scale and 99% availability unverified |
| NFR-11–12 Usability | Labels, native keyboard controls, focus styles, safe text rendering | Smoke/visual review; formal accessibility/user study outstanding |
| NFR-13 Tests/API | Coverage gate, SQLite/PostgreSQL CI, OpenAPI 3.0.3 export | Test results and CI |
| NFR-14 Configuration | Runtime duplicate/cold-start thresholds and severity fallback | Arbitrary severity-label names remain unsupported; four report labels are fixed |
| DC-01–05 Architecture | TypeScript extension, local FastAPI inference, relational DB, OpenAPI | No remote LLM calls or report uploads; model download is explicit |

## Design interpretations

- Duplicates remain stored and reference their original rather than being deleted.
- Developers/managers/admins may change status. Reporter-only testers cannot verify under the report's role table; its tester example conflicts with that table.
- Workload counts Open/In Progress. Verified history is append-only and assignees cannot change afterward.
- Profile enrichment happens in the verification transaction, before the successful response.
- New-developer inclusion requires matching declared skills. Rule-based and learned suggestions are distinguished.
- Retrieval uses explicit BM25; PostgreSQL full-text search is not described as BM25.
- Removed members lose data access immediately. Project audits preserve membership changes.

CodeRabbit and Snyk account integrations require repository-owner setup. CI does not replace human pull-request review. Better data/model quality and production/user-study evidence are necessary before the entire report can be marked accepted.
