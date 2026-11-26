# Source changes and stale vector copies

This experiment demonstrates the distinction between an authoritative MongoDB receipt
and its **derived** copies in PostgreSQL/pgvector and Qdrant.

## Run it safely

Only use the isolated test runner (it verifies dedicated database identities before
doing any writes):

```powershell
docker compose -f docker-compose.test.yaml up -d
python scripts/run_integration_tests.py -s -v tests/integration/test_source_refresh.py
```

The test creates one unique receipt, one PostgreSQL vector row, and one Qdrant
point. It deletes all three even if an assertion fails, then the runner verifies
that no test records remain. Do not copy the commands into a development
database containing seeded data.

## What the outputs show

| Stage | MongoDB source version | pgvector copy version | Qdrant copy version |
| --- | ---: | ---: | ---: |
| BEFORE | 1 | 1 | 1 |
| STALE | 2 | 1 | 1 |
| REFRESHED | 2 | 2 | 2 |

1. Create a version-1 receipt and write derived content to both vector stores.
   Preserve `source_id`, `source_version`, and `refreshed_at`.
2. Edit the MongoDB receipt in place, using a conditional write on source
   version 1 and incrementing it to 2. At this point both vector copies still
   show the old content and version 1. Detect staleness by comparing their
   recorded version with MongoDB's version.
3. Re-read the current receipt and upsert the same document ID to PostgreSQL
   and Qdrant. Both copies now hold version 2, corrected content, and new
   refresh timestamps. One logical vector record remains in each store.

The printed evidence includes the source identifier, old and new content,
source versions, and both refresh timestamps. Use `-s` so pytest keeps these
lines visible. This is safe to capture for Presentation II.

**Test scope:** The deterministic 384-dimensional vectors are deliberately
synthetic. This verifies version tracking, stored content, and propagation
without downloading an embedding model; it does **not** measure embedding
quality or nearest-neighbor recall. The earlier benchmarks cover retrieval
quality separately.

## Why this design?

`source_id` identifies where the derived document came from;
`source_version` identifies **which state** was used to compute it; and
`refreshed_at` records when the copy was written. A timestamp alone cannot
prove that the current source was indexed.

The existing `store_documents()` upsert updates both stores while preserving
stable document IDs. The source-version field is optional to avoid fabricating
versions for pre-existing synthetic or policy documents.

**Limitations:** The test manually detects and repairs stale copies; the
production application does not yet run an automatic change detector, outbox,
or refresh worker. PostgreSQL commits its vector copy before Qdrant's upsert.
If Qdrant fails, the copies can disagree until a retry or reconciliation
repairs them. Moreover, version comparison presumes every authoritative source
update increments its version. This is an experiment on maintaining derived
data, not a distributed transaction or a fully automated synchronization
system.
