``` mermaid
    
erDiagram
    EMPLOYEES ||--o{ EXPENSES : submits
    COST_CENTRES ||--o{ EMPLOYEES : contains
    COST_CENTRES ||--o{ BUDGETS : has
    COST_CENTRES ||--o{ EXPENSES : receives
    BUDGETS ||--o{ EXPENSES : funds
    EXPENSES ||--o{ DECISIONS : receives
    EMPLOYEES ||--o{ DECISIONS : makes

    EMPLOYEES {
        int id PK
        string name
        string email
        int cost_centre_id FK
    }
    COST_CENTRES {
        int id PK
        string name
    }
    BUDGETS {
        int id PK
        int cost_centre_id FK
        decimal total
        decimal remaining
        int version
    }
    EXPENSES {
        int id PK
        int employee_id FK
        int cost_centre_id FK
        int budget_id FK
        decimal amount
        string description
        string status
    }
    DECISIONS {
        int id PK
        int expense_id FK
        int approver_id FK
        string decision
        timestamp created_at
    }

```