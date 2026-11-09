import os
from collections import defaultdict

import psycopg
import redis
from dotenv import load_dotenv
from neo4j import GraphDatabase

from app.services.approver_cache import (
    cache_approver_chain,
)

load_dotenv()

EXPECTED_EMPLOYEES = 250


def load_employees():
    with psycopg.connect(os.getenv("DATABASE_URL")) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, cost_centre_id
                FROM employees
                WHERE email LIKE 'synthetic-expense-%@example.test'
                ORDER BY id
            """)

            employees = cur.fetchall()

    if len(employees) != EXPECTED_EMPLOYEES:
        raise RuntimeError(
            f"Expected 250 synthetic employees, "
            f"found {len(employees)}"
        )

    return employees


def load_approver_candidates():
    """
    Retrieve approval candidates from Neo4j.

    These are candidate approvers, not final
    authorization decisions.
    """

    driver = GraphDatabase.driver(
        "bolt://localhost:7687",
        auth=("neo4j", os.getenv("NEO4J_PASSWORD")),
    )

    try:
        with driver.session() as session:

            # Find directly responsible employees.
            owners = list(session.run("""
                MATCH (owner:Employee)-[:RESPONSIBLE_FOR]->
                      (cc:CostCentre)

                WHERE cc.name STARTS WITH 'Synthetic - '

                RETURN
                    cc.cost_centre_id AS centre_id,
                    cc.name AS centre_name,
                    owner.employee_id AS owner_id
            """))

            # Find delegated employees.
            delegations = list(session.run("""
                MATCH (owner:Employee)-[r:DELEGATED_TO]->
                      (delegate:Employee)

                MATCH (owner)-[:RESPONSIBLE_FOR]->
                      (cc:CostCentre)

                WHERE cc.name STARTS WITH 'Synthetic - '
                  AND r.scope = cc.name

                RETURN
                    cc.cost_centre_id AS centre_id,
                    delegate.employee_id AS delegate_id
            """))

    finally:
        driver.close()

    candidates = defaultdict(set)

    owner_by_centre = {}

    for record in owners:
        centre_id = record["centre_id"]
        owner_id = record["owner_id"]

        if centre_id in owner_by_centre:
            raise RuntimeError(
                f"Multiple responsible employees for "
                f"cost centre {centre_id}"
            )

        owner_by_centre[centre_id] = owner_id
        candidates[centre_id].add(owner_id)

    for record in delegations:
        centre_id = record["centre_id"]

        candidates[centre_id].add(
            record["delegate_id"]
        )

    if len(owner_by_centre) != 8:
        raise RuntimeError(
            "Expected eight synthetic cost-centre owners"
        )

    chains = {}

    for centre_id, approvers in candidates.items():
        owner_id = owner_by_centre[centre_id]

        # Put the responsible employee first.
        chains[centre_id] = [
            owner_id,
            *sorted(approvers - {owner_id}),
        ]

    return chains


def main():
    employees = load_employees()
    chains = load_approver_candidates()

    # Use the existing cache service so all entries
    # contain source_id, refreshed_at and a 300s TTL.
    for employee_id, centre_id in employees:

        if centre_id not in chains:
            raise RuntimeError(
                f"No approver chain for centre {centre_id}"
            )

        cache_approver_chain(
            employee_id=employee_id,
            approver_chain=chains[centre_id],
            source_id=f"neo4j:cost_centre:{centre_id}",
        )

    # Verify the entries immediately because Redis
    # keys are configured to expire after 300 seconds.
    client = redis.Redis(
        host="localhost",
        port=6379,
        password=os.getenv("REDIS_PASSWORD"),
        decode_responses=True,
    )

    try:
        verified = 0

        for employee_id, centre_id in employees:
            key = f"approver_chain:{employee_id}"

            cached = client.get(key)

            if cached is None:
                raise RuntimeError(
                    f"Missing Redis entry: {key}"
                )

            ttl = client.ttl(key)

            if not 0 < ttl <= 300:
                raise RuntimeError(
                    f"Invalid TTL for {key}: {ttl}"
                )

            verified += 1

        print("--- Redis verification ---")
        print("Synthetic employee cache entries:", verified)
        print("Cost-centre chains:", len(chains))
        print("TTL: 300 seconds")

        assert verified == EXPECTED_EMPLOYEES

        # Display one sample.
        employee_id, centre_id = employees[0]
        sample_key = f"approver_chain:{employee_id}"

        print("\nSample cache key:", sample_key)
        print("Sample source centre:", centre_id)
        print("Sample value:", client.get(sample_key))
        print("Sample TTL:", client.ttl(sample_key))

        print("\nSUCCESS: Redis cache data verified.")

    finally:
        client.close()


if __name__ == "__main__":
    main()