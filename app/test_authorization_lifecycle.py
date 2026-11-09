import os
from datetime import date

from dotenv import load_dotenv
from neo4j import GraphDatabase

from app.services.authorization_service import is_authorized_approver

load_dotenv()

DELEGATION_SOURCE_ID = "authorization_lifecycle_test"


def main():
    driver = GraphDatabase.driver(
        "bolt://localhost:7687",
        auth=("neo4j", os.getenv("NEO4J_PASSWORD")),
    )

    expense_date = date(2026, 11, 9)

    try:
        with driver.session() as session:

            # Make the test repeatable.
            session.run(
                """
                MATCH (a:Employee {employee_id: 1})
                      -[r:DELEGATED_TO]->
                      (b:Employee {employee_id: 2})
                WHERE r.source_id = $source_id
                DELETE r
                """,
                source_id=DELEGATION_SOURCE_ID,
            ).consume()

            # A separate authorization test should not overwrite
            # or delete an unrelated, pre-existing delegation.
            existing = session.run(
                """
                MATCH (:Employee {employee_id: 1})
                      -[r:DELEGATED_TO]->
                      (:Employee {employee_id: 2})
                RETURN count(r) AS count
                """
            ).single()["count"]

            if existing:
                raise RuntimeError(
                    "Alice already has a delegation to Bob. "
                    "Refusing to modify unrelated graph data."
                )

            # Create a temporary delegation.
            session.run(
                """
                MATCH (a:Employee {employee_id: 1})
                MATCH (b:Employee {employee_id: 2})

                CREATE (a)-[:DELEGATED_TO {
                    scope: 'IT',
                    amount_limit: 1000,
                    valid_from: '2026-01-01',
                    valid_to: '2026-12-31',
                    source_id: $source_id
                }]->(b)
                """,
                source_id=DELEGATION_SOURCE_ID,
            ).consume()

        print("1. Temporary delegation created: Alice -> Bob")

        cases = [
            ("Bob approves €700 IT", 2, 1, 700, True),
            ("Bob approves €1,500 IT", 2, 1, 1500, False),
            ("Bob approves €700 Marketing", 2, 2, 700, False),
            ("Alice approves €700 IT", 1, 1, 700, True),
        ]

        for name, approver_id, centre_id, amount, expected in cases:
            actual = is_authorized_approver(
                approver_id=approver_id,
                cost_centre_id=centre_id,
                amount=amount,
                expense_date=expense_date,
            )

            print(f"{name}: {actual}")

            assert actual == expected, f"Failed: {name}"

        print("\n2. All delegation checks passed.")

    finally:
        # Always remove the test delegation, even if an assertion fails.
        try:
            with driver.session() as session:
                session.run(
                    """
                    MATCH (:Employee {employee_id: 1})
                          -[r:DELEGATED_TO]->
                          (:Employee {employee_id: 2})
                    WHERE r.source_id = $source_id
                    DELETE r
                    """,
                    source_id=DELEGATION_SOURCE_ID,
                ).consume()
        finally:
            driver.close()

    print("\n3. Temporary delegation revoked.")

    authorized_after_revocation = is_authorized_approver(
        approver_id=2,
        cost_centre_id=1,
        amount=700,
        expense_date=expense_date,
    )

    print(
        "Bob authorized after revocation:",
        authorized_after_revocation,
    )

    assert authorized_after_revocation is False

    print("\nSUCCESS: Authorization lifecycle test passed.")


if __name__ == "__main__":
    main()