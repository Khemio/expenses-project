# Data model

This page describes the PostgreSQL schema in [`app/database/schema.sql`](../app/database/schema.sql) and the [API sessions migration](../app/database/migrations/001_api_sessions.sql). It replaces the original simplified coursework diagram.

## Relational model

```mermaid
erDiagram
    COST_CENTRES ||--o{ EMPLOYEES : contains
    COST_CENTRES ||--o{ BUDGETS : has
    COST_CENTRES ||--o{ EXPENSES : receives
    EMPLOYEES ||--o{ EXPENSES : submits
    BUDGETS ||--o{ EXPENSES : funds
    EXPENSES ||--o{ DECISIONS : receives
    EMPLOYEES ||--o{ DECISIONS : makes
    EMPLOYEES ||--o{ API_SESSIONS : owns
    EMPLOYEES o|--o{ DECISIONS : target_of

    COST_CENTRES {
        int id PK
        varchar name UK
    }
    EMPLOYEES {
        int id PK
        varchar name
        varchar email UK
        int cost_centre_id FK
        timestamp created_at
    }
    BUDGETS {
        int id PK
        int cost_centre_id FK
        numeric total
        numeric remaining
        int version
        timestamp updated_at
    }
    EXPENSES {
        int id PK
        int employee_id FK
        int cost_centre_id FK
        int budget_id FK
        numeric amount
        text description
        date expense_date
        varchar status
        timestamp created_at
    }
    DECISIONS {
        int id PK
        int expense_id FK
        int approver_id FK
        varchar decision
        text comment
        text rule_version
        jsonb evidence_snapshot
        timestamp created_at
        int target_approver_id FK
    }
    API_SESSIONS {
        char token_hash PK
        int employee_id FK
        timestamptz created_at
        timestamptz expires_at
        timestamptz revoked_at
    }
```

`decisions.target_approver_id` is nullable and references an employee; an escalation records the employee to whom it is assigned. The base schema defines the other tables, while `api_sessions` is introduced separately by a migration. The additive `002_decision_evidence.sql` migration adds nullable evidence fields to existing decisions; new decisions record a rule version and JSONB snapshot. See [decision evidence](DECISION_EVIDENCE.md).

**Important constraints:** `budgets.remaining` must be between zero and `total`, and `budgets.version` supports concurrency checks; expense amounts are positive and statuses are `pending`, `approved`, `rejected`, or `escalated`. Decisions are `approved`, `rejected`, or `escalated`.

## Vector storage (PostgreSQL / pgvector)

```mermaid
erDiagram
    VECTOR_DOCUMENTS {
        text id PK
        text document_type
        text content
        text source_id
        text filter_group
        timestamptz refreshed_at
        int source_version
        vector384 embedding
    }
```

`vector_documents` is independent of the transactional foreign-key graph; the vector is stored as `VECTOR(384)`. The corresponding Qdrant store is maintained separately rather than through a cross-database foreign key. `source_version` is optional and is NULL for legacy or unversioned documents. When the source supplies a version it is copied to PostgreSQL and Qdrant; `refreshed_at` records when each derived copy was written, not the timestamp of the source change.

## Other stores

- **Neo4j:** `Employee` and `CostCentre` nodes; `RESPONSIBLE_FOR`, `DELEGATED_TO` and `REVIEWER_FOR` authorization edges. IDs correspond to PostgreSQL employees and cost centres, but there are no cross-database foreign keys.
- **MongoDB:** receipt-shaped documents validated using a JSON Schema, including expense ID, vendor, country, VAT number, total, currency and receipt date.
- **Redis:** cached approver chains with expiration and invalidation.
- **Qdrant:** embeddings and metadata for receipt and policy similarity-search experiments.

See [architecture and workflow notes](ARCHITECTURE.md). Earlier materials are preserved in the [coursework archive](coursework/README.md).

This page documents schema structure, not a claim that operations across the five databases share an atomic transaction.
