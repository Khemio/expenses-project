
import os
import subprocess
import sys

import psycopg
import redis

from pathlib import Path
from neo4j import GraphDatabase
from pymongo import MongoClient



ROOT = Path(__file__).resolve().parents[1]

TEST_DATABASE_URL = (
    "postgresql://expense_test:local_test_password"
    "@127.0.0.1:55432/expense_approval_test"
)


def initialize_database():
    """Initialize the isolated PostgreSQL schema if needed."""

    schema_path = ROOT / "app" / "database" / "schema.sql"

    with psycopg.connect(TEST_DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT to_regclass('public.expenses')"
            )

            if cur.fetchone()[0] is not None:
                return

            schema = schema_path.read_text(encoding="utf-8")
            cur.execute(schema)

        

def verify_test_cleanup() -> bool:
    """Check that integration tests left no scenario records."""

    # Verify PostgreSQL cleanup.
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM cost_centres
                WHERE name LIKE %s
                """,
                ("pytest-%",),
            )
            postgres_remaining = cur.fetchone()[0]

    # Verify Neo4j cleanup.
    driver = GraphDatabase.driver(
        "bolt://127.0.0.1:57687",
        auth=("neo4j", "local_test_password"),
    )

    try:
        with driver.session() as session:
            record = session.run(
                """
                MATCH (n)
                WHERE n.test_run_id IS NOT NULL
                RETURN count(n) AS remaining
                """
            ).single()

            neo4j_remaining = record["remaining"]

    finally:
        driver.close()

    
    # Verify MongoDB cleanup.
    mongo_client = MongoClient(
        "mongodb://expense_test:local_test_password"
        "@127.0.0.1:57017/?authSource=admin",
        serverSelectionTimeoutMS=5000,
    )

    try:
        mongodb_remaining = mongo_client[
            "expense_approval"
        ]["receipts"].count_documents({})
    finally:
        mongo_client.close()

    # Verify Redis cleanup.
    redis_client = redis.Redis(
        host="127.0.0.1",
        port=56379,
        password="local_test_password",
        decode_responses=True,
    )

    try:
        redis_remaining = redis_client.dbsize()
    finally:
        redis_client.close()


    print("\n--- Integration test cleanup verification ---")
    print("PostgreSQL test cost centres:", postgres_remaining)
    print("Neo4j tagged test nodes:", neo4j_remaining)
    print("MongoDB receipt documents:", mongodb_remaining)
    print("Redis keys:", redis_remaining)

    if any((
        postgres_remaining != 0,
        neo4j_remaining != 0,
        mongodb_remaining != 0,
        redis_remaining != 0,
    )):
        print("FAILED: Integration tests left records behind.")
        return False

    print("SUCCESS: No test scenario records remain.")
    return True



def main():
    env = os.environ.copy()

    env.update({
        "EXPENSE_TEST_MODE": "1",
        "DATABASE_URL": TEST_DATABASE_URL,
        "NEO4J_URI": "bolt://127.0.0.1:57687",
        "NEO4J_USER": "neo4j",
        "NEO4J_PASSWORD": "local_test_password",

        # Required by the current centralized Settings class.
        # These services are not used by this test suite yet.
        
        "MONGO_URI": (
            "mongodb://expense_test:local_test_password"
            "@127.0.0.1:57017/?authSource=admin"
        ),
        "REDIS_HOST": "127.0.0.1",
        "REDIS_PORT": "56379",
        "REDIS_PASSWORD": "local_test_password",

        # "QDRANT_URL": "http://127.0.0.1:6333",
        "QDRANT_URL": "http://127.0.0.1:56333",
    })

    # Initialize under the same explicit test configuration.
    # The URL is fixed and does not use the development .env.
    initialize_database()

    command = [
        sys.executable,
        "-m",
        "pytest",
        "-o",
        "addopts=",
        *(sys.argv[1:] or ["tests/integration"]),
    ]

    
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        check=False,
    )

    cleanup_ok = False

    try:
        cleanup_ok = verify_test_cleanup()
    except Exception as error:
        print(f"Cleanup verification failed: {error}")

    if result.returncode != 0:
        print("FAILED: Integration tests did not pass.")
        return result.returncode

    if not cleanup_ok:
        print("FAILED: Integration test cleanup verification.")
        return 1

    print("SUCCESS: Tests and cleanup verification passed.")
    return 0



if __name__ == "__main__":
    raise SystemExit(main())
