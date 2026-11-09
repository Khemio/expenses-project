import os

import psycopg
from dotenv import load_dotenv

from app.services.expense_workflow import (
    WorkflowError,
    process_expense,
)

load_dotenv()


def main():
    budget_id = None
    expense_id = None

    try:
        # Create isolated test records.
        with psycopg.connect(os.getenv("DATABASE_URL")) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO budgets
                        (cost_centre_id, total, remaining)
                    VALUES (1, 2000, 2000)
                    RETURNING id, version
                    """
                )

                budget_id, version = cur.fetchone()

                cur.execute(
                    """
                    INSERT INTO expenses (
                        employee_id,
                        cost_centre_id,
                        budget_id,
                        amount,
                        description,
                        expense_date
                    )
                    VALUES (
                        1, 1, %s, 1500,
                        'Escalation assignment test',
                        '2026-11-09'
                    )
                    RETURNING id
                    """,
                    (budget_id,),
                )

                expense_id = cur.fetchone()[0]

            conn.commit()

        # Bob escalates to Alice.
        result = process_expense(
            expense_id=expense_id,
            approver_id=2,
            expected_version=version,
        )

        assert result["status"] == "escalated"
        print("1. Bob escalated expense successfully.")

        # Carol attempts to complete Alice's escalation.
        try:
            process_expense(
                expense_id=expense_id,
                approver_id=3,
                expected_version=version,
            )

        except WorkflowError as error:
            print("2. Carol correctly blocked:", error)

        else:
            raise AssertionError(
                "Carol unexpectedly completed the escalation"
            )

        # Check that Carol's attempt changed nothing.
        with psycopg.connect(os.getenv("DATABASE_URL")) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT status FROM expenses WHERE id = %s",
                    (expense_id,),
                )
                status = cur.fetchone()[0]

                cur.execute(
                    """
                    SELECT remaining, version
                    FROM budgets
                    WHERE id = %s
                    """,
                    (budget_id,),
                )
                remaining, current_version = cur.fetchone()

                cur.execute(
                    """
                    SELECT decision, approver_id, target_approver_id
                    FROM decisions
                    WHERE expense_id = %s
                    ORDER BY id
                    """,
                    (expense_id,),
                )
                decisions = cur.fetchall()

        assert status == "escalated"
        assert remaining == 2000
        assert current_version == version
        assert decisions == [("escalated", 2, 1)]

        print("3. Expense remains escalated.")
        print("   Budget unchanged:", remaining)
        print("   Decisions:", decisions)

        # Alice completes the escalation.
        result = process_expense(
            expense_id=expense_id,
            approver_id=1,
            expected_version=version,
        )

        assert result["status"] == "approved"

        with psycopg.connect(os.getenv("DATABASE_URL")) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT remaining, version
                    FROM budgets
                    WHERE id = %s
                    """,
                    (budget_id,),
                )
                final_remaining, final_version = cur.fetchone()

                cur.execute(
                    """
                    SELECT decision, approver_id, target_approver_id
                    FROM decisions
                    WHERE expense_id = %s
                    ORDER BY id
                    """,
                    (expense_id,),
                )
                final_decisions = cur.fetchall()

        assert final_remaining == 500
        assert final_version == version + 1
        assert final_decisions == [
            ("escalated", 2, 1),
            ("approved", 1, None),
        ]

        print("4. Alice successfully approved the expense.")
        print("   Final budget:", final_remaining)
        print("   Final decisions:", final_decisions)

        print("\nSUCCESS: Escalation assignment enforced.")

    finally:
        # Remove only records created by this test.
        if budget_id is not None:
            with psycopg.connect(os.getenv("DATABASE_URL")) as conn:
                with conn.cursor() as cur:
                    if expense_id is not None:
                        cur.execute(
                            "DELETE FROM decisions WHERE expense_id = %s",
                            (expense_id,),
                        )
                        cur.execute(
                            "DELETE FROM expenses WHERE id = %s",
                            (expense_id,),
                        )

                    cur.execute(
                        "DELETE FROM budgets WHERE id = %s",
                        (budget_id,),
                    )

                conn.commit()

            print("Test records removed.")


if __name__ == "__main__":
    main()