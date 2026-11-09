from app.services.integrated_approval_service import (
    approve_expense_with_authorization,
    UnauthorizedApprover,
)


def main():
    # Expense 5 is pending and belongs to IT.
    # Carol has no authorization for IT.

    print("Testing unauthorized approval attempt...")

    try:
        result = approve_expense_with_authorization(
            expense_id=5,
            approver_id=3,
            expected_version=2,
        )

        raise AssertionError(
            f"Unauthorized approval unexpectedly succeeded: {result}"
        )

    except UnauthorizedApprover as error:
        print("Correctly denied:", error)

    print("\nSUCCESS: Unauthorized approval was blocked.")


if __name__ == "__main__":
    main()