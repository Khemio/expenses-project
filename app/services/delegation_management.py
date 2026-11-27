"""A narrow graph-mutation path that invalidates derived Redis authority data.

This module is not exposed as an administrative API. Callers must be trusted;
authorization to manage delegations is outside the prototype's scope.
"""

from app.database.neo4j import get_driver
from app.services.approver_cache import invalidate_approver_chain


def revoke_direct_delegation(
    *, owner_id: int, delegate_id: int, cost_centre_id: int
) -> int:
    """Remove direct grants for one cost centre and invalidate the delegate's cache.

    The Neo4j write commits before Redis is touched. Even if no graph edge
    remains, invalidate the cache: retrying after a Redis outage must repair
    any stale entry left by a previous successful graph commit.

    Returns the number of matching direct relationships deleted.
    """
    if any(value <= 0 for value in (owner_id, delegate_id, cost_centre_id)):
        raise ValueError("Employee and cost-centre IDs must be positive")

    query = """
    MATCH (owner:Employee {employee_id: $owner_id})
          -[:RESPONSIBLE_FOR]->
          (cc:CostCentre {cost_centre_id: $cost_centre_id})
    MATCH (owner)-[grant:DELEGATED_TO]->
          (delegate:Employee {employee_id: $delegate_id})
    WHERE grant.scope = cc.name
    WITH collect(grant) AS grants
    FOREACH (grant IN grants | DELETE grant)
    RETURN size(grants) AS revoked
    """

    def delete_grants(tx):
        record = tx.run(
            query,
            owner_id=owner_id,
            delegate_id=delegate_id,
            cost_centre_id=cost_centre_id,
        ).single()
        return int(record["revoked"]) if record else 0

    with get_driver().session() as session:
        revoked = session.execute_write(delete_grants)

    # Invalidate AFTER the graph commit. This is intentionally not an
    # atomic cross-store operation; Redis errors must propagate to callers.
    # Cache reads must never replace a fresh Neo4j authorization check.
    invalidate_approver_chain(delegate_id)
    return revoked
