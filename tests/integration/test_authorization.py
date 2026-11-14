
from datetime import date

import pytest

from app.database.neo4j import get_driver
from app.services.authorization_service import is_authorized_approver


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
                amount_limit: 1000.0,
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
