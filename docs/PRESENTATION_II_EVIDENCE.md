# Presentation II — evidence capture runbook

**Submission dates:** 2026-11-30 or 2026-12-07, as assigned by the course.
This is a guide to collecting actual outputs; **do not substitute the expected
results below for execution logs**.

## 1. Verified code behavior vs evaluation labels

- 123 integration tests and 55 unit tests passed on 2026-11-27, before the
  additional evidence-printing changes on this branch.
- The 25 labelled decision cases in `data/expense_test_cases.json` contain
  **9 approved, 11 rejected, 5 escalated** outcomes. These test
  `app/services/decision_service.py:evaluate_expense`, a **pure simplified
  evaluator**, not the complete transactional workflow (which checks
  Neo4j, MongoDB and a PostgreSQL budget).
- The duplicate dataset `data/duplicate_test_cases.json` has **25 pairs**:
  **10 positive** and **15 negative** labels.
- The policy dataset `data/policy_test_cases.json` contains **20 labelled
  queries**, with one relevant canonical policy ID per query.
- Existing file `data/filtered_benchmark_results.txt` describes an
  **earlier** 205-vector, 10-rare-record (4.88%) filtered experiment.
  **Do not present it as a 455-vector, 23-rare-record (5.05%) measurement.**
- Our isolated source-refresh experiment uses synthetic deterministic
  384-dimensional vectors to test version propagation. It is not a
  semantic retrieval-quality benchmark.

## 2. Capture actual saved system output

All commands below use the dedicated **test** Docker services. The runner
checks database identities and all stores' cleanup. Never invoke integration
tests directly with `pytest` against development databases.

```powershell
docker compose -f docker-compose.test.yaml up -d
```

Pure labelled evaluator results (no database writes):

```powershell
python -m scripts.report_labeled_decisions
```

This prints the 25-case denominator, expected outcome counts and mismatches.
It reports **only** the simplified evaluator.

Historical decision snapshot, before/after budget change:

```powershell
python scripts/run_integration_tests.py -s -v tests/integration/test_decision_evidence.py
```

Show the **actual PostgreSQL decision ID, timestamp, outcome, rule version,
source IDs, budget version and JSONB snapshot**. The report must distinguish
the decision-time balance from the subsequently changed current balance.
The receipt observation has a source ID, but the MongoDB receipt has no
tracked source version in the current workflow; the Neo4j path is likewise
not stored at edge-version granularity.

Two concurrent expenses competing for one EUR 1,000 budget:

```powershell
python scripts/run_integration_tests.py -s -v tests/integration/test_concurrency.py
```

The required case is `test_concurrent_expenses_sharing_budget`: expect one
EUR 700 approval, one conflict, EUR 300 remaining and exactly one
corresponding decision. Capture actual command output.

Missing receipt and MongoDB validation:

```powershell
python scripts/run_integration_tests.py -v tests/integration/test_receipt_evidence_gate.py tests/integration/test_mongo_receipts.py
```

Source v1 → stale vector copies → refreshed v2:

```powershell
python scripts/run_integration_tests.py -s -v tests/integration/test_source_refresh.py
```

The outputs include the source ID, both content versions, metadata and
timestamps for PostgreSQL and Qdrant.

Redis cache vs live Neo4j authorization:

```powershell
python scripts/run_integration_tests.py -s -v tests/integration/test_delegation_cache_revocation.py
```

Optional branching/converging Neo4j authorization evidence:

```powershell
python scripts/run_integration_tests.py -s -v tests/integration/test_branching_delegation.py
```

To save command output to files under a local, non-repository evidence folder,
PowerShell users can pipe a **single command** through `Tee-Object`, e.g.:

```powershell
New-Item -ItemType Directory -Force presentation-evidence
python scripts/run_integration_tests.py -s -v tests/integration/test_source_refresh.py 2>&1 | Tee-Object presentation-evidence/source-refresh.txt
```

This example writes files in a local directory, not into source code. Review
and redact any credentials before sharing logs. The test examples are synthetic.

## 3. Measurements that require an explicit evaluation run

The course handout requests the following, **with denominators, fixed
labels, computation methods, parameters and a misprediction/failure
explained**:

| Measurement | Cases | What to record |
| --- | ---: | --- |
| Expense outcome accuracy | 25 | Compare predicted vs expected; state pure evaluator vs production workflow |
| Duplicate-detection precision / recall | 25 pairs | TP, FP, FN, TN, threshold, treatment of near duplicates |
| Policy recall@5 and MRR | 20 queries | Relevant labels, ranks, misses, embedding model and document filter |
| pgvector ANN recall@10 | 20 fixed queries | ANN vs own exact, HNSW ef, iterative scan, latency |
| Qdrant ANN recall@10 | 20 fixed queries | ANN vs own exact, hnsw_ef, latency |
| Cross-store top-10 overlap | 20 fixed queries | Number of IDs appearing in both top-10 lists |
| ~5% filtered search | 20 fixed queries | Actual count/denominator, returned count, recall and latency |
| SQL join vs Qdrant lookup | One comparable query | PG SQL joins business rows in one statement; Qdrant needs separate business lookup |

**Current reproducibility gap:** The GitHub repository contains labels,
dataset generation scripts, and a historical saved filtered-results text file,
but not a clearly identifiable **current, complete benchmark runner** that
prints all the requested numbers for the final 455-document dataset.
Earlier experimental measurements must be reproduced or explicitly labelled
as historical/exploratory. The GitHub code base cannot by itself establish
the current live counts of your local development database.

Be particularly careful with filtered HNSW: an approximate index may retrieve
too few matching neighbors after selective filtering. Report pgvector's
`hnsw.ef_search`, iterative scan setting, the *returned result count*,
and recall against an exact filtered baseline. A small subset of records
and synthetic labels do **not** justify a claim of production-grade accuracy.

## 4. Recommended five-section slide order

1. **Three substantial changes since Presentation I**: versioned decision
   history, missing-receipt fail-closed checks, source-refresh consistency.
   For each show an actual before/after effect and a known limitation.
2. **Why five stores**: one actual query + result from PostgreSQL, MongoDB,
   Redis, Neo4j, and pgvector/Qdrant. Admit that PostgreSQL with JSONB,
   a cache table, or recursive CTEs could implement some of these.
3. **Real decision and concurrency**: `expense_workflow.py`, saved
   transaction, missing evidence and version conflict.
4. **Source change and measurements**: before/stale/after table and metrics
   with denominators; explain one wrong filtered ANN result.
5. **Historical explanation**: reconstruct a specific approved expense
   from the saved `decisions.evidence_snapshot` and rule version.

Optional backup slide: branching Neo4j two-path approval, addressing the
professor's question without crowding out required measured results.

## 5. Final report and hand-in

A **3–4 page report** must identify each store's role and principal query,
the decision and transaction semantics, the labelled measurement methodology
and outcomes, one incorrect result and its cause, and the source-change
consistency demonstration. Submit source code, actual test data and labels,
plus saved logs/outputs. The older PDF in `docs/coursework/` predates the
current API and evidence features and should **not** be submitted unchanged
as if it describes the present system.

Do not claim complete cross-database atomicity, automatic refresh,
complete historical Neo4j path versions, or that semantic search is used as
a hard precondition of production approvals; none of those are implemented.
