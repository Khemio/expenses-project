

from app.database.neo4j import get_driver


class EscalationError(Exception):
    """Raised when escalation configuration is invalid."""


def find_responsible_approver(
    cost_centre_id: int,
) -> int | None:
    """Find the employee responsible for a cost centre.

    Returns None if there is no responsible employee.
    Raises EscalationError if multiple owners are found.
    """

    query = """
    MATCH (employee:Employee)-[:RESPONSIBLE_FOR]->(cc:CostCentre)
    WHERE cc.cost_centre_id = $cost_centre_id
    RETURN employee.employee_id AS employee_id
    ORDER BY employee.employee_id
    """

    with get_driver().session() as session:
        records = list(
            session.run(
                query,
                cost_centre_id=cost_centre_id,
            )
        )

    if not records:
        return None

    if len(records) != 1:
        raise EscalationError(
            "Expected exactly one responsible employee"
        )

    return records[0]["employee_id"]
    