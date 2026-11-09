import os
from decimal import Decimal

import psycopg
from dotenv import load_dotenv

from app.services.expense_workflow import process_expense
from app.services.workflow_retry import process_expense_with_retry

load_dotenv()


def main():
    budget_id = None
    expense_ids = []

    try:
        # Create an isolated budget shared by two expenses.
        with psycopg.connect(os.getenv("DATABASE_URL")) as conn:
            with conn.cursor() as cur:

                cur.execute(
                    """
                    INSERT INTO budgets (
                        cost_centre_id,
                        total,
                        remaining
                    )
                    VALUES (1, 1000, 1000)
                    RETURNING id, version
                    """
                )

                budget_id, initial_version = cur.fetchone()

                for number in range(2):
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
                            1, 1, %s, 700, %s, '2026-11-09'
                        )
                        RETURNING id
                        """,
                        (
                            budget_id,
                            f"Workflow retry test {number + 1}",
                        ),
                    )

                    expense_ids.append(cur.fetchone()[0])

            conn.commit()

        first_expense, second_expense = expense_ids

        print("1. Test data created.")
        print("Initial budget: 1000 EUR")
        print("Initial version:", initial_version)
        print("Expense IDs:", expense_ids)

        # First expense consumes 700 EUR.
        first_result = process_expense(
            expense_id=first_expense,
            approver_id=1,
            expected_version=initial_version,
        )

        assert first_result["status"] == "approved"

        print("\n2. First expense approved.")

        # Second request starts with the now-stale version.
        second_result = process_expense_with_retry(
            expense_id=second_expense,
            approver_id=1,
            expected_version=initial_version,
            max_attempts=3,
        )

        print("\n3. Second expense result:")
        print(second_result)

        assert second_result["status"] == "rejected"

        # Verify the final database state.
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

                remaining, final_version = cur.fetchone()

                cur.execute(
                    """
                    SELECT id, status
                    FROM expenses
                    WHERE id = ANY(%s)
                    ORDER BY id
                    """,
                    (expense_ids,),
                )

                expense_states = cur.fetchall()

                cur.execute(
                    """
                    SELECT expense_id, decision, approver_id
                    FROM decisions
                    WHERE expense_id = ANY(%s)
                    ORDER BY id
                    """,
                    (expense_ids,),
                )

                decisions = cur.fetchall()

        print("\n4. Final PostgreSQL state:")
        print("Remaining budget:", remaining)
        print("Budget version:", final_version)
        print("Expenses:", expense_states)
        print("Decisions:", decisions)

        assert remaining == Decimal("300")
        assert final_version == initial_version + 1

        assert dict(expense_states) == {
            first_expense: "approved",
            second_expense: "rejected",
        }

        assert decisions == [
            (first_expense, "approved", 1),
            (second_expense, "rejected", 1),
        ]

        print("\nSUCCESS: Conflict reevaluation worked correctly.")

    finally:
        # Remove only the test records.
        if budget_id is not None:
            with psycopg.connect(os.getenv("DATABASE_URL")) as conn:
                with conn.cursor() as cur:

                    if expense_ids:
                        cur.execute(
                            """
                            DELETE FROM decisions
                            WHERE expense_id = ANY(%s)
                            """,
                            (expense_ids,),
                        )

                        cur.execute(
                            """
                            DELETE FROM expenses
                            WHERE id = ANY(%s)
                            """,
                            (expense_ids,),
                        )

                    cur.execute(
                        """
                        DELETE FROM budgets
                        WHERE id = %s
                        """,
                        (budget_id,),
                    )

                conn.commit()

            print("Test records removed.")


if __name__ == "__main__":
    main()