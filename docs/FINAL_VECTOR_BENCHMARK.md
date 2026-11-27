# Final vector evaluation — Presentation II

The [read-only evaluation script](../scripts/benchmark_vector_results.py)
runs the complete fixed-label evaluation against the **existing development
datasets** in PostgreSQL/pgvector and Qdrant. This is separate from the
integration tests' isolated 3-document vectors and synthetic refresh experiment.

## Before running

- Both PostgreSQL and Qdrant must contain **exactly the same 455 document IDs**
  and matching `document_type` and `filter_group` metadata.
- Expect **23 rare documents out of 455 (5.05%)** if
  `app.database.prepare_rare_filter` was run on the 205+250 dataset.
- Check that the current `.env` points to your **development** databases, not
  the dedicated integration-test services.
- The script will *stop with an explanation*, not fill missing records,
  re-embed documents or change a filter configuration.
- The default command is **read-only**, including index checks and all searches.

Run from the repository root:

```powershell
python -m scripts.benchmark_vector_results
```

Save terminal evidence for your submission (the folder is local):

```powershell
New-Item -ItemType Directory -Force presentation-evidence
python -m scripts.benchmark_vector_results 2>&1 |
    Tee-Object presentation-evidence/final-vector-benchmark.txt
```

**Only if** the script explicitly reports that the PostgreSQL cosine HNSW index
is absent, you can elect to install it:

```powershell
python -m scripts.benchmark_vector_results --install-pg-hnsw
```

This optional command **changes your development PostgreSQL schema** by
adding an HNSW index and running ANALYZE. It does not create source documents.
Do not use it against an irreplaceable database without confirming your
connection and having a backup.

## Outputs and interpretation

| Evaluation | Inputs | Meaning |
| --- | --- | --- |
| ANN recall@10 (pgvector) | 20 fixed queries | Shared IDs with *PostgreSQL's own exact* top-10 divided by 10 |
| ANN recall@10 (Qdrant) | 20 fixed queries | Shared IDs with *Qdrant's own exact* top-10 divided by 10 |
| Cross-store overlap | Same 20 queries | Count of IDs in both ANN top-10 sets |
| Filtered search | Same 20 queries; `rare` | Exact and ANN comparisons, number returned and timing |
| Duplicate detection | 25 labelled pairs | TP, FP, FN, TN, precision and recall at a **fixed** cosine threshold (default 0.85) |
| Policy retrieval | 20 labelled queries | Exact cosine recall@5 and MRR, filtered to policy documents |
| SQL join vs Qdrant lookup | One query | Two different enrichment approaches when a valid receipt-to-expense mapping exists |

Defaults: `hnsw.ef_search=64` in pgvector, `hnsw_ef=64` in Qdrant,
`hnsw.iterative_scan=off`, and `k=10`.

**Observed on November 27, 2026:** With 455 total records and only 23
`rare` records, PostgreSQL's planner used the B-tree
`vector_documents_filter_group_idx` plus exact distance sorting instead of
the HNSW vector index for filtered search. This is sensible for small,
selective subsets. The script now checks the actual PostgreSQL plan
for each query; a recall score from this exact filtered path must not be
presented as *HNSW recall*. The initial user run stopped on this planner
choice before it could print duplicate/policy metrics.

The normal run retains this planner choice. To investigate a **controlled
HNSW filtered alternative** without modifying indexes or source data:

```powershell
python -m scripts.benchmark_vector_results --force-filtered-hnsw
```

This applies `SET LOCAL enable_sort=off` inside the filtered search
transactions, discouraging the exact B-tree-plus-sort plan; each query
still has its actual plan inspected and printed. This is a planner
experiment, **not PostgreSQL's normal search configuration**. The script
will warn if it still does not select HNSW.
You can explicitly compare the filtered pgvector setting:

```powershell
python -m scripts.benchmark_vector_results --iterative-scan strict_order
```

These search settings are scoped to each PostgreSQL query transaction.
The script verifies the actual PostgreSQL plan and labels queries that
use exact/planner-selected access separately from HNSW results.
Qdrant reported `indexed_vectors_count=0` on November 27; the results
may be full scans rather than HNSW. Do not describe this as a
demonstrated Qdrant HNSW speedup.

## Important honesty checks

1. **Duplicate detection measures text-pair similarity**, not Qdrant or
   pgvector ANN retrieval. The same MiniLM encoder embeds both strings and
   the threshold classifies each pair. The threshold is chosen in advance
   in the command (not tuned to the 25 labels here).
2. **Policy IDs repeat.** The 100 policy rows use 20 underlying passage
   texts. The official labelled IDs name one canonical document (e.g.
   `policy_001`); identical copies may crowd out the canonical ID.
   Accordingly the report prints both *strict canonical-ID* recall/MRR and
   *equivalent policy group* recall/MRR, clearly labelled. The latter is a
   supplementary metric, not a substitution for the original ground truth.
3. **ANN recall is not policy relevance recall.** It measures how closely
   an approximate index reproduces its exact nearest neighbors.
4. **Filtered recall can suffer from post-filtering.** Report the actual
   count of hits returned, the scan settings and the HNSW plan, not just
   recall as a single number.
5. The optional SQL join uses `receipt_expense_mapping` if it already
   contains valid data. This table is a demonstration mapping, not part of
   every production expense. If absent or empty, the script prints
   `SKIPPED` instead of fabricating a result.
6. Existing `data/filtered_benchmark_results.txt` describes **205 rows
   with 10 filtered** (4.88%), not the later **455 / 23** run. Keep those
   two experiments separate.
7. The script intentionally fails rather than silently overwrite indexed
   records, train models, or adjust labels. Its printed results are the
   actual values needed for the submission.

## Common blockers

- **PostgreSQL has fewer than 455 vectors:** inspect dev DB setup and the
  receipt-indexing process; do not run the benchmark on the isolated test DB.
- **Qdrant and PostgreSQL metadata disagree:** the script lists sample
  missing/mismatched IDs. Repair the underlying indexing inconsistency
  explicitly rather than hiding it.
- **No pgvector HNSW index:** check schema and consider the explicit
  `--install-pg-hnsw` option in development only.
- **No business join:** the old receipt mapping utility uses fixed integer
  IDs. Do not execute it blindly on a regenerated database. The report
  should state that this demonstration is missing until verified.
- **Model download:** `all-MiniLM-L6-v2` may need to be fetched once, unless
  it is already cached locally.
