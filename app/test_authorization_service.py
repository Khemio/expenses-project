from datetime import date

from app.services.authorization_service import is_authorized_approver


def main():

    expense_date = date(2026, 11, 9)

    test_cases = [
        {
            "name": "Alice approves IT expense",
            "approver_id": 1,
            "cost_centre_id": 1,
            "amount": 700,
        },
        {
            "name": "Bob approves IT expense",
            "approver_id": 2,
            "cost_centre_id": 1,
            "amount": 700,
        },
        {
            "name": "Bob exceeds IT delegation limit",
            "approver_id": 2,
            "cost_centre_id": 1,
            "amount": 1500,
        },
        {
            "name": "Bob attempts Marketing approval",
            "approver_id": 2,
            "cost_centre_id": 2,
            "amount": 700,
        },
        {
            "name": "Carol attempts IT approval",
            "approver_id": 3,
            "cost_centre_id": 1,
            "amount": 700,
        },
    ]

    for case in test_cases:

        authorized = is_authorized_approver(
            approver_id=case["approver_id"],
            cost_centre_id=case["cost_centre_id"],
            amount=case["amount"],
            expense_date=expense_date,
        )

        print(f"{case['name']}: {authorized}")


if __name__ == "__main__":
    main()