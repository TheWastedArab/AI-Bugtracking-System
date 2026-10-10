# Evaluation record

These results come from local experiments on 10 October 2026. They are observations, not proof that all capstone acceptance targets have been achieved. Machine-readable results are in [evaluation/](evaluation/).

## Dataset

The supplied MSR dataset's v02 JSON files contained 165,547 Eclipse and 394,878 Mozilla reports. After excluding missing text/severity and enhancements, normalization retained 141,451 Eclipse and 365,949 Mozilla records. These counts refer to the supplied v02 files, not the older counts in the dataset README.

Only earliest observed titles were available as text; full descriptions and duplicate-to-original links were absent. Final severity/assignee values came from histories. Developer addresses were pseudonymized. Training removes exact-text duplicates, splits chronologically, and excludes outcomes recorded after the training boundary.

## Severity

TF-IDF with SVM, Random Forest, and Naive Bayes majority voting was trained on 105,558 Eclipse records and tested on 27,696 later records. Ten-fold training-set cross-validation was also run.

| Measure | Result |
| --- | --- |
| Eclipse held-out accuracy | 70.53% |
| Eclipse macro F1 | 0.3252 |
| Eclipse weighted F1 | 0.6840 |
| Critical recall | 35.75% |
| Test-set majority-class baseline | 78.53% |
| Mozilla out-of-distribution accuracy, 365,949 records | 66.32% |
| Report target | 85% accuracy; not achieved |

The majority baseline exceeds the ensemble's accuracy, while minority-class performance remains weak. The current artifact is experimental and requires human review. The Mozilla evaluation uses its full normalized corpus; it is a distribution-shift check, not a separate model selection set. Do not describe this model as production validated.

## Assignment

The CNN-LSTM run used an evenly spaced 30,000-record sample from normalized Eclipse data, filtered to fixed reports and training assignees with sufficient examples. It trained for six epochs on 11,486 records and tested on 2,947 reports across 233 learned developer classes. The test set included 642 unseen assignees, counted as failures.

| Measure | Result |
| --- | --- |
| Top-1 accuracy | 15.88% |
| Top-3 accuracy | 26.43% |
| Top-5 accuracy | 33.66% |
| Simulated mean reassignments | 78.32 |
| Expected random baseline | 141.49 |
| Simulated reduction | 44.64% |

The reassignment simulation counts candidate rank minus one, exhausting the list for unseen assignees. It is not measured developer behavior. The reduction exceeds the report's 20% random-baseline target under this simulation, but low top-k accuracy and the limited sample remain material limitations. No cross-project assignment transfer result is claimed because project developer identities differ.

The offline artifact is not connected to live user accounts. Live project models train from that project's verified-resolution history, with declared skills, component fit, and capacity incorporated in recommendation ranking.

## Duplicate detection

The application runs BM25 followed by local all-MiniLM-L6-v2 similarity and supports graceful lexical fallback. Runtime inference was exercised through the UI. Recall@5, MRR, and MAP cannot be evaluated honestly from this dataset without original-bug links. The supplied evaluator requires those links and refuses status-only input.

## Local concurrency

A small synthetic SQLite QA project was tested with 50 concurrent requests after warmup. All 150 measured concurrent requests succeeded.

| Endpoint | Mean seconds | p95 seconds |
| --- | --- | --- |
| Search | 0.547 | 0.761 |
| Duplicate suggestions | 0.981 | 1.435 |
| Submission and triage | 1.194 | 1.852 |

The test includes local client connection setup. The database was small, not 50,000 bugs. Mean latency rose substantially against the sequential baseline, exceeding the 10% degradation target. These results cannot establish production throughput, a hard 1.5-second deadline for every request, or uptime.

A second run used over 50,000 synthetic bugs and the current cached sparse BM25 implementation. All 150 concurrent requests succeeded. The corpus and models were warmed first; edits can invalidate the retrieval index, so this does not measure cold rebuild latency.

| Endpoint | Mean seconds | p95 seconds |
| --- | --- | --- |
| Search | 0.623 | 0.835 |
| Duplicate suggestions | 1.289 | 1.585 |
| Submission and triage | 1.243 | 1.809 |

See `evaluation/load-50000.metrics.json`. Duplicate p95 remains above 1.5 seconds, and the 10% degradation target is not met. These synthetic SQLite results do not establish PostgreSQL production performance.

## Remaining acceptance evidence

Obtain full descriptions and linked duplicate ground truth; improve and reevaluate model quality; run realistic PostgreSQL load tests; complete the five-person usability study, formal accessibility review, live SMTP/push/scanner acceptance, backup/restore checks, and availability monitoring. The implementation and experimental results must remain distinguishable in the final capstone report.
