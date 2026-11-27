"""Show stale Redis delegation data and repair after Neo4j revocation.

Run through the isolated runner only:
    python scripts/run_integration_tests.py -s -v tests/integration/test_delegation_cache_revocation.py
"""
from datetime import date

import pytest

from app.database.neo4j import get_driver
from app.database.redis import get_redis_client
from app.services.approver_cache import (
    cache_approver_chain,
    get_cached_approver_chain,
    invalidate_approver_chain,
)
from app.services.authorization_service import is_authorized_approver
from app.services.delegation_management import revoke_direct_delegation

pytestmark = pytest.mark.integration
EXPENSE_DATE = date(2026, 11, 9)


@pytest.fixture
def direct_delegation(expense_scenario):
    s = expense_scenario
    owner_id = s["employee_id"]
    delegate_id = s["unauthorized_employee_id"]
    centre_id = s["cost_centre_id"]
    with get_driver().session() as session:
        session.run(
            """
            MATCH (owner:Employee {employee_id: $owner_id})
            MATCH (delegate:Employee {employee_id: $delegate_id})
            MATCH (cc:CostCentre {cost_centre_id: $centre_id})
            CREATE (owner)-[:DELEGATED_TO {
                scope: cc.name,
                amount_limit_cents: 100000,
                valid_from: '2026-01-01',
                valid_to: '2026-12-31'
            }]->(delegate)
            """,
            owner_id=owner_id,
            delegate_id=delegate_id,
            centre_id=centre_id,
        ).consume()

    cache_key = f"approver_chain:{delegate_id}"
    assert get_redis_client().get(cache_key) is None

    try:
        yield s
    finally:
        get_redis_client().delete(cache_key)
        # expense_scenario removes graph nodes/relationships at teardown.


def _authorized(s):
    return is_authorized_approver(
        approver_id=s["unauthorized_employee_id"],
        cost_centre_id=s["cost_centre_id"],
        amount=700,
        expense_date=EXPENSE_DATE,
    )


def test_revocation_invalidates_redis_chain(direct_delegation):
    s = direct_delegation
    delegate_id = s["unauthorized_employee_id"]

    cache_approver_chain(
        employee_id=delegate_id,
        approver_chain=[s["employee_id"], delegate_id],
        source_id=f"neo4j:cost-centre:{s['cost_centre_id']}",
    )
    cached_before = get_cached_approver_chain(delegate_id)
    ttl_before = get_redis_client().ttl(f"approver_chain:{delegate_id}")

    assert _authorized(s)
    assert cached_before["approver_chain"][-1] == delegate_id
    assert ttl_before > 0

    print("\nBEFORE: delegation exists; live authority=True; cached chain exists")
    print("  cache source:", cached_before["source_id"])
    print("  cache refreshed_at:", cached_before["refreshed_at"])
    print("  cache TTL seconds:", ttl_before)

    revoked = revoke_direct_delegation(
        owner_id=s["employee_id"],
        delegate_id=delegate_id,
        cost_centre_id=s["cost_centre_id"],
    )
    assert revoked == 1
    assert _authorized(s) is False
    assert get_cached_approver_chain(delegate_id) is None

    print("REVOKED: graph edge removed; live authority=False")
    print("INVALIDATED: Redis chain removed; subsequent read misses")

    # Retrying is safe even though the graph edge is already gone.
    assert revoke_direct_delegation(
        owner_id=s["employee_id"],
        delegate_id=delegate_id,
        cost_centre_id=s["cost_centre_id"],
    ) == 0
    assert get_cached_approver_chain(delegate_id) is None


def test_out_of_band_graph_change_leaves_stale_cache(direct_delegation):
    s = direct_delegation
    delegate_id = s["unauthorized_employee_id"]

    cache_approver_chain(
        employee_id=delegate_id,
        approver_chain=[s["employee_id"], delegate_id],
        source_id=f"neo4j:cost-centre:{s['cost_centre_id']}",
    )
    assert _authorized(s) is True

    # An uncoordinated graph-only change leaves the derived cache stale.
    with get_driver().session() as session:
        session.run(
            """
            MATCH (owner:Employee {employee_id: $owner_id})
                  -[grant:DELEGATED_TO]->
                  (delegate:Employee {employee_id: $delegate_id})
            DELETE grant
            """,
            owner_id=s["employee_id"],
            delegate_id=delegate_id,
        ).consume()

    cached_stale = get_cached_approver_chain(delegate_id)
    assert cached_stale is not None
    assert _authorized(s) is False

    print("\nSTALE: Neo4j says not authorized, Redis still stores old chain")
    print("  stale chain:", cached_stale["approver_chain"])
    print("  live authority:", _authorized(s))

    # Repeat the trusted mutation path: even if an earlier graph write
    # already removed the edge, a retry repairs cache invalidation.
    assert revoke_direct_delegation(
        owner_id=s["employee_id"],
        delegate_id=delegate_id,
        cost_centre_id=s["cost_centre_id"],
    ) == 0
    assert get_cached_approver_chain(delegate_id) is None
    assert _authorized(s) is False

    print("REPAIRED: Redis key absent after safe idempotent retry")


def test_revocation_fails_closed_when_redis_is_unavailable(
    direct_delegation, monkeypatch
):
    """Graph may commit before Redis fails; caller must see the failure."""
    import app.services.delegation_management as management

    s = direct_delegation

    def fail_invalidation(_employee_id):
        raise ConnectionError("Simulated Redis outage")

    monkeypatch.setattr(
        management, "invalidate_approver_chain", fail_invalidation
    )

    with pytest.raises(ConnectionError, match="Simulated Redis outage"):
        revoke_direct_delegation(
            owner_id=s["employee_id"],
            delegate_id=s["unauthorized_employee_id"],
            cost_centre_id=s["cost_centre_id"],
        )

    # The live authority check still uses Neo4j, never the stale cache.
    assert _authorized(s) is False
