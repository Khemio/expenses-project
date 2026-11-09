
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.services.approval_service import (
    approve_expense,
    BudgetConflict,
)


def run_approval(expense_id, approver_id):
    try:
        result = approve_expense(
            expense_id=expense_id,
            approver_id=approver_id,
            expected_version=1,
        )
        return f"SUCCESS: {result}"

    except BudgetConflict as error:
        return f"CONFLICT: Expense {expense_id}: {error}"


if __name__ == "__main__":
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(run_approval, 5, 2),
            executor.submit(run_approval, 6, 3),
        ]

        for future in as_completed(futures):
            print(future.result())
