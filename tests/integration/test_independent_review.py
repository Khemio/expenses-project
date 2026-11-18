
from decimal import Decimal

import pytest
from datetime import date
from uuid import uuid4

from app.database.neo4j import get_driver
from app.database.postgres import get_connection
from app.services.exceptions import UnauthorizedApprover, WorkflowError
from app.services.expense_workflow import (
    approve_expense,
    escalate_expense,
    reject_expense,
)
from app.services.authorization_service import (
    is_authorized_for_expense,
    get_authorized_expense_ids,
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



def test_owner_escalation_targets_independent_reviewer(
    expense_scenario,
):
    s = expense_scenario
    reviewer_id = s["unauthorized_employee_id"]

    assign_reviewer(s)

    result = escalate_expense(
        expense_id=s["expense_id"],
        employee_id=s["employee_id"],
        expected_version=s["version"],
    )

    assert result["status"] == "escalated"

    with get_connection() as conn:
        decision = conn.execute(
            """
            SELECT
                approver_id,
                target_approver_id,
                decision
            FROM decisions
            WHERE expense_id = %s
            """,
            (s["expense_id"],),
        ).fetchone()

    assert decision == (
        s["employee_id"],
        reviewer_id,
        "escalated",
    )

    completed = approve_expense(
        expense_id=s["expense_id"],
        approver_id=reviewer_id,
        expected_version=s["version"],
    )

    assert completed["status"] == "approved"


def test_owner_cannot_escalate_without_reviewer(
    expense_scenario,
):
    s = expense_scenario

    with pytest.raises(
        WorkflowError,
        match="No independent reviewer configured",
    ):
        escalate_expense(
            expense_id=s["expense_id"],
            employee_id=s["employee_id"],
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

        decision_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM decisions
            WHERE expense_id = %s
            """,
            (s["expense_id"],),
        ).fetchone()[0]

    assert status == "pending"
    assert decision_count == 0



def test_revoked_reviewer_cannot_complete_escalation(
    expense_scenario,
):
    s = expense_scenario
    reviewer_id = s["unauthorized_employee_id"]

    assign_reviewer(s)

    escalate_expense(
        expense_id=s["expense_id"],
        employee_id=s["employee_id"],
        expected_version=s["version"],
    )

    # Revoke reviewer authority after assignment.
    with get_driver().session() as session:
        session.run(
            """
            MATCH (reviewer:Employee {
                employee_id: $reviewer_id
            })-[r:REVIEWER_FOR]->
            (cc:CostCentre {
                cost_centre_id: $cost_centre_id
            })
            DELETE r
            """,
            reviewer_id=reviewer_id,
            cost_centre_id=s["cost_centre_id"],
        ).consume()

    with pytest.raises(
        WorkflowError,
        match="Assigned approver no longer has authority",
    ):
        approve_expense(
            expense_id=s["expense_id"],
            approver_id=reviewer_id,
            expected_version=s["version"],
        )

    with get_connection() as conn:
        status = conn.execute(
            """
            SELECT status FROM expenses WHERE id = %s
            """,
            (s["expense_id"],),
        ).fetchone()[0]

        budget = conn.execute(
            """
            SELECT remaining, version
            FROM budgets WHERE id = %s
            """,
            (s["budget_id"],),
        ).fetchone()

        decisions = conn.execute(
            """
            SELECT decision
            FROM decisions
            WHERE expense_id = %s
            ORDER BY id
            """,
            (s["expense_id"],),
        ).fetchall()

    assert status == "escalated"
    assert budget == (Decimal("2000"), s["version"])
    assert decisions == [("escalated",)]



from app.services.reviewer_service import (
    ReviewerConfigurationError,
)


def test_ambiguous_reviewers_fail_closed(
    expense_scenario,
):
    s = expense_scenario
    reviewer_id = s["unauthorized_employee_id"]

    assign_reviewer(s)

    # Add a conflicting reviewer assignment.
    with get_driver().session() as session:
        session.run(
            """
            MATCH (owner:Employee {
                employee_id: $owner_id
            })
            MATCH (cc:CostCentre {
                cost_centre_id: $cost_centre_id
            })
            CREATE (owner)-[:REVIEWER_FOR]->(cc)
            """,
            owner_id=s["employee_id"],
            cost_centre_id=s["cost_centre_id"],
        ).consume()

    # The single-expense authorization path
    # must not grant independent-review authority.
    with pytest.raises(ReviewerConfigurationError):
        approve_expense(
            expense_id=s["expense_id"],
            approver_id=reviewer_id,
            expected_version=s["version"],
        )

    # The batched authorization path must also
    # exclude the expense.
    from app.services.authorization_service import (
        get_authorized_expense_ids,
    )
    from datetime import date

    candidate = {
        "id": s["expense_id"],
        "employee_id": s["employee_id"],
        "cost_centre_id": s["cost_centre_id"],
        "amount": Decimal("700"),
        "expense_date": date(2026, 11, 9),
    }

    authorized_ids = get_authorized_expense_ids(
        approver_id=reviewer_id,
        candidates=[candidate],
    )

    assert s["expense_id"] not in authorized_ids



def test_independent_reviewer_cannot_approve_regular_employee(
    expense_scenario,
):
    s = expense_scenario

    owner_id = s["employee_id"]
    reviewer_id = s["unauthorized_employee_id"]
    regular_employee_id = None
    expense_id = None

    assign_reviewer(s)

    try:
        # Create a third employee in the same cost centre.
        with get_connection() as conn:
            regular_employee_id = conn.execute(
                """
                INSERT INTO employees (
                    name, email, cost_centre_id
                )
                VALUES (%s, %s, %s)
                RETURNING id
                """,
                (
                    "Regular Test Employee",
                    f"regular-{uuid4().hex}@example.test",
                    s["cost_centre_id"],
                ),
            ).fetchone()[0]

        # Create an expense belonging to that employee.
        expense_id = s["create_expense"](
            amount=250,
            description="Regular employee expense",
            employee_id=regular_employee_id,
        )

        expense_date = date(2026, 11, 9)

        # The ordinary owner remains authorized.
        assert is_authorized_for_expense(
            approver_id=owner_id,
            submitter_id=regular_employee_id,
            cost_centre_id=s["cost_centre_id"],
            amount=Decimal("250"),
            expense_date=expense_date,
        )

        # REVIEWER_FOR alone must not authorize Bob.
        assert not is_authorized_for_expense(
            approver_id=reviewer_id,
            submitter_id=regular_employee_id,
            cost_centre_id=s["cost_centre_id"],
            amount=Decimal("250"),
            expense_date=expense_date,
        )

        candidate = {
            "id": expense_id,
            "employee_id": regular_employee_id,
            "cost_centre_id": s["cost_centre_id"],
            "amount": Decimal("250"),
            "expense_date": expense_date,
        }

        assert expense_id not in get_authorized_expense_ids(
            approver_id=reviewer_id,
            candidates=[candidate],
        )

        # The actual workflow must reject the decision.
        with pytest.raises(UnauthorizedApprover):
            approve_expense(
                expense_id=expense_id,
                approver_id=reviewer_id,
                expected_version=s["version"],
            )

        with get_connection() as conn:
            status = conn.execute(
                """
                SELECT status
                FROM expenses
                WHERE id = %s
                """,
                (expense_id,),
            ).fetchone()[0]

        assert status == "pending"

    finally:
        # The factory tracks the expense, but this employee
        # must be removed before the parent fixture tears down.
        with get_connection() as conn:
            if expense_id is not None:
                conn.execute(
                    "DELETE FROM decisions WHERE expense_id = %s",
                    (expense_id,),
                )
                conn.execute(
                    "DELETE FROM expenses WHERE id = %s",
                    (expense_id,),
                )

            if regular_employee_id is not None:
                conn.execute(
                    "DELETE FROM employees WHERE id = %s",
                    (regular_employee_id,),
                )
