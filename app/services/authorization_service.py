# import os
from datetime import date
from decimal import Decimal
from collections.abc import Sequence

from app.database.neo4j import get_driver

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
        AND rel.amount_limit >= $amount
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
            amount=float(Decimal(str(amount))),
            expense_date=expense_date.isoformat(),
        )

        record = result.single()

        return bool(record and record["authorized"])


def get_authorized_expense_ids(
    approver_id: int,
    candidates: Sequence[dict],
    batch_size: int = 200,
) -> set[int]:
    """Return IDs of expenses an employee may approve.

    Applies the same Neo4j delegation rules used by
    is_authorized_approver(), but evaluates candidates
    in batches.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be positive")

    if not candidates:
        return set()

    query = """
    UNWIND $candidates AS item

    MATCH (owner:Employee)-[:RESPONSIBLE_FOR]->(cc:CostCentre)
    WHERE cc.cost_centre_id = item.cost_centre_id

    MATCH path =
        (owner)-[:DELEGATED_TO*0..5]->(approver:Employee)
    WHERE approver.employee_id = $approver_id

    AND ALL(rel IN relationships(path) WHERE
        rel.scope = cc.name
        AND rel.amount_limit >= item.amount
        AND date(rel.valid_from) <= date(item.expense_date)
        AND date(rel.valid_to) >= date(item.expense_date)
    )

    RETURN DISTINCT item.id AS expense_id
    """

    authorized_ids: set[int] = set()

    with get_driver().session() as session:
        for start in range(0, len(candidates), batch_size):
            chunk = candidates[start:start + batch_size]

            parameters = [
                {
                    "id": item["id"],
                    "cost_centre_id": item["cost_centre_id"],
                    "amount": float(
                        Decimal(str(item["amount"]))
                    ),
                    "expense_date": (
                        item["expense_date"].isoformat()
                    ),
                }
                for item in chunk
            ]

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
