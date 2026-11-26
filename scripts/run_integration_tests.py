
import os
import subprocess
import sys

import psycopg
import redis

from pathlib import Path
from neo4j import GraphDatabase
from pymongo import MongoClient
from qdrant_client import QdrantClient



ROOT = Path(__file__).resolve().parents[1]

TEST_DATABASE_URL = (
    "postgresql://expense_test:local_test_password"
    "@127.0.0.1:55432/expense_approval_test"
)



def verify_test_environment() -> None:
    """Verify isolated database connections before any writes."""

    print("\n--- Preflight database verification ---")

    # PostgreSQL: verify the actual connected database and role.
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT current_database(), current_user"
            )
            database_name, username = cur.fetchone()

    if (
        database_name != "expense_approval_test"
        or username != "expense_test"
    ):
        raise RuntimeError(
            "PostgreSQL is not the expected test database"
        )

    print("PostgreSQL identity verified.")

    # Neo4j: verify test credentials and connectivity.
    driver = GraphDatabase.driver(
        "bolt://127.0.0.1:57687",
        auth=("neo4j", "local_test_password"),
    )

    try:
        driver.verify_connectivity()
    finally:
        driver.close()

    print("Neo4j test connection verified.")

    # MongoDB: verify authentication and connectivity.
    mongo = MongoClient(
        "mongodb://expense_test:local_test_password"
        "@127.0.0.1:57017/?authSource=admin",
        serverSelectionTimeoutMS=5000,
    )

    try:
        mongo.admin.command("ping")

        status = mongo.admin.command("connectionStatus")
        users = status.get("authInfo", {}).get(
            "authenticatedUsers", []
        )

        if not any(
            user.get("user") == "expense_test"
            and user.get("db") == "admin"
            for user in users
        ):
            raise RuntimeError(
                "Unexpected MongoDB authenticated user"
            )
    finally:
        mongo.close()

    print("MongoDB authentication verified.")

    # Redis: verify the isolated instance is reachable.
    cache = redis.Redis(
        host="127.0.0.1",
        port=56379,
        password="local_test_password",
        socket_connect_timeout=5,
        socket_timeout=5,
    )

    try:
        if not cache.ping():
            raise RuntimeError("Redis test connection failed")
    finally:
        cache.close()

    print("Redis test connection verified.")

    # Qdrant: verify connectivity without changing collections.
    qdrant = QdrantClient(
        url="http://127.0.0.1:56333",
        timeout=10,
    )

    try:
        qdrant.get_collections()
    finally:
        qdrant.close()

    print("Qdrant test connection verified.")
    print("SUCCESS: Test environment preflight passed.\n")


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

            cur.execute("SELECT COUNT(*) FROM vector_documents")
            postgres_vectors_remaining = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM api_sessions")
            postgres_sessions_remaining = cur.fetchone()[0]

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

    
    qdrant_client = QdrantClient(
        url="http://127.0.0.1:56333",
        timeout=10,
    )

    try:
        collection_name = "expense_documents"

        if qdrant_client.collection_exists(collection_name):
            qdrant_remaining = qdrant_client.count(
                collection_name=collection_name,
                exact=True,
            ).count
        else:
            qdrant_remaining = 0

    finally:
        qdrant_client.close()



    print("\n--- Integration test cleanup verification ---")
    print("PostgreSQL test cost centres:", postgres_remaining)
    print("Neo4j tagged test nodes:", neo4j_remaining)
    print("MongoDB receipt documents:", mongodb_remaining)
    print("Redis keys:", redis_remaining)
    print("Qdrant vector points:", qdrant_remaining)
    print("Postgres vector points:", postgres_vectors_remaining)
    print("PostgreSQL API sessions:", postgres_sessions_remaining)

    if any((
        postgres_remaining != 0,
        neo4j_remaining != 0,
        mongodb_remaining != 0,
        redis_remaining != 0,
        qdrant_remaining != 0,
        postgres_vectors_remaining != 0,
        postgres_sessions_remaining != 0,
    )):
        print("FAILED: Integration tests left records behind.")
        return False

    print("SUCCESS: No test scenario records remain.")
    return True



def initialize_auth_schema():
    """Apply the idempotent authentication schema."""
    migration_path = (
        ROOT
        / "app"
        / "database"
        / "migrations"
        / "001_api_sessions.sql"
    )

    with psycopg.connect(TEST_DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                migration_path.read_text(encoding="utf-8")
            )

    print("Authentication schema ready.")



def initialize_decision_evidence_schema():
    """Apply additive evidence columns to existing isolated test databases."""
    migration_path = (
        ROOT
        / "app"
        / "database"
        / "migrations"
        / "002_decision_evidence.sql"
    )

    with psycopg.connect(TEST_DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                migration_path.read_text(encoding="utf-8")
            )

    print("Decision evidence schema ready.")


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

        "QDRANT_URL": "http://127.0.0.1:56333",
    })

    # Initialize under the same explicit test configuration.
    # The URL is fixed and does not use the development .env.
    try:
        verify_test_environment()
        initialize_database()
        initialize_auth_schema()
        initialize_decision_evidence_schema()
    except Exception as error:
        print(f"FAILED: Test environment preparation: {error}")
        return 1

    command = [
        sys.executable,
        "-m",
        "pytest",
        "-o",
        "addopts=",
        "-m",
        "integration",
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
