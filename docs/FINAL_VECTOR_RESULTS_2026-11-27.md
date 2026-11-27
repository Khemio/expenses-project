# Final vector benchmark — observed results (2026-11-27)

Source: user's completed terminal output from `python -m scripts.benchmark_vector_results`
on the existing **development** database, following the corrected
planner-sensitive benchmark implementation. These measurements are
observations of one small local run, not general performance guarantees.

## Dataset and configuration

- PostgreSQL/pgvector and Qdrant: **455** matching vector documents in each.
- Rare group: **23/455 = 5.05%**.
- Encoder: `sentence-transformers/all-MiniLM-L6-v2`, normalized vectors,
  cosine similarity.
- 20 fixed benchmark queries, `k=10`; per-store exact top-10 reference.
- PostgreSQL `hnsw.ef_search=64`,
  `hnsw.iterative_scan=off`; Qdrant requested `hnsw_ef=64`.
- PostgreSQL HNSW index `vector_documents_embedding_hnsw` exists.
- **Qdrant `indexed_vectors_count=0`**: HNSW was not established.
- PostgreSQL query plans: **20/20 unfiltered HNSW**; **20/20 filtered
  ordinary `vector_documents_filter_group_idx` + exact Sort**.

## Vector search results

| Scope | Store | Agreement with own exact top-10 | Average returned | Mean query latency |
| --- | --- | ---: | ---: | ---: |
| Unfiltered | PostgreSQL HNSW | 1.0000 | 10 | 8.946 ms |
| Unfiltered | Qdrant (ANN requested; full scan possible) | 1.0000 | 10 | 11.403 ms |
| Rare filter (5.05%) | PostgreSQL B-tree + exact sort | 1.0000 | 10 | 8.443 ms |
| Rare filter (5.05%) | Qdrant (ANN requested; full scan possible) | 1.0000 | 10 | 12.880 ms |

Cross-store top-10 ID overlap: **10.00/10** both unfiltered and filtered.
These are timings of a particular local setup; they are not statistically
meaningful speed rankings. The **filtered PostgreSQL 1.0000 is not an
HNSW recall result**, because the planner selected exact sorting.

## Controlled filtered-HNSW experiment — observed results (2026-11-27)

A second completed run used:

```powershell
python -m scripts.benchmark_vector_results --force-filtered-hnsw
```

This applies `SET LOCAL enable_sort=off` only during the filtered
queries, discouraging the normal B-tree-filter + exact-sort plan.
PostgreSQL's actual plans confirmed **20/20 filtered HNSW index scans**.
The source documents, filter, exact reference and search parameters stayed
the same as in the main evaluation.

| Metric, 20 filtered queries | Normal PostgreSQL plan | Forced PostgreSQL HNSW | Qdrant in forced-run comparison |
| --- | ---: | ---: | ---: |
| Exact top-10 agreement / recall@10 | **1.0000** | **0.8300** | 1.0000 |
| Mean results returned (limit 10) | **10.00** | **8.30** | 10.00 |
| Mean query latency | **8.443 ms** | **8.100 ms** | 13.137 ms |
| Plan | B-tree filter + exact Sort | HNSW + filter | HNSW not established |

- In the forced run, **query Q01 returned only 5/10** filtered results
  and had recall@10 **0.5**, despite 23 records matching the filter.
- Other outputs from the forced run: unfiltered PostgreSQL HNSW
  recall@10 **1.0000**, mean latency **7.511 ms**;
  unfiltered Qdrant top-10 agreement **1.0000**, mean **12.519 ms**.
- Under forced filtered HNSW, the cross-store top-10 ID overlap was
  **8.30/10**, versus **10.00/10** with the normal PostgreSQL plan.
- Both stores were queried with `k=10`, PostgreSQL
  `hnsw.ef_search=64`, `hnsw.iterative_scan=off`; Qdrant requested
  `hnsw_ef=64`, but `indexed_vectors_count=0` means this cannot be
  described as demonstrated Qdrant HNSW behavior.
- **Explanation:** with a highly selective filter, the approximate
  vector index retrieves candidates before applying the metadata
  condition; too few may survive when iterative scanning is off.
  PostgreSQL's normal plan instead evaluates distances among the
  small group of qualifying rows and returns a complete top ten.
- The apparent **0.343 ms** filtered latency reduction is not
  meaningful evidence of a speed advantage: these were two separate
  local runs with no warmup or statistical uncertainty estimate.
  The clear result is **reduced recall and incomplete results**.

This forced experiment is **not the default application query plan**.
It should be the preferred illustration of an incorrect filtered ANN result,
with the earlier duplicate false positives retained as a distinct
semantic-classification failure.

## Duplicate detection — fixed threshold 0.85

25 labelled pairs: 10 true duplicate pairs, 15 distinct pairs.

| | Predicted duplicate | Predicted distinct |
| --- | ---: | ---: |
| Actually duplicate | 10 TP | 0 FN |
| Actually distinct | 3 FP | 12 TN |

- **Precision: 10/(10+3) = 0.7692 (76.92%)**.
- **Recall: 10/(10+0) = 1.0000 (100%)**.
- False positives: `DUP16` (0.9033), `DUP18` (0.9045),
  `DUP21` (0.9039). All are *distinct* labelled receipts even though
  their text embeddings are highly similar. A cosine threshold alone
  incorrectly flags them as duplicates. This supports checking structured
  invoice number, vendor, date and amount before deciding duplication.
- This is **pairwise embedding cosine classification**, not an ANN
  nearest-neighbor recall measurement.

## Policy search — 20 labelled queries, top-5

Results matched between PostgreSQL and Qdrant:

| Interpretation | Recall@5 | MRR |
| --- | ---: | ---: |
| Strict canonical labelled ID | **18/20 = 0.9000** | **0.5783** |
| Equivalent repeated-policy group | **20/20 = 1.0000** | **0.9625** |

- Strict-ID misses: `POL12` and `POL15`, with returned IDs listed in
  the saved console output.
- There are **100 stored policy rows derived from 20 canonical passages**.
  Thus some retrievals select semantically equivalent copies rather than
  the specific canonical ID in the labels. The group-equivalence measure is
  explanatory, **not a replacement for strict-ID ground truth**.
- This uses exact cosine semantic retrieval with a policy-only filter,
  rather than testing ANN recall.

## SQL enrichment vs Qdrant + relational lookup

The script observed a PostgreSQL enriched row linked by
`receipt_expense_mapping`:
`receipt_001` → `expenses.id=5` (EUR 700, pending).
A Qdrant payload ID lookup followed by PostgreSQL business lookup
found the same linked expense.

The development vector text for `receipt_001` also included the appended
sentence *"Updated source note: this receipt was reviewed and its vendor
details were confirmed."* This differs from the checked-in
`data/vector_documents.json` content. The benchmark's 455-ID
preflight verified document IDs and filter/type metadata, **not text
or embedding equality with the source file**. That is a further
consistency limitation rather than an automatic source-refresh guarantee.

**Critical qualification:** `receipt_expense_mapping` is a synthetic
demonstration table, and the original `receipt_001` in the checked-in
dataset contains **EUR 580.89**, not EUR 700. Thus the association is
illustrative, **not a verified receipt-to-expense relationship**. It
demonstrates that PostgreSQL can join the vector row with business records
in one SQL statement, whereas retrieving Qdrant data requires a further
business-record lookup. The comparison does **not** establish end-to-end
retrieval performance or financial provenance.

## Suggested slide interpretation

1. **Architectural comparison:** PostgreSQL and Qdrant agree on top-10
   documents. On small filtered subsets the PostgreSQL optimizer sensibly
   chooses an exact plan. Qdrant does not report indexed vectors, so
   an HNSW-versus-HNSW speed claim would be false.
2. **Failure analysis:** the duplicate detector generated 3 false
   positives because different receipts can have similar descriptions.
   This is the best concrete example of one wrong result.
3. **Policy search:** strict-ID recall is 90%; the equivalent-passage
   measure gives context for repeated records and the label granularity.
4. **Constraints:** synthetic evaluation, one machine, repeated policy
   passages, no proven Qdrant HNSW usage, and an illustrative join mapping.
5. **Planner sensitivity:** a forced HNSW filtered run returned an average
   **8.30 of 10** results and recall@10 **0.83**, while the normal
   PostgreSQL plan used B-tree filtering and exact sorting to return all ten.

If the command is rerun, save the full output under
`presentation-evidence/final-vector-benchmark.txt` locally. This
Markdown document records the reported observations and their limits;
it is not a substitute for the original execution log.
