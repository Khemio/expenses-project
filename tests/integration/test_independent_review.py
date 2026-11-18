
from decimal import Decimal

import pytest

from app.database.neo4j import get_driver
from app.database.postgres import get_connection
from app.services.exceptions import UnauthorizedApprover
from app.services.expense_workflow import (
    approve_expense,
    reject_expense,
)


pytestmark = pytest.mark.integration


def assign_reviewer(s):
    with get_driver().session() as session:
        session.run(
            """
            MATCH (reviewer:Employee {
                employee_id: $reviewer_id
            })
            MATCH (cc:CostCentre {
                cost_centre_id: $cost_centre_id
            })
            CREATE (reviewer)-[:REVIEWER_FOR]->(cc)
            """,
            reviewer_id=s["unauthorized_employee_id"],
            cost_centre_id=s["cost_centre_id"],
        ).consume()


def test_independent_reviewer_can_approve_owner_expense(
    expense_scenario,
):
    s = expense_scenario
    reviewer_id = s["unauthorized_employee_id"]

    assign_reviewer(s)

    result = approve_expense(
        expense_id=s["expense_id"],
        approver_id=reviewer_id,
        expected_version=s["version"],
    )

    assert result["status"] == "approved"
    assert result["approver_id"] == reviewer_id

    with get_connection() as conn:
        budget = conn.execute(
            """
            SELECT remaining, version
            FROM budgets
            WHERE id = %s
            """,
            (s["budget_id"],),
        ).fetchone()

    assert budget == (
        Decimal("1300"),
        s["version"] + 1,
    )


def test_independent_reviewer_can_reject_owner_expense(
    expense_scenario,
):
    s = expense_scenario
    reviewer_id = s["unauthorized_employee_id"]

    assign_reviewer(s)

    result = reject_expense(
        expense_id=s["expense_id"],
        approver_id=reviewer_id,
        expected_version=s["version"],
        reason="Missing supporting documents",
    )

    assert result["status"] == "rejected"

    with get_connection() as conn:
        budget = conn.execute(
            """
            SELECT remaining, version
            FROM budgets
            WHERE id = %s
            """,
            (s["budget_id"],),
        ).fetchone()

        decision = conn.execute(
            """
            SELECT approver_id, decision, comment
            FROM decisions
            WHERE expense_id = %s
            """,
            (s["expense_id"],),
        ).fetchone()

    assert budget == (Decimal("2000"), s["version"])
    assert decision == (
        reviewer_id,
        "rejected",
        "Missing supporting documents",
    )


def test_reviewer_cannot_decide_without_assignment(
    expense_scenario,
):
    s = expense_scenario

    with pytest.raises(UnauthorizedApprover):
        approve_expense(
            expense_id=s["expense_id"],
            approver_id=s["unauthorized_employee_id"],
            expected_version=s["version"],
        )

    with get_connection() as conn:
        status = conn.execute(
            """
            SELECT status
            FROM expenses
            WHERE id = %s
            """,
            (s["expense_id"],),
        ).fetchone()[0]

        decisions = conn.execute(
            """
            SELECT COUNT(*)
            FROM decisions
            WHERE expense_id = %s
            """,
            (s["expense_id"],),
        ).fetchone()[0]

    assert status == "pending"
    assert decisions == 0
