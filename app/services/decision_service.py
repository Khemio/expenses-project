
from decimal import Decimal


def evaluate_expense(
    amount,
    budget_remaining,
    budget_version_matches,
    valid_approver,
    requires_escalation,
):
    """
    Evaluate an expense without modifying any database.

    Returns one of:
        approved
        rejected
        escalated
    """

    amount = Decimal(str(amount))
    budget_remaining = Decimal(str(budget_remaining))

    if amount <= 0:
        return "rejected"

    if amount > budget_remaining:
        return "rejected"

    if not budget_version_matches:
        return "rejected"

    if requires_escalation:
        return "escalated"

    if not valid_approver:
        return "rejected"

    return "approved"
