# Expense Approval System

A Python/FastAPI backend prototype for expense submission and review, built to explore **polyglot persistence**, transaction safety, and graph-based authorization. The project uses five database technologies for distinct responsibilities and includes isolated integration tests.

> **Status:** Backend portfolio / coursework prototype. No frontend or public login flow yet; not intended for production deployment.

## Architecture

| Technology | Responsibility |
| --- | --- |
| **PostgreSQL** (+ pgvector) | Employees, cost centres, budgets, expenses, decisions, transactional workflow and vector storage |
| **MongoDB** | Validated receipt documents |
| **Redis** | Cached approver chains with TTL and invalidation |
| **Neo4j** | Cost-centre responsibility, scoped delegation and independent-review relationships |
| **Qdrant** | Vector similarity search over example receipts and policies |

The FastAPI application sits in front of the relational workflow and graph authorization services. Approval uses PostgreSQL row locks, a budget-version check, an atomic budget deduction, and a decision record. Graph authority is checked at decision time, including after escalation.

**Authorization rules:** An employee cannot approve or reject their own expense. Ordinary authority is based on `RESPONSIBLE_FOR` and bounded `DELEGATED_TO` paths. The distinct `REVIEWER_FOR` path applies to a cost-centre owner's own expenses. Escalations assign a specific eligible reviewer; revocation is rechecked before completion. The approver queue performs authorization before pagination.

See [architecture and workflow notes](docs/ARCHITECTURE.md) and the [database diagram](schema.md).

## What the API currently exposes

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/api/v1/health` | Process health response (not a dependency check) |
| GET | `/api/v1/auth/me` | Current authenticated employee |
| GET | `/api/v1/expenses` | List an employee's expenses, with pagination/filtering |
| GET | `/api/v1/expenses/{id}` | Read an accessible expense |
| POST | `/api/v1/expenses` | Submit an expense |
| POST | `/api/v1/expenses/{id}/approve` | Approve against the current budget version |
| POST | `/api/v1/expenses/{id}/reject` | Reject with a reason |
| POST | `/api/v1/expenses/{id}/escalate` | Submitter-initiated escalation |
| GET | `/api/v1/approvals` | Paginated queue of currently actionable expenses |

Interactive OpenAPI documentation is available at `http://127.0.0.1:8000/docs` when the API is running.

**Authentication limitation:** Protected endpoints expect a bearer session token. The project contains internal session creation and revocation code, but **no publicly exposed login endpoint**. The README deliberately does not claim a complete interactive sign-in workflow.

## Local setup (development)

Requirements: Python 3.11 (the tested development version), Docker with Compose, and sufficient resources for five databases. The embedding experiments may download a Sentence Transformers model on first use.

From the repository root (PowerShell shown):

```powershell
Copy-Item .env.example .env
# Edit .env and replace every 'replace_me' with your local passwords.
docker compose up -d

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Initialize relational tables, the API-session migration, and receipt validation:

```powershell
python -m app.database.init_db
@'
import os
from pathlib import Path
import psycopg
from dotenv import load_dotenv
load_dotenv()
with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
    conn.execute(Path("app/database/migrations/001_api_sessions.sql").read_text(encoding="utf-8"))
'@ | python -
python -m app.database.mongo_setup
```

The database schema and session migration should be applied to a **fresh development database**, not blindly replayed over data you need to preserve. Graph data (employees/cost centres/relationships) must be populated consistently with PostgreSQL for approval operations; there is no automatic complete bootstrap of a demo organization.

Start the API:

```powershell
python -m uvicorn app.api.main:app --reload
```

Check `http://127.0.0.1:8000/api/v1/health` for `{"status":"ok"}`. This checks the running process, **not** whether every database is healthy. Other endpoints require a valid session bearer token.

## Tests

Unit tests:

```powershell
python -m pytest -v
```

Integration tests use **dedicated Docker test services**, separate credentials and an explicit safety preflight. Never invoke the integration tests directly with plain pytest:

```powershell
docker compose -f docker-compose.test.yaml up -d
python scripts/run_integration_tests.py -v
```

The test runner checks the database identities before running, applies the test schema, and verifies cleanup afterward. Last user-verified result (November 18, 2026): **55 unit tests** and **110 integration tests** passed. Test counts may change as development continues.

## Project layout

- `app/api/` — FastAPI routes, request/response schemas and authentication dependency
- `app/services/` — expense workflow, authorization, approval queries and cache/session helpers
- `app/database/` — database clients, schema, setup utilities and seed/benchmark scripts
- `tests/unit/` and `tests/integration/` — behavior, security and data-store tests
- `scripts/run_integration_tests.py` — isolated integration test runner with cleanup verification
- `data/` — example datasets used for database/vector experiments

## Current limitations

- No Vue/frontend client and no public authentication/login endpoint.
- Independent-review relationships must be configured through a trusted administrative process; there is no reviewer-management API.
- No full production deployment, secret-management or active-employee lifecycle enforcement.
- Database seed scripts and experimental data-store workflows are not a single unified, repeatable application bootstrap.
- Vector search and receipt storage are demonstrated as database integrations; they are not presented as a complete receipt-upload or policy-search HTTP product.

## Background

This project began as a multi-database data-management exercise and evolved into a tested expense-approval backend. The [technical report](expense_approval_technical_report.pdf) documents the earlier database-focused work; the current API and authorization code evolved further, so treat that report as background rather than a complete description of the latest backend.
