
from decimal import Decimal
from datetime import date

import pytest

from app.database.postgres import get_connection

from app.services.exceptions import WorkflowError
from app.services.expense_workflow import approve_expense
from app.services.workflow_retry import approve_expense_with_retry


@pytest.mark.integration
def test_budget_conflict_retry_reevaluates_expense(decision_scenario):
    first_expense_id = decision_scenario["expense_id"]
    approver_id = decision_scenario["employee_id"]
    budget_id = decision_scenario["budget_id"]
    initial_version = decision_scenario["version"]

    
    with get_connection() as conn:
        second_expense_id = conn.execute(
            """
            INSERT INTO expenses (
                employee_id,
                cost_centre_id,
                budget_id,
                amount,
                description,
                expense_date
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                decision_scenario["submitter_id"],
                decision_scenario["cost_centre_id"],
                budget_id,
                Decimal("700.00"),
                "Expense requiring budget reevaluation",
                date(2026, 11, 9),
            ),
        ).fetchone()[0]

    decision_scenario["track_expense"](second_expense_id)


    # Start with 1000 EUR shared by two 700 EUR expenses.
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE budgets
            SET total = 1000, remaining = 1000
            WHERE id = %s
            """,
            (budget_id,),
        )

    # First expense consumes 700 EUR.

    first_result = approve_expense(
        expense_id=first_expense_id,
        approver_id=approver_id,
        expected_version=initial_version,
    )

    assert first_result["status"] == "approved"

    # Second request still has the old budget version.
    # Retry should reload the version and reevaluate.

    with pytest.raises(
        WorkflowError,
        match="Insufficient budget",
    ):
        approve_expense_with_retry(
            expense_id=second_expense_id,
            approver_id=approver_id,
            expected_version=initial_version,
            max_attempts=3,
        )

    with get_connection() as conn:
        budget = conn.execute(
            """
            SELECT remaining, version
            FROM budgets
            WHERE id = %s
            """,
            (budget_id,),
        ).fetchone()

        expenses = dict(
            conn.execute(
                """
                SELECT id, status
                FROM expenses
                WHERE id = ANY(%s)
                """,
                ([first_expense_id, second_expense_id],),
            ).fetchall()
        )

        decisions = conn.execute(
            """
            SELECT expense_id, decision
            FROM decisions
            WHERE expense_id = ANY(%s)
            ORDER BY id
            """,
            ([first_expense_id, second_expense_id],),
        ).fetchall()

    assert budget == (
        Decimal("300"),
        initial_version + 1,
    )

    assert expenses == {
        first_expense_id: "approved",
        second_expense_id: "pending",
    }

    assert decisions == [
        (first_expense_id, "approved"),
    ]
