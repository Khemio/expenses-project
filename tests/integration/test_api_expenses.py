
import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app

pytestmark = pytest.mark.integration

@pytest.fixture
def client():
    with TestClient(create_app()) as test_client:
        yield test_client

def test_get_existing_expense(client, expense_scenario, auth_headers):
    expense_id = expense_scenario["expense_id"]

    response = client.get(
        f"/api/v1/expenses/{expense_id}",
        headers=auth_headers,
    )

    assert response.status_code == 200

    body = response.json()

    assert body["id"] == expense_id
    assert body["employee_id"] == (
        expense_scenario["employee_id"]
    )
    assert body["budget_id"] == (
        expense_scenario["budget_id"]
    )
    assert body["amount"] == "700.00"
    assert body["status"] == "pending"
    assert body["description"] == (
        "Integration test expense"
    )

def test_get_nonexistent_expense(client, auth_headers):
    response = client.get(
        "/api/v1/expenses/999999999",
        headers=auth_headers,
    )

    assert response.status_code == 404
    assert response.json() == {
        "detail": "Expense not found"
    }

def test_get_expense_invalid_id(client, auth_headers):
    response = client.get(
        "/api/v1/expenses/0",
        headers=auth_headers,
    )

    assert response.status_code == 422


def test_list_expenses_with_pagination(
    client, expense_scenario, auth_headers
):
    first_id = expense_scenario["expense_id"]
    second_id = expense_scenario["create_expense"](
        description="Second expense"
    )
    third_id = expense_scenario["create_expense"](
        description="Third expense"
    )

    centre_id = expense_scenario["cost_centre_id"]

    response = client.get(
        "/api/v1/expenses",
        params={
            "cost_centre_id": centre_id,
            "limit": 2,
            "offset": 0,
        },
        headers=auth_headers,
    )

    assert response.status_code == 200

    page = response.json()
    assert page["total"] == 3
    assert page["limit"] == 2
    assert page["offset"] == 0
    assert [
        item["id"] for item in page["items"]
    ] == [third_id, second_id]

    next_page = client.get(
        "/api/v1/expenses",
        params={
            "cost_centre_id": centre_id,
            "limit": 2,
            "offset": 2,
        },
        headers=auth_headers,
    ).json()

    assert next_page["total"] == 3
    assert [
        item["id"] for item in next_page["items"]
    ] == [first_id]


def test_list_expenses_status_filter(
    client, expense_scenario, auth_headers
):
    response = client.get(
        "/api/v1/expenses",
        params={
            "cost_centre_id": expense_scenario[
                "cost_centre_id"
            ],
            "status": "approved",
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["total"] == 0
    assert response.json()["items"] == []


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
        {"status": "unknown"},
        {"cost_centre_id": 0},
    ],
)
def test_list_expenses_invalid_parameters(
    client, params, auth_headers
):
    response = client.get(
        "/api/v1/expenses",
        params=params,
        headers=auth_headers,
    )

    assert response.status_code == 422



@pytest.fixture
def auth_headers(auth_token):
    return {
        "Authorization": f"Bearer {auth_token}"
    }



@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/expenses",
        "/api/v1/expenses/1",
    ],
)
def test_expenses_require_authentication(client, path):
    response = client.get(path)
    assert response.status_code == 401


def test_employee_cannot_read_another_employees_expense(
    client,
    expense_scenario,
):
    from app.database.postgres import get_connection
    from app.services.auth_sessions import (
        create_session,
        hash_session_token,
    )

    token = create_session(
        expense_scenario["unauthorized_employee_id"]
    )

    try:
        headers = {
            "Authorization": f"Bearer {token}"
        }

        expense_id = expense_scenario["expense_id"]

        response = client.get(
            f"/api/v1/expenses/{expense_id}",
            headers=headers,
        )
        assert response.status_code == 404

        response = client.get(
            "/api/v1/expenses",
            headers=headers,
            params={
                "cost_centre_id": expense_scenario[
                    "cost_centre_id"
                ]
            },
        )
        assert response.status_code == 200
        assert response.json()["items"] == []
        assert response.json()["total"] == 0

    finally:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM api_sessions
                    WHERE token_hash = %s
                    """,
                    (hash_session_token(token),),
                )
