import os
import random
from collections import defaultdict
from datetime import datetime, timezone

import psycopg
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

SEED = 42
EXPECTED_EMPLOYEES = 250
EXPECTED_CENTRES = 8

DELEGATION_LIMITS = [500, 1000, 1500, 2500, 5000]


def load_postgres_data():
    with psycopg.connect(os.getenv("DATABASE_URL")) as conn:
        with conn.cursor() as cur:

            cur.execute("""
                SELECT id, name, cost_centre_id
                FROM employees
                WHERE email LIKE 'synthetic-expense-%@example.test'
                ORDER BY id
            """)

            employees = [
                {
                    "employee_id": row[0],
                    "name": row[1],
                    "cost_centre_id": row[2],
                }
                for row in cur.fetchall()
            ]

            cur.execute("""
                SELECT id, name
                FROM cost_centres
                WHERE name LIKE 'Synthetic - %'
                ORDER BY id
            """)

            centres = [
                {
                    "cost_centre_id": row[0],
                    "name": row[1],
                }
                for row in cur.fetchall()
            ]

    if len(employees) != EXPECTED_EMPLOYEES:
        raise RuntimeError(
            f"Expected 250 employees, found {len(employees)}"
        )

    if len(centres) != EXPECTED_CENTRES:
        raise RuntimeError(
            f"Expected 8 cost centres, found {len(centres)}"
        )

    centre_ids = {c["cost_centre_id"] for c in centres}

    if any(e["cost_centre_id"] not in centre_ids for e in employees):
        raise RuntimeError(
            "Some synthetic employees belong to unexpected cost centres"
        )

    return employees, centres


def generate_relationships(employees, centres):
    rng = random.Random(SEED)

    employees_by_centre = defaultdict(list)

    for employee in employees:
        employees_by_centre[employee["cost_centre_id"]].append(employee)

    responsibilities = []
    delegations = []

    refreshed_at = datetime.now(timezone.utc).isoformat()

    for centre in centres:
        centre_id = centre["cost_centre_id"]
        members = employees_by_centre[centre_id]

        if not members:
            raise RuntimeError(
                f"Cost centre {centre_id} has no employees"
            )

        # Select one responsible employee per cost centre.
        owner = members[0]

        responsibilities.append({
            "employee_id": owner["employee_id"],
            "cost_centre_id": centre_id,
            "source_id": f"synthetic_responsibility_{centre_id}",
            "refreshed_at": refreshed_at,
        })

        # Delegate to the remaining employees.
        for employee in members[1:]:
            employee_id = employee["employee_id"]

            delegations.append({
                "owner_id": owner["employee_id"],
                "delegate_id": employee_id,
                "scope": centre["name"],
                "amount_limit": rng.choice(DELEGATION_LIMITS),
                "valid_from": "2026-01-01",
                "valid_to": "2027-12-31",
                "source_id": f"synthetic_delegation_{employee_id}",
                "refreshed_at": refreshed_at,
            })

    return responsibilities, delegations


def main():
    employees, centres = load_postgres_data()

    responsibilities, delegations = generate_relationships(
        employees,
        centres,
    )

    refreshed_at = datetime.now(timezone.utc).isoformat()

    employee_rows = [
        {
            **employee,
            "source_id": f"postgres_employee:{employee['employee_id']}",
            "refreshed_at": refreshed_at,
        }
        for employee in employees
    ]

    centre_rows = [
        {
            **centre,
            "source_id": f"postgres_cost_centre:{centre['cost_centre_id']}",
            "refreshed_at": refreshed_at,
        }
        for centre in centres
    ]

    driver = GraphDatabase.driver(
        "bolt://localhost:7687",
        auth=("neo4j", os.getenv("NEO4J_PASSWORD")),
    )

    try:
        with driver.session() as session:

            # 1. Create employee nodes.
            session.run("""
                UNWIND $rows AS row

                MERGE (e:Employee {
                    employee_id: row.employee_id
                })

                SET e.name = row.name,
                    e.cost_centre_id = row.cost_centre_id,
                    e.source_id = row.source_id,
                    e.refreshed_at = row.refreshed_at
            """, rows=employee_rows).consume()

            print("Employee nodes synchronized.")

            # 2. Create cost-centre nodes.
            session.run("""
                UNWIND $rows AS row

                MERGE (c:CostCentre {
                    cost_centre_id: row.cost_centre_id
                })

                SET c.name = row.name,
                    c.source_id = row.source_id,
                    c.refreshed_at = row.refreshed_at
            """, rows=centre_rows).consume()

            print("Cost-centre nodes synchronized.")

            # 3. Create responsibility relationships.
            session.run("""
                UNWIND $rows AS row

                MATCH (e:Employee {
                    employee_id: row.employee_id
                })

                MATCH (c:CostCentre {
                    cost_centre_id: row.cost_centre_id
                })

                MERGE (e)-[r:RESPONSIBLE_FOR {
                    source_id: row.source_id
                }]->(c)

                SET r.refreshed_at = row.refreshed_at
            """, rows=responsibilities).consume()

            print("Responsibility relationships synchronized.")

            # 4. Create delegation relationships.
            session.run("""
                UNWIND $rows AS row

                MATCH (owner:Employee {
                    employee_id: row.owner_id
                })

                MATCH (delegate:Employee {
                    employee_id: row.delegate_id
                })

                MERGE (owner)-[r:DELEGATED_TO {
                    source_id: row.source_id
                }]->(delegate)

                SET r.scope = row.scope,
                    r.amount_limit = row.amount_limit,
                    r.valid_from = row.valid_from,
                    r.valid_to = row.valid_to,
                    r.refreshed_at = row.refreshed_at
            """, rows=delegations).consume()

            print("Delegation relationships synchronized.")

            # 5. Verify generated records.
            result = session.run("""
                MATCH (e:Employee)
                WHERE e.source_id STARTS WITH 'postgres_employee:'
                RETURN count(e) AS count
            """).single()

            employee_count = result["count"]

            result = session.run("""
                MATCH (c:CostCentre)
                WHERE c.source_id STARTS WITH 'postgres_cost_centre:'
                RETURN count(c) AS count
            """).single()

            centre_count = result["count"]

            result = session.run("""
                MATCH ()-[r:RESPONSIBLE_FOR]->()
                WHERE r.source_id STARTS WITH 'synthetic_responsibility_'
                RETURN count(r) AS count
            """).single()

            responsibility_count = result["count"]

            result = session.run("""
                MATCH ()-[r:DELEGATED_TO]->()
                WHERE r.source_id STARTS WITH 'synthetic_delegation_'
                RETURN count(r) AS count
            """).single()

            delegation_count = result["count"]

        print("\n--- Neo4j verification ---")
        print("Synthetic employees:", employee_count)
        print("Synthetic cost centres:", centre_count)
        print("Synthetic responsibilities:", responsibility_count)
        print("Synthetic delegations:", delegation_count)

        assert employee_count == 250
        assert centre_count == 8
        assert responsibility_count == 8
        assert delegation_count == 242

        print("\nSUCCESS: Neo4j synthetic data verified.")

    finally:
        driver.close()


if __name__ == "__main__":
    main()