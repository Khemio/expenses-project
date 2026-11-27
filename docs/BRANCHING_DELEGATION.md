# Branching and converging Neo4j delegation paths

This isolated integration experiment addresses the professor's question about
whether the approval graph can express more than a simple employee-to-manager
relationship. The **production** authorization service already traverses
delegation paths of length 0 through 5. This scenario supplies a more complex
graph to that existing query; it does not change application rules.

## Graph

```text
                 Cost centre
                       ^
                RESPONSIBLE_FOR
                       |
                      Owner
                    /       \
          DELEGATED_TO       DELEGATED_TO
                 /             \
          Team A lead       Team B lead
                 \             /
          DELEGATED_TO       DELEGATED_TO
                    \       /
                 Shared delegate
```

All delegation relationships carry the cost-centre scope, amount limit and
validity interval. For an expense of EUR 700 on 2026-11-09, both paths are
valid initially.

## Run

```powershell
docker compose -f docker-compose.test.yaml up -d
python scripts/run_integration_tests.py -s -v tests/integration/test_branching_delegation.py
```

Only run through `scripts/run_integration_tests.py` so isolated PostgreSQL,
Neo4j, MongoDB, Redis and Qdrant credentials are verified first. The fixture
creates its own test-tagged graph nodes and cleans them up automatically.

## Expected result

| State | Valid paths | Shared delegate authorized? |
| --- | ---: | --- |
| Both Team A and Team B paths exist | 2 | Yes |
| Revoke the owner's grant to Team A | 1 | Yes, via Team B |
| Revoke the owner's grant to Team B | 0 | No |
| Team B limited to EUR 500 | 1 valid path for EUR 700 | Yes, via Team A |
| Then revoke Team A | 0 valid paths | No |

The test exercises the **same** `is_authorized_approver()` function used by
the workflow and the `get_authorized_expense_ids()` batch/queue query, so
the demonstration is not simply a hand-written query that bypasses our
existing authorization logic.

## Why this is more than a simple SQL join

An organization can have several independent chains of delegated authority,
with different relationship-specific scope, maximum amount and dates.
We require *at least one entire path* from the cost-centre owner to the
candidate approver in which every relationship is valid. Losing one path
does not revoke permission when another remains valid.

PostgreSQL can express this model with a recursive CTE. Neo4j is not strictly
required; it makes variable-length traversal and edge-specific predicates
particularly natural. It is also well-suited to explaining *which route*
grants authority.

## Limitations

This scenario uses **graph-only intermediate test employees** and a single
shared delegate for one cost centre. It does not create multiple independent
reviewers for an owner's own expenses, implement manager delegation
administration through the API, or modify the Redis cache's multi-hop
invalidation strategy. The cache currently invalidates a direct delegate;
fully reliable cache invalidation for branching graph updates would need
dependency tracking or graph revision/version-based cache keys.

This test is intentionally an **extra explanation of Neo4j's role**, not
a replacement for the required Redis revocation or source-refresh evidence.
