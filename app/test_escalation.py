import os

import psycopg
from dotenv import load_dotenv

from app.services.escalation_service import escalate_expense

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
                    INSERT INTO budgets (
                        cost_centre_id,
                        total,
                        remaining
                    )
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
                        'Escalation integration test',
                        '2026-11-09'
                    )
                    RETURNING id
                    """,
                    (budget_id,),
                )

                expense_id = cur.fetchone()[0]

            conn.commit()

        print("1. Test expense created:", expense_id)
        print("   Amount: 1500 EUR")
        print("   Budget: 2000 EUR")
        print("   Requested approver: Bob")

        # Bob cannot approve this expense.
        result = escalate_expense(
            expense_id=expense_id,
            current_approver_id=2,
            expected_version=version,
        )

        print("\n2. Escalation result:")
        print(result)

        # Verify the database state.
        with psycopg.connect(os.getenv("DATABASE_URL")) as conn:
            with conn.cursor() as cur:

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
                    SELECT remaining, version
                    FROM budgets
                    WHERE id = %s
                    """,
                    (budget_id,),
                )

                remaining, new_version = cur.fetchone()

                cur.execute(
                    """
                    SELECT decision, approver_id, comment
                    FROM decisions
                    WHERE expense_id = %s
                    """,
                    (expense_id,),
                )

                decision = cur.fetchone()

        print("\n3. PostgreSQL verification:")
        print("Expense status:", status)
        print("Budget remaining:", remaining)
        print("Budget version:", new_version)
        print("Decision:", decision)

        assert status == "escalated"
        assert remaining == 2000
        assert new_version == version

        assert decision is not None
        assert decision[0] == "escalated"
        assert decision[1] == 2

        assert result["to_approver"] == 1

        print("\nSUCCESS: Escalation completed correctly.")

    finally:
        # Remove only records belonging to this test.
        if budget_id is not None:
            with psycopg.connect(os.getenv("DATABASE_URL")) as conn:
                with conn.cursor() as cur:

                    if expense_id is not None:
                        cur.execute(
                            """
                            DELETE FROM decisions
                            WHERE expense_id = %s
                            """,
                            (expense_id,),
                        )

                        cur.execute(
                            """
                            DELETE FROM expenses
                            WHERE id = %s
                            """,
                            (expense_id,),
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