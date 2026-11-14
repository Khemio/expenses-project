
import os
import subprocess
import sys
from pathlib import Path

import psycopg


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
        "MONGO_URI": "mongodb://127.0.0.1:27017",
        "REDIS_PASSWORD": "unused_for_these_tests",
        "QDRANT_URL": "http://127.0.0.1:6333",
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
        "tests/integration",
        *sys.argv[1:],
    ]

    return subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
