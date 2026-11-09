import os
from datetime import date
from decimal import Decimal

from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()


def is_authorized_approver(
    approver_id: int,
    cost_centre_id: int,
    amount,
    expense_date: date,
) -> bool:

    driver = GraphDatabase.driver(
        "bolt://localhost:7687",
        auth=("neo4j", os.getenv("NEO4J_PASSWORD")),
    )

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

    try:
        with driver.session() as session:
            result = session.run(
                query,
                approver_id=approver_id,
                cost_centre_id=cost_centre_id,
                amount=float(Decimal(str(amount))),
                expense_date=expense_date.isoformat(),
            )

            record = result.single()

            return bool(record and record["authorized"])

    finally:
        driver.close()