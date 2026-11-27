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

If the command is rerun, save the full output under
`presentation-evidence/final-vector-benchmark.txt` locally. This
Markdown document records the reported observations and their limits;
it is not a substitute for the original execution log.
