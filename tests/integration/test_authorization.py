
from datetime import date
from decimal import Decimal

import pytest

from app.database.neo4j import get_driver
from app.services.money import to_cents
from app.services.authorization_service import is_authorized_approver

from app.services.authorization_service import (
    get_authorized_expense_ids,
)


@pytest.fixture
def delegated_scenario(expense_scenario):
    owner_id = expense_scenario["employee_id"]
    delegate_id = expense_scenario["unauthorized_employee_id"]
    centre_id = expense_scenario["cost_centre_id"]

    # Add a delegation between the fixture's existing employees.
    with get_driver().session() as session:
        session.run(
            """
            MATCH (owner:Employee {employee_id: $owner_id})
            MATCH (delegate:Employee {employee_id: $delegate_id})
            MATCH (cc:CostCentre {cost_centre_id: $centre_id})

            CREATE (owner)-[:DELEGATED_TO {
                scope: cc.name,
                amount_limit_cents: 100000,
                valid_from: date('2026-01-01'),
                valid_to: date('2026-12-31')
            }]->(delegate)
            """,
            owner_id=owner_id,
            delegate_id=delegate_id,
            centre_id=centre_id,
        ).consume()

    # The parent fixture removes these nodes and their
    # relationships at teardown.
    yield expense_scenario


@pytest.mark.integration
def test_owner_has_direct_authority(expense_scenario):
    assert is_authorized_approver(
        approver_id=expense_scenario["employee_id"],
        cost_centre_id=expense_scenario["cost_centre_id"],
        amount=700,
        expense_date=date(2026, 11, 9),
    )


@pytest.mark.integration
def test_delegation_within_limit(delegated_scenario):
    scenario = delegated_scenario

    assert is_authorized_approver(
        approver_id=scenario["unauthorized_employee_id"],
        cost_centre_id=scenario["cost_centre_id"],
        amount=700,
        expense_date=date(2026, 11, 9),
    )


@pytest.mark.integration
def test_delegation_exceeds_limit(delegated_scenario):
    scenario = delegated_scenario

    assert not is_authorized_approver(
        approver_id=scenario["unauthorized_employee_id"],
        cost_centre_id=scenario["cost_centre_id"],
        amount=1500,
        expense_date=date(2026, 11, 9),
    )


@pytest.mark.integration
def test_expired_delegation(delegated_scenario):
    scenario = delegated_scenario

    assert not is_authorized_approver(
        approver_id=scenario["unauthorized_employee_id"],
        cost_centre_id=scenario["cost_centre_id"],
        amount=700,
        expense_date=date(2027, 1, 1),
    )


@pytest.mark.integration
def test_delegation_revocation(delegated_scenario):
    scenario = delegated_scenario

    delegate_id = scenario["unauthorized_employee_id"]
    owner_id = scenario["employee_id"]
    centre_id = scenario["cost_centre_id"]

    def authorized():
        return is_authorized_approver(
            approver_id=delegate_id,
            cost_centre_id=centre_id,
            amount=700,
            expense_date=date(2026, 11, 9),
        )

    assert authorized()

    # Remove the delegation relationship.
    with get_driver().session() as session:
        session.run(
            """
            MATCH (owner:Employee {employee_id: $owner_id})
                  -[r:DELEGATED_TO]->
                  (delegate:Employee {employee_id: $delegate_id})

            DELETE r
            """,
            owner_id=owner_id,
            delegate_id=delegate_id,
        ).consume()

    # Authorization must reflect the revoked delegation.
    assert not authorized()


from uuid import uuid4


@pytest.mark.integration
@pytest.mark.parametrize(
    "first_limit, second_limit, first_valid_to, "
    "second_scope_valid, expected",
    [
        (1000, 800, "2026-12-31", True, True),
        (600, 1000, "2026-12-31", True, False),
        (1000, 600, "2026-12-31", True, False),
        (1000, 800, "2026-10-31", True, False),
        (1000, 800, "2026-12-31", False, False),
    ],
    ids=[
        "valid-two-hop-chain",
        "first-hop-amount-limit",
        "second-hop-amount-limit",
        "expired-first-hop",
        "wrong-second-hop-scope",
    ],
)
def test_multi_hop_delegation(
    expense_scenario,
    first_limit,
    second_limit,
    first_valid_to,
    second_scope_valid,
    expected,
):
    owner_id = expense_scenario["employee_id"]
    delegate_id = expense_scenario["unauthorized_employee_id"]
    centre_id = expense_scenario["cost_centre_id"]

    # This node is used only in the authorization graph.
    # PostgreSQL employee records are not needed for this test.
    intermediate_id = f"intermediate-{uuid4().hex}"

    with get_driver().session() as session:
        session.run(
            """
            MATCH (owner:Employee {employee_id: $owner_id})
            MATCH (delegate:Employee {employee_id: $delegate_id})
            MATCH (cc:CostCentre {cost_centre_id: $centre_id})

            CREATE (middle:Employee {
                name: 'Intermediate Test Delegate',
                test_employee_key: $intermediate_id,
                test_run_id: cc.test_run_id
            })

            CREATE (owner)-[:DELEGATED_TO {
                scope: cc.name,
                amount_limit_cents: $first_limit_cents,
                valid_from: '2026-01-01',
                valid_to: $first_valid_to
            }]->(middle)

            CREATE (middle)-[:DELEGATED_TO {
                scope: CASE
                    WHEN $second_scope_valid
                    THEN cc.name
                    ELSE 'Other Cost Centre'
                END,
                amount_limit_cents: $second_limit_cents,
                valid_from: '2026-01-01',
                valid_to: '2026-12-31'
            }]->(delegate)
            """,
            owner_id=owner_id,
            delegate_id=delegate_id,
            centre_id=centre_id,
            intermediate_id=intermediate_id,
            first_limit_cents=to_cents(first_limit),
            second_limit_cents=to_cents(second_limit),
            first_valid_to=first_valid_to,
            second_scope_valid=second_scope_valid,
        ).consume()

    # The parent fixture should delete the intermediate
    # node using the shared test_run_id.
    actual = is_authorized_approver(
        approver_id=delegate_id,
        cost_centre_id=centre_id,
        amount=700,
        expense_date=date(2026, 11, 9),
    )

    assert actual is expected



@pytest.mark.integration
@pytest.mark.parametrize(
    "amount, expected",
    [
        ("999.99", True),
        ("1000.00", True),
        ("1000.01", False),
        ("1000.02", False),
    ],
)
def test_delegation_monetary_boundaries(
    delegated_scenario,
    amount,
    expected,
):
    s = delegated_scenario
    delegate_id = s["unauthorized_employee_id"]
    centre_id = s["cost_centre_id"]
    expense_date = date(2026, 11, 9)
    decimal_amount = Decimal(amount)

    single_result = is_authorized_approver(
        approver_id=delegate_id,
        cost_centre_id=centre_id,
        amount=decimal_amount,
        expense_date=expense_date,
    )

    candidate = {
        "id": s["expense_id"],
        "employee_id": s["employee_id"],
        "cost_centre_id": centre_id,
        "amount": decimal_amount,
        "expense_date": expense_date,
    }

    batch_result = get_authorized_expense_ids(
        approver_id=delegate_id,
        candidates=[candidate],
    )

    assert single_result is expected
    assert (
        s["expense_id"] in batch_result
    ) is expected
