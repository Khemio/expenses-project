
# Testing

The project uses pytest for unit and integration tests.

## Test suites

- Unit tests exercise application logic without requiring databases.
- Integration tests exercise PostgreSQL, MongoDB, Redis, Neo4j, and Qdrant.

Integration tests use a separate Docker Compose environment defined in
`docker-compose.test.yaml`.

Do not run integration tests against development databases.

## Requirements

- Python 3.11
- Docker Desktop with Docker Compose
- Project Python dependencies installed

Run commands from the repository root.

## Starting test databases

```powershell
docker compose -f docker-compose.test.yaml up -d --wait
```

This starts five isolated database services using separate ports and volumes.

| Database | Test port |
|----------|-----------|
| PostgreSQL | 55432 |
| MongoDB | 57017 |
| Redis | 56379 |
| Neo4j Bolt | 57687 |
| Qdrant HTTP | 56333 |

## Running unit tests

```powershell
python -m pytest -v
```

Unit tests run by default. They do not require Docker.

## Running integration tests

```powershell
python scripts/run_integration_tests.py -v
```

The integration-test runner:

1. Configures isolated test database connections.
2. Verifies database connectivity and PostgreSQL identity.
3. Initializes the PostgreSQL schema if necessary.
4. Runs integration tests.
5. Verifies that test records are cleaned up.

A test run fails if pytest fails or cleanup verification detects
remaining records.

## Running specific integration tests

```powershell
python scripts/run_integration_tests.py tests/integration/test_vector_storage.py -v
```

## Stopping test databases

```powershell
docker compose -f docker-compose.test.yaml down
```

This preserves the test volumes.

## Resetting the test environment

**Warning:** The following command deletes all database data stored in
the isolated test environment.

```powershell
docker compose -f docker-compose.test.yaml down -v
docker compose -f docker-compose.test.yaml up -d --wait
```

Only use this command after verifying that `docker-compose.test.yaml`
uses the separate `expenses-tests` Compose project.

## Known limitation

Vector documents are committed to PostgreSQL before being written
to Qdrant.

If Qdrant fails, the two databases may temporarily disagree.

The integration suite includes a test documenting this behavior.
A durable synchronization mechanism is planned for future development.
