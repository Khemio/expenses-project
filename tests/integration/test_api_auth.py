
import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.database.postgres import get_connection
from app.services.auth_sessions import (
    create_session,
    hash_session_token,
    revoke_session,
)


pytestmark = pytest.mark.integration


@pytest.fixture
def client():
    with TestClient(create_app()) as test_client:
        yield test_client




def test_authenticated_employee(
    client, auth_token, expense_scenario
):
    response = client.get(
        "/api/v1/auth/me",
        headers={
            "Authorization": f"Bearer {auth_token}"
        },
    )

    assert response.status_code == 200

    employee = response.json()

    assert employee["id"] == expense_scenario["employee_id"]
    assert employee["cost_centre_id"] == (
        expense_scenario["cost_centre_id"]
    )
    assert employee["name"] == "Test Approver"


def test_missing_authentication(client):
    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_invalid_token(client):
    response = client.get(
        "/api/v1/auth/me",
        headers={
            "Authorization": "Bearer invalid-token"
        },
    )

    assert response.status_code == 401


def test_revoked_token(client, auth_token):
    assert revoke_session(auth_token) is True

    response = client.get(
        "/api/v1/auth/me",
        headers={
            "Authorization": f"Bearer {auth_token}"
        },
    )

    assert response.status_code == 401


def test_expired_token(client, auth_token):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE api_sessions
                SET
                    created_at = NOW() - INTERVAL '2 days',
                    expires_at = NOW() - INTERVAL '1 day'
                WHERE token_hash = %s
                """,
                (hash_session_token(auth_token),),
            )

    response = client.get(
        "/api/v1/auth/me",
        headers={
            "Authorization": f"Bearer {auth_token}"
        },
    )

    assert response.status_code == 401
