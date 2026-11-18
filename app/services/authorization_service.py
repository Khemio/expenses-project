# import os
from datetime import date
from decimal import Decimal
from collections.abc import Sequence

from app.database.neo4j import get_driver
from app.services.money import to_cents
from app.services.reviewer_service import (
    find_independent_reviewer,
)

def is_authorized_approver(
    approver_id: int,
    cost_centre_id: int,
    amount,
    expense_date: date,
) -> bool:

    query = """
    MATCH (owner:Employee)-[:RESPONSIBLE_FOR]->(cc:CostCentre)
    WHERE cc.cost_centre_id = $cost_centre_id

    MATCH path = (owner)-[:DELEGATED_TO*0..5]->(approver:Employee)
    WHERE approver.employee_id = $approver_id

    AND ALL(rel IN relationships(path) WHERE
        rel.scope = cc.name
        AND rel.amount_limit_cents >= $amount_cents
        AND date(rel.valid_from) <= date($expense_date)
        AND date(rel.valid_to) >= date($expense_date)
    )

    RETURN count(path) > 0 AS authorized
    """

    with get_driver().session() as session:
        result = session.run(
            query,
            approver_id=approver_id,
            cost_centre_id=cost_centre_id,
            amount_cents=to_cents(amount),
            expense_date=expense_date.isoformat(),
        )

        record = result.single()

        return bool(record and record["authorized"])


def get_authorized_expense_ids(
    approver_id: int,
    candidates: Sequence[dict],
    batch_size: int = 200,
) -> set[int]:
    """Resolve ordinary and independent-reviewer authority in batches."""
    if batch_size < 1:
        raise ValueError("batch_size must be positive")

    if not candidates:
        return set()

    ordinary_query = """
    UNWIND $candidates AS item

    MATCH (owner:Employee)-[:RESPONSIBLE_FOR]->(cc:CostCentre)
    WHERE cc.cost_centre_id = item.cost_centre_id

    MATCH path =
        (owner)-[:DELEGATED_TO*0..5]->(approver:Employee)
    WHERE approver.employee_id = $approver_id
      AND item.submitter_id <> $approver_id

    AND ALL(rel IN relationships(path) WHERE
        rel.scope = cc.name
        AND rel.amount_limit_cents >= item.amount_cents
        AND date(rel.valid_from) <= date(item.expense_date)
        AND date(rel.valid_to) >= date(item.expense_date)
    )

    RETURN DISTINCT item.id AS expense_id
    """

    reviewer_query = """
    UNWIND $candidates AS item

    MATCH (owner:Employee)-[:RESPONSIBLE_FOR]->
          (cc:CostCentre)
    WHERE cc.cost_centre_id = item.cost_centre_id

    WITH item, cc,
         collect(DISTINCT owner.employee_id) AS owners

    WHERE size(owners) = 1
      AND owners[0] = item.submitter_id
      AND item.submitter_id <> $approver_id

    MATCH (reviewer:Employee)-[:REVIEWER_FOR]->(cc)

    WITH item,
         collect(DISTINCT reviewer.employee_id) AS reviewers

    WHERE size(reviewers) = 1
      AND reviewers[0] = $approver_id

    RETURN DISTINCT item.id AS expense_id
    """

    authorized_ids: set[int] = set()

    with get_driver().session() as session:
        for start in range(0, len(candidates), batch_size):
            chunk = candidates[start:start + batch_size]

            parameters = [
                {
                    "id": item["id"],
                    "submitter_id": item["employee_id"],
                    "cost_centre_id": item["cost_centre_id"],
                    "amount_cents": to_cents(item["amount"]),
                    "expense_date": item["expense_date"].isoformat(),
                }
                for item in chunk
            ]

            for query in (ordinary_query, reviewer_query):
                result = session.run(
                    query,
                    approver_id=approver_id,
                    candidates=parameters,
                )

                authorized_ids.update(
                    record["expense_id"]
                    for record in result
                )

    return authorized_ids




def is_authorized_for_expense(
    *,
    approver_id: int,
    submitter_id: int,
    cost_centre_id: int,
    amount,
    expense_date: date,
) -> bool:
    """Check ordinary and independent-reviewer authority."""

    # Separation of duties applies to both paths.
    if approver_id == submitter_id:
        return False

    # Ordinary responsibility/delegation remains valid.
    if is_authorized_approver(
        approver_id=approver_id,
        cost_centre_id=cost_centre_id,
        amount=amount,
        expense_date=expense_date,
    ):
        return True

    # Special authority for expenses submitted by
    # the responsible cost-centre owner.
    reviewer_id = find_independent_reviewer(
        cost_centre_id=cost_centre_id,
        submitter_id=submitter_id,
    )

    return reviewer_id == approver_id
