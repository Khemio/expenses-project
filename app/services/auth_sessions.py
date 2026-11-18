
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from psycopg.rows import dict_row

from app.database.postgres import get_connection


DEFAULT_SESSION_LIFETIME = timedelta(hours=8)


def generate_session_token() -> str:
    """Generate a cryptographically random bearer token."""
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    """Return a deterministic verifier for a session token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(
    employee_id: int,
    lifetime: timedelta = DEFAULT_SESSION_LIFETIME,
) -> str:
    """Create a session for an already authenticated employee.

    This function does not authenticate an employee.
    Only trusted authentication code may call it.
    """
    if lifetime <= timedelta(0):
        raise ValueError("Session lifetime must be positive")

    token = generate_session_token()
    expires_at = datetime.now(timezone.utc) + lifetime

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO api_sessions (
                    token_hash,
                    employee_id,
                    expires_at
                )
                VALUES (%s, %s, %s)
                """,
                (
                    hash_session_token(token),
                    employee_id,
                    expires_at,
                ),
            )

    return token


def get_session_employee(token: str) -> dict | None:
    """Return employee identity for an active session."""
    if not token:
        return None

    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT
                    e.id,
                    e.name,
                    e.email,
                    e.cost_centre_id
                FROM api_sessions AS s
                JOIN employees AS e
                    ON e.id = s.employee_id
                WHERE s.token_hash = %s
                  AND s.revoked_at IS NULL
                  AND s.expires_at > NOW()
                """,
                (hash_session_token(token),),
            )

            return cur.fetchone()


def revoke_session(token: str) -> bool:
    """Revoke a session. Return True if it was active."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE api_sessions
                SET revoked_at = NOW()
                WHERE token_hash = %s
                  AND revoked_at IS NULL
                  AND expires_at > NOW()
                """,
                (hash_session_token(token),),
            )

            return cur.rowcount == 1
