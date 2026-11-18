
CREATE TABLE IF NOT EXISTS api_sessions (
    token_hash CHAR(64) PRIMARY KEY,
    employee_id INTEGER NOT NULL
        REFERENCES employees(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,

    CONSTRAINT api_sessions_expiration_check
        CHECK (expires_at > created_at)
);

CREATE INDEX IF NOT EXISTS api_sessions_employee_idx
    ON api_sessions(employee_id);

CREATE INDEX IF NOT EXISTS api_sessions_expires_idx
    ON api_sessions(expires_at);
