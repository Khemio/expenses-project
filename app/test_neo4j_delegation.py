
import os
from datetime import date

from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()


def check_delegation(
    employee_id: int,
    approver_id: int,
    cost_centre: str,
    amount: float,
    expense_date: date,
):
    driver = GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        auth=(
            os.getenv("NEO4J_USER", "neo4j"),
            os.getenv("NEO4J_PASSWORD"),
        ),
    )

    query = """
    MATCH (employee:Employee {employee_id: $employee_id})
    MATCH (approver:Employee {employee_id: $approver_id})

    MATCH path =
        (employee)-[:DELEGATED_TO*1..5]->(approver)

    WHERE ALL(rel IN relationships(path)
        WHERE rel.scope = $cost_centre
          AND rel.amount_limit >= $amount
          AND rel.valid_from <= date($expense_date)
          AND rel.valid_to >= date($expense_date)
    )

    RETURN path
    LIMIT 1
    """

    with driver.session() as session:
        result = session.run(
            query,
            employee_id=employee_id,
            approver_id=approver_id,
            cost_centre=cost_centre,
            amount=amount,
            expense_date=expense_date.isoformat(),
        )

        valid = result.single() is not None

    driver.close()
    return valid


if __name__ == "__main__":
    expense_date = date(2026, 11, 2)

    print(
        "Bob can approve €700 IT expense:",
        check_delegation(
            employee_id=1,
            approver_id=2,
            cost_centre="IT",
            amount=700.00,
            expense_date=expense_date,
        ),
    )

    print(
        "Bob can approve €1500 IT expense:",
        check_delegation(
            employee_id=1,
            approver_id=2,
            cost_centre="IT",
            amount=1500.00,
            expense_date=expense_date,
        ),
    )

    print(
        "Bob can approve €700 Marketing expense:",
        check_delegation(
            employee_id=1,
            approver_id=2,
            cost_centre="Marketing",
            amount=700.00,
            expense_date=expense_date,
        ),
    )
