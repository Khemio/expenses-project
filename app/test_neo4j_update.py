
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()


def main():
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    username = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD")

    driver = GraphDatabase.driver(
        uri,
        auth=(username, password),
    )

    source_id = "delegation_employee_1"

    try:
        with driver.session() as session:

            # 1. Create a derived copy of the source delegation.
            session.run(
                """
                MATCH (alice:Employee {employee_id: 1})
                MATCH (bob:Employee {employee_id: 2})
                MERGE (alice)-[d:DERIVED_DELEGATION]->(bob)
                SET d.scope = 'IT',
                    d.amount_limit = 1000.00,
                    d.valid_from = date('2026-01-01'),
                    d.valid_to = date('2026-12-31'),
                    d.source_id = $source_id,
                    d.refreshed_at = $refreshed_at
                """,
                source_id=source_id,
                refreshed_at=datetime.now(timezone.utc).isoformat(),
            )

            # 2. Check the derived graph before revocation.
            result = session.run(
                """
                MATCH (alice:Employee {employee_id: 1})
                      -[d:DERIVED_DELEGATION]->
                      (bob:Employee {employee_id: 2})
                WHERE d.source_id = $source_id
                RETURN count(d) > 0 AS delegation_exists
                """,
                source_id=source_id,
            ).single()

            print("1. Derived delegation initially exists:", result["delegation_exists"])

            # 3. Revoke the source delegation.
            session.run(
                """
                MATCH (alice:Employee {employee_id: 1})
                      -[d:DELEGATED_TO]->
                      (bob:Employee {employee_id: 2})
                WHERE d.source_id = $source_id
                DELETE d
                """,
                source_id=source_id,
            )

            print("\n2. Source delegation revoked.")

            # 4. Check whether the derived copy is stale.
            result = session.run(
                """
                MATCH (alice:Employee {employee_id: 1})
                      -[d:DERIVED_DELEGATION]->
                      (bob:Employee {employee_id: 2})
                WHERE d.source_id = $source_id
                RETURN count(d) > 0 AS delegation_exists,
                       max(d.refreshed_at) AS refreshed_at
                """,
                source_id=source_id,
            ).single()

            print("3. Derived delegation still exists:", result["delegation_exists"])
            print("   Last refresh:", result["refreshed_at"])

            # 5. Refresh the derived graph from the source.
            session.run(
                """
                MATCH (alice:Employee {employee_id: 1})
                      -[d:DERIVED_DELEGATION]->
                      (bob:Employee {employee_id: 2})
                WHERE d.source_id = $source_id
                DELETE d
                """,
                source_id=source_id,
            )

            print("\n4. Derived delegation deleted during refresh.")

            # 6. Verify that the derived delegation is now gone.
            result = session.run(
                """
                MATCH (alice:Employee {employee_id: 1})
                      -[d:DERIVED_DELEGATION]->
                      (bob:Employee {employee_id: 2})
                WHERE d.source_id = $source_id
                RETURN count(d) AS remaining
                """,
                source_id=source_id,
            ).single()

            print("5. Derived delegations remaining:", result["remaining"])

    finally:
        driver.close()


if __name__ == "__main__":
    main()
