
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()


def setup_neo4j():
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    username = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD")

    if not password:
        raise ValueError("NEO4J_PASSWORD is missing from .env")

    driver = GraphDatabase.driver(
        uri,
        auth=(username, password),
    )

    refreshed_at = datetime.now(timezone.utc).isoformat()

    with driver.session() as session:

        # Create employees
        session.run(
            """
            MERGE (alice:Employee {employee_id: 1})
            SET alice.name = 'Alice Johnson'

            MERGE (bob:Employee {employee_id: 2})
            SET bob.name = 'Bob Smith'

            MERGE (carol:Employee {employee_id: 3})
            SET carol.name = 'Carol Davis'
            """
        )

        # Create cost centre
        session.run(
            """
            MERGE (it:CostCentre {cost_centre_id: 1})
            SET it.name = 'IT'
            """
        )

        # Assign responsibility
        session.run(
            """
            MATCH (alice:Employee {employee_id: 1})
            MATCH (it:CostCentre {cost_centre_id: 1})
            MERGE (alice)-[:RESPONSIBLE_FOR]->(it)
            """
        )

        # Original source delegation
        session.run(
            """
            MATCH (alice:Employee {employee_id: 1})
            MATCH (bob:Employee {employee_id: 2})
            MERGE (alice)-[d:DELEGATED_TO]->(bob)
            SET d.scope = 'IT',
                d.amount_limit = 1000.00,
                d.valid_from = date('2026-01-01'),
                d.valid_to = date('2026-12-31'),
                d.source_id = 'delegation_employee_1',
                d.refreshed_at = $refreshed_at
            """,
            refreshed_at=refreshed_at,
        )

    driver.close()

    print("Neo4j graph created successfully.")


if __name__ == "__main__":
    setup_neo4j()
