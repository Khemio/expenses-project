# Delegation revocation and Redis cache consistency

The original expense-approval assignment requires a demonstration of a **stale
cached approver chain after a Neo4j delegation is revoked**, followed by
cache invalidation. The tests in this change make that failure mode and repair
reproducible using the project's isolated Docker services.

## Run

```powershell
docker compose -f docker-compose.test.yaml up -d
python scripts/run_integration_tests.py -s -v tests/integration/test_delegation_cache_revocation.py
```

The runner verifies test-service identities before making writes. Tests create
their own graph delegation and Redis key, then clean up through existing
fixtures. Do **not** run these integration tests with plain pytest against
development databases.

## What is shown

| Scenario | Neo4j direct delegation | Redis approver chain | Live authorization |
| --- | --- | --- | --- |
| Before revocation | Present | Cached, with TTL | Authorized |
| Graph changed outside mutation service | Absent | **Stale** | Not authorized |
| After invalidation retry | Absent | Cache miss | Not authorized |
| Normal mutation service | Deleted | Invalidated | Not authorized |

`revoke_direct_delegation()` is a narrow, trusted operation that deletes
matching direct delegation relationships for a specific cost centre, then
invalidates the delegated employee's cached approver chain.

The graph write completes before invalidation. If Redis fails, the operation
**raises the failure**; the graph write may already have succeeded. Retrying
the same call will still attempt cache invalidation even if the Neo4j edge
was previously removed. This is safe because the mutation is idempotent and
ensures a failed earlier invalidation can be repaired.

## Why this doesn't make authorizations unsafe

**The production approval workflow always performs a fresh Neo4j authority
check**, including after an escalation. It does not treat the Redis chain as
a substitute for current graph authorization. Accordingly, a stale chain in
Redis is observable but cannot independently authorize an approval.

This is deliberately different from a vulnerable cache-authoritative design.
The correct lesson is to invalidate dependent data on source mutation **and**
retain a fresh authorization check for sensitive financial actions.

## Limits

- This is not a public delegation-management endpoint, and the trusted caller
  policy for modifying graph grants is not implemented here.
- The operation handles a **direct** grant scoped to a cost centre. It does not
  automatically discover every descendant cache entry affected by revoking
  an edge in a multi-hop delegation graph. Such changes require broader
  invalidation or revision-based cache keys.
- Redis and Neo4j cannot be committed together atomically. Production
  reliability would require a retry queue/outbox or reconciliation job.
- The approver-chain cache has a fixed TTL, but no read-through loader is
  implemented. A cache miss requires the consumer to consult Neo4j.
- Cache demonstration output uses isolated example records, not performance
  benchmarks.

Future graph work could add two branching delegation paths and verify that
revoking one path doesn't remove authority granted through another valid
path. That is a separate improvement, not needed to demonstrate cache
invalidation.
