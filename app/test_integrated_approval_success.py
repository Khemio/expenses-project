import os

import psycopg
from dotenv import load_dotenv

from app.services.integrated_approval_service import (
    approve_expense_with_authorization,
)

load_dotenv()


class RollbackTest(Exception):
    pass


def main():
    # This test uses its own budget and expense.
    # The authorization graph already establishes that
    # Alice is responsible for IT.

    with psycopg.connect(os.getenv("DATABASE_URL")) as conn:
        with conn.cursor() as cur:

            # Create an isolated budget.
            cur.execute(
                """
                INSERT INTO budgets
                    (cost_centre_id, total, remaining)
                VALUES (1, 2000, 2000)
                RETURNING id, version
                """
            )

            budget_id, version = cur.fetchone()

            # Create an isolated expense.
            cur.execute(
                """
                INSERT INTO expenses
                    (employee_id, cost_centre_id,
                     budget_id, amount, description, expense_date)
                VALUES
                    (1, 1, %s, 700,
                     'Integration test equipment',
                     '2026-11-09')
                RETURNING id
                """,
                (budget_id,),
            )

            expense_id = cur.fetchone()[0]

        conn.commit()

    try:
        result = approve_expense_with_authorization(
            expense_id=expense_id,
            approver_id=1,
            expected_version=version,
        )

        print("Approval result:", result)

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

                remaining, new_version = cur.fetchone()

                cur.execute(
                    """
                    SELECT status
                    FROM expenses
                    WHERE id = %s
                    """,
                    (expense_id,),
                )

                status = cur.fetchone()[0]

                cur.execute(
                    """
                    SELECT decision, approver_id
                    FROM decisions
                    WHERE expense_id = %s
                    """,
                    (expense_id,),
                )

                decision = cur.fetchone()

        print("Remaining budget:", remaining)
        print("New budget version:", new_version)
        print("Expense status:", status)
        print("Decision:", decision)

        assert remaining == 1300
        assert new_version == version + 1
        assert status == "approved"
        assert decision == ("approved", 1)

        print("\nSUCCESS: Authorized approval completed correctly.")

    finally:
        # Remove only records created by this test.
        with psycopg.connect(os.getenv("DATABASE_URL")) as conn:
            with conn.cursor() as cur:
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