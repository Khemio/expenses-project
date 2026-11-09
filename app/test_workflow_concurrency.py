import os
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Event

import psycopg
from dotenv import load_dotenv

from app.services.expense_workflow import (
    WorkflowError,
    process_expense,
)

load_dotenv()


def attempt_approval(expense_id, version, start_event):
    start_event.wait()

    try:
        result = process_expense(
            expense_id=expense_id,
            approver_id=1,
            expected_version=version,
        )

        return ("SUCCESS", result)

    except WorkflowError as error:
        return ("BLOCKED", str(error))


def main():
    budget_id = None
    expense_id = None

    try:
        # Create an isolated budget and expense.
        with psycopg.connect(os.getenv("DATABASE_URL")) as conn:
            with conn.cursor() as cur:

                cur.execute(
                    """
                    INSERT INTO budgets (
                        cost_centre_id, total, remaining
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
                        1, 1, %s, 700,
                        'Concurrent workflow test',
                        '2026-11-09'
                    )
                    RETURNING id
                    """,
                    (budget_id,),
                )

                expense_id = cur.fetchone()[0]

            conn.commit()

        print("1. Created expense:", expense_id)
        print("   Initial budget: 2000 EUR")
        print("   Expense amount: 700 EUR")

        # Start two simultaneous approval requests.
        start_event = Event()

        with ThreadPoolExecutor(max_workers=2) as executor:

            futures = [
                executor.submit(
                    attempt_approval,
                    expense_id,
                    version,
                    start_event,
                )
                for _ in range(2)
            ]

            start_event.set()

            results = [
                future.result()
                for future in futures
            ]

        print("\n2. Concurrent request results:")

        for index, result in enumerate(results, start=1):
            print(f"Request {index}: {result}")

        successes = sum(
            result[0] == "SUCCESS"
            for result in results
        )

        blocked = sum(
            result[0] == "BLOCKED"
            for result in results
        )

        assert successes == 1
        assert blocked == 1

        # Verify final database state.
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
                    SELECT COUNT(*)
                    FROM decisions
                    WHERE expense_id = %s
                      AND decision = 'approved'
                    """,
                    (expense_id,),
                )

                approval_count = cur.fetchone()[0]

        print("\n3. PostgreSQL verification:")
        print("Remaining budget:", remaining)
        print("Budget version:", new_version)
        print("Expense status:", status)
        print("Approval decisions:", approval_count)

        assert remaining == Decimal("1300")
        assert new_version == version + 1
        assert status == "approved"
        assert approval_count == 1

        print(
            "\nSUCCESS: Concurrent approval "
            "did not cause duplicate spending."
        )

    finally:
        # Clean up only this test's records.
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