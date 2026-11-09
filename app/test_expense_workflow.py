import os

import psycopg
from dotenv import load_dotenv

from app.services.expense_workflow import (
    process_expense,
    WorkflowError,
)

load_dotenv()


def main():
    budget_id = None
    expense_id = None

    try:
        # 1. Create isolated test records.
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
                        'Unified workflow integration test',
                        '2026-11-09'
                    )
                    RETURNING id
                    """,
                    (budget_id,),
                )

                expense_id = cur.fetchone()[0]

            conn.commit()

        print("1. Created test expense:", expense_id)

        # 2. Bob attempts approval.
        # Because Bob has no current delegation,
        # the expense should be escalated.
        result = process_expense(
            expense_id=expense_id,
            approver_id=2,
            expected_version=version,
        )

        print("\n2. Bob processes expense:")
        print(result)

        assert result["status"] == "escalated"

        # 3. Alice handles the escalated expense.
        result = process_expense(
            expense_id=expense_id,
            approver_id=1,
            expected_version=version,
        )

        print("\n3. Alice processes escalated expense:")
        print(result)

        assert result["status"] == "approved"

        # 4. Verify final PostgreSQL state.
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
                    SELECT decision, approver_id, target_approver_id
                    FROM decisions
                    WHERE expense_id = %s
                    ORDER BY id
                    """,
                    (expense_id,),
                )

                decisions = cur.fetchall()

        print("\n4. Final PostgreSQL state:")
        print("Expense status:", status)
        print("Remaining budget:", remaining)
        print("Budget version:", new_version)
        print("Decisions:", decisions)

        assert status == "approved"
        assert remaining == 500
        assert new_version == version + 1

        # assert decisions == [
        #     ("escalated", 2),
        #     ("approved", 1),
        # ]
        assert decisions == [
            ("escalated", 2, 1),
            ("approved", 1, None),
        ]

        # 5. Verify that double approval is blocked.
        print("\n5. Testing repeated approval...")

        try:
            process_expense(
                expense_id=expense_id,
                approver_id=1,
                expected_version=new_version,
            )

        except WorkflowError as error:
            print("Correctly blocked:", error)

        else:
            raise AssertionError(
                "Repeated approval unexpectedly succeeded"
            )

        print("\nSUCCESS: Unified workflow test passed.")

    finally:
        # Remove temporary test records.
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