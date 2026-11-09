import os
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Event

import psycopg
from dotenv import load_dotenv

from app.services.exceptions import BudgetConflict
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

        return ("SUCCESS", expense_id, result)

    except BudgetConflict as error:
        return ("CONFLICT", expense_id, str(error))

    except WorkflowError as error:
        return ("BLOCKED", expense_id, str(error))


def main():
    budget_id = None
    expense_ids = []

    try:
        # 1. Create one budget shared by two expenses.
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

                budget_id, version = cur.fetchone()

                for number in range(1, 3):
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
                            f"Shared budget concurrency test {number}",
                        ),
                    )

                    expense_ids.append(cur.fetchone()[0])

            conn.commit()

        print("1. Test data created:")
        print("Budget ID:", budget_id)
        print("Initial budget: 1000 EUR")
        print("Initial version:", version)
        print("Expense IDs:", expense_ids)
        print("Each expense: 700 EUR")

        # 2. Start both approval requests simultaneously.
        start_event = Event()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    attempt_approval,
                    expense_id,
                    version,
                    start_event,
                )
                for expense_id in expense_ids
            ]

            start_event.set()

            results = [future.result() for future in futures]

        print("\n2. Concurrent request results:")

        for result in results:
            print(result)

        successes = [r for r in results if r[0] == "SUCCESS"]
        conflicts = [r for r in results if r[0] == "CONFLICT"]

        assert len(successes) == 1, (
            f"Expected one successful approval, got {len(successes)}"
        )

        assert len(conflicts) == 1, (
            f"Expected one version conflict, got {len(conflicts)}"
        )

        # 3. Verify the final PostgreSQL state.
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

        print("\n3. PostgreSQL verification:")
        print("Remaining budget:", remaining)
        print("Budget version:", new_version)
        print("Expense states:", expense_states)
        print("Decisions:", decisions)

        assert remaining == Decimal("300")
        assert new_version == version + 1

        statuses = [status for _, status in expense_states]

        assert statuses.count("approved") == 1
        assert statuses.count("pending") == 1

        assert len(decisions) == 1
        assert decisions[0][1] == "approved"
        assert decisions[0][2] == 1

        assert decisions[0][0] == successes[0][1]

        print(
            "\nSUCCESS: Shared-budget concurrency "
            "prevented overspending."
        )

    finally:
        # Clean up only records created by this test.
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