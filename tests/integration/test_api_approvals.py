
import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.database.postgres import get_connection
from app.services.auth_sessions import (
    create_session,
    hash_session_token,
)
from app.services.expense_workflow import escalate_expense


pytestmark = pytest.mark.integration


@pytest.fixture
def client():
    with TestClient(create_app()) as test_client:
        yield test_client


def headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_approver_sees_pending_expenses(
    client, expense_scenario, auth_token
):
    s = expense_scenario

    response = client.get(
        "/api/v1/approvals",
        headers=headers(auth_token),
    )

    assert response.status_code == 200

    page = response.json()
    ids = [item["id"] for item in page["items"]]

    assert s["expense_id"] in ids

    expense = next(
        item for item in page["items"]
        if item["id"] == s["expense_id"]
    )

    assert expense["status"] == "pending"
    assert expense["budget_version"] == s["version"]


def test_unauthorized_employee_has_empty_queue(
    client, expense_scenario
):
    s = expense_scenario

    token = create_session(
        s["unauthorized_employee_id"]
    )

    try:
        response = client.get(
            "/api/v1/approvals",
            headers=headers(token),
        )

        assert response.status_code == 200
        assert response.json()["items"] == []
        assert response.json()["total"] == 0

    finally:
        with get_connection() as conn:
            conn.execute(
                """
                DELETE FROM api_sessions
                WHERE token_hash = %s
                """,
                (hash_session_token(token),),
            )


def test_assigned_escalation_appears_in_queue(
    client, expense_scenario, auth_token
):
    s = expense_scenario

    escalate_expense(
        expense_id=s["expense_id"],
        employee_id=s["employee_id"],
        expected_version=s["version"],
    )

    response = client.get(
        "/api/v1/approvals",
        headers=headers(auth_token),
    )

    assert response.status_code == 200

    items = response.json()["items"]
    expense = next(
        item for item in items
        if item["id"] == s["expense_id"]
    )

    assert expense["status"] == "escalated"
    assert expense["budget_version"] == s["version"]


def test_approval_queue_requires_authentication(client):
    response = client.get("/api/v1/approvals")

    assert response.status_code == 401


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
    ],
)
def test_invalid_queue_pagination(client, auth_token, params):
    response = client.get(
        "/api/v1/approvals",
        params=params,
        headers=headers(auth_token),
    )

    assert response.status_code == 422
