"""Two independent Neo4j paths can grant the same expense approver authority.

Run only via the safety-checked isolated runner:
    python scripts/run_integration_tests.py -s -v tests/integration/test_branching_delegation.py
"""
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from app.database.neo4j import get_driver
from app.services.authorization_service import (
    get_authorized_expense_ids,
    is_authorized_approver,
)
from app.services.money import to_cents


pytestmark = pytest.mark.integration
EXPENSE_DATE = date(2026, 11, 9)
EXPENSE_AMOUNT = Decimal("700.00")


@pytest.fixture
def branching_scenario(expense_scenario):
    """Owner -> Team A / Team B -> shared delegate; tagged for fixture cleanup."""
    s = expense_scenario
    with get_driver().session() as session:
        session.run(
            """
            MATCH (owner:Employee {employee_id: $owner_id})
                  -[:RESPONSIBLE_FOR]->
                  (cc:CostCentre {cost_centre_id: $cost_centre_id})
            MATCH (delegate:Employee {employee_id: $delegate_id})
            WHERE delegate.test_run_id = cc.test_run_id

            CREATE (team_a:Employee {
                name: 'Team A lead',
                test_employee_key: $a_key,
                test_run_id: cc.test_run_id
            })
            CREATE (team_b:Employee {
                name: 'Team B lead',
                test_employee_key: $b_key,
                test_run_id: cc.test_run_id
            })

            CREATE (owner)-[:DELEGATED_TO {
                test_branch: 'A', scope: cc.name,
                amount_limit_cents: 100000,
                valid_from: '2026-01-01', valid_to: '2026-12-31'
            }]->(team_a)
            CREATE (team_a)-[:DELEGATED_TO {
                test_branch: 'A', scope: cc.name,
                amount_limit_cents: 100000,
                valid_from: '2026-01-01', valid_to: '2026-12-31'
            }]->(delegate)

            CREATE (owner)-[:DELEGATED_TO {
                test_branch: 'B', scope: cc.name,
                amount_limit_cents: 100000,
                valid_from: '2026-01-01', valid_to: '2026-12-31'
            }]->(team_b)
            CREATE (team_b)-[:DELEGATED_TO {
                test_branch: 'B', scope: cc.name,
                amount_limit_cents: 100000,
                valid_from: '2026-01-01', valid_to: '2026-12-31'
            }]->(delegate)
            """,
            owner_id=s["employee_id"],
            cost_centre_id=s["cost_centre_id"],
            delegate_id=s["unauthorized_employee_id"],
            a_key=f"pytest-branch-A-{uuid4().hex}",
            b_key=f"pytest-branch-B-{uuid4().hex}",
        ).consume()

    # The parent expense_scenario fixture deletes nodes with the matching
    # test_run_id, and DETACH DELETE removes these relationships as well.
    return s


def _valid_paths(s):
    """Inspect which paths satisfy the same scope/amount/date rules as auth."""
    query = """
    MATCH (owner:Employee)-[:RESPONSIBLE_FOR]->
          (cc:CostCentre {cost_centre_id: $cost_centre_id})
    MATCH path = (owner)-[:DELEGATED_TO*1..5]->
          (delegate:Employee {employee_id: $delegate_id})
    WHERE ALL(rel IN relationships(path) WHERE
        rel.scope = cc.name
        AND rel.amount_limit_cents >= $amount_cents
        AND date(rel.valid_from) <= date($expense_date)
        AND date(rel.valid_to) >= date($expense_date)
    )
    RETURN [node IN nodes(path) | node.name] AS route
    ORDER BY route
    """
    with get_driver().session() as session:
        return [
            record["route"]
            for record in session.run(
                query,
                cost_centre_id=s["cost_centre_id"],
                delegate_id=s["unauthorized_employee_id"],
                amount_cents=to_cents(EXPENSE_AMOUNT),
                expense_date=EXPENSE_DATE.isoformat(),
            )
        ]


def _assert_authorized(s, expected):
    """Verify both the single-request check and approval-queue batch check."""
    delegate_id = s["unauthorized_employee_id"]
    assert is_authorized_approver(
        approver_id=delegate_id,
        cost_centre_id=s["cost_centre_id"],
        amount=EXPENSE_AMOUNT,
        expense_date=EXPENSE_DATE,
    ) is expected

    candidate = {
        "id": s["expense_id"],
        "employee_id": s["employee_id"],
        "cost_centre_id": s["cost_centre_id"],
        "amount": EXPENSE_AMOUNT,
        "expense_date": EXPENSE_DATE,
    }
    eligible = get_authorized_expense_ids(
        approver_id=delegate_id,
        candidates=[candidate],
    )
    assert (s["expense_id"] in eligible) is expected


def _revoke_owner_to_branch(s, branch):
    """Delete only the owner's grant into one specific branch."""
    with get_driver().session() as session:
        summary = session.run(
            """
            MATCH (owner:Employee {employee_id: $owner_id})
                  -[:RESPONSIBLE_FOR]->
                  (cc:CostCentre {cost_centre_id: $cost_centre_id})
            MATCH (owner)-[grant:DELEGATED_TO]->(middle:Employee)
            WHERE grant.test_branch = $branch
              AND middle.test_run_id = cc.test_run_id
            DELETE grant
            """,
            owner_id=s["employee_id"],
            cost_centre_id=s["cost_centre_id"],
            branch=branch,
        ).consume()
    assert summary.counters.relationships_deleted == 1


def test_two_paths_one_revoke_then_both_revoked(branching_scenario):
    s = branching_scenario

    paths = _valid_paths(s)
    assert len(paths) == 2
    assert {route[1] for route in paths} == {"Team A lead", "Team B lead"}
    _assert_authorized(s, True)

    print("\nBEFORE: 2 valid delegation paths; shared approver authorized")
    for route in paths:
        print("  path:", " -> ".join(route))

    _revoke_owner_to_branch(s, "A")
    paths = _valid_paths(s)
    assert len(paths) == 1
    assert paths[0][1] == "Team B lead"
    _assert_authorized(s, True)

    print("AFTER REVOKING A: 1 valid path; still authorized via Team B")

    _revoke_owner_to_branch(s, "B")
    assert _valid_paths(s) == []
    _assert_authorized(s, False)

    print("AFTER REVOKING B: 0 valid paths; no longer authorized")


def test_one_path_over_limit_does_not_invalidate_other(branching_scenario):
    s = branching_scenario

    with get_driver().session() as session:
        summary = session.run(
            """
            MATCH (owner:Employee {employee_id: $owner_id})
                  -[:RESPONSIBLE_FOR]->
                  (cc:CostCentre {cost_centre_id: $cost_centre_id})
            MATCH (owner)-[:DELEGATED_TO {test_branch: 'B'}]->
                  (middle:Employee)-[grant:DELEGATED_TO {test_branch: 'B'}]->
                  (delegate:Employee {employee_id: $delegate_id})
            WHERE middle.test_run_id = cc.test_run_id
            SET grant.amount_limit_cents = 50000
            """,
            owner_id=s["employee_id"],
            cost_centre_id=s["cost_centre_id"],
            delegate_id=s["unauthorized_employee_id"],
        ).consume()
    assert summary.counters.properties_set == 1

    paths = _valid_paths(s)
    assert len(paths) == 1
    assert paths[0][1] == "Team A lead"
    _assert_authorized(s, True)

    # Team B's path still exists physically, but its EUR 500 limit
    # cannot authorize this EUR 700 expense. Revoking A removes the
    # last *valid* path without deleting the Team B relationships.
    _revoke_owner_to_branch(s, "A")
    assert _valid_paths(s) == []
    _assert_authorized(s, False)

    print("\nAMOUNT LIMIT: Team B still has edges but cannot approve EUR 700")
    print("  after revoking valid Team A path: 0 eligible paths; denied")
