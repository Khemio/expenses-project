
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE cost_centres (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE
);

CREATE TABLE employees (
    id SERIAL PRIMARY KEY,
    name VARCHAR(150) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    cost_centre_id INTEGER NOT NULL
        REFERENCES cost_centres(id),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE budgets (
    id SERIAL PRIMARY KEY,
    cost_centre_id INTEGER NOT NULL
        REFERENCES cost_centres(id),
    total NUMERIC(12, 2) NOT NULL CHECK (total >= 0),
    remaining NUMERIC(12, 2) NOT NULL CHECK (
        remaining >= 0 AND remaining <= total
    ),
    version INTEGER NOT NULL DEFAULT 1,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE expenses (
    id SERIAL PRIMARY KEY,
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    cost_centre_id INTEGER NOT NULL REFERENCES cost_centres(id),
    budget_id INTEGER NOT NULL REFERENCES budgets(id),
    amount NUMERIC(12, 2) NOT NULL CHECK (amount > 0),
    description TEXT NOT NULL,
    expense_date DATE NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected', 'escalated')),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE decisions (
    id SERIAL PRIMARY KEY,
    expense_id INTEGER NOT NULL REFERENCES expenses(id),
    approver_id INTEGER NOT NULL REFERENCES employees(id),
    decision VARCHAR(20) NOT NULL
        CHECK (decision IN ('approved', 'rejected', 'escalated')),
    comment TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE decisions
ADD COLUMN IF NOT EXISTS target_approver_id INTEGER
REFERENCES employees(id);