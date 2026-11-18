
import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.database.postgres import get_connection


pytestmark = pytest.mark.integration


@pytest.fixture
def client():
    with TestClient(create_app()) as test_client:
        yield test_client


def make_payload(scenario):
    return {
        "cost_centre_id": scenario["cost_centre_id"],
        "budget_id": scenario["budget_id"],
        "amount": "125.50",
        "description": "Office supplies",
        "expense_date": "2026-11-16",
    }


def test_submit_expense(
    client, expense_scenario, auth_token
):
    scenario = expense_scenario
    payload = make_payload(scenario)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT remaining, version
                FROM budgets WHERE id = %s
                """,
                (scenario["budget_id"],),
            )
            before = cur.fetchone()

    response = client.post(
        "/api/v1/expenses",
        json=payload,
        headers={
            "Authorization": f"Bearer {auth_token}"
        },
    )

    assert response.status_code == 201

    expense = response.json()
    scenario["track_expense"](expense["id"])

    assert expense["employee_id"] == scenario["employee_id"]
    assert expense["amount"] == "125.50"
    assert expense["status"] == "pending"

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT remaining, version
                FROM budgets WHERE id = %s
                """,
                (scenario["budget_id"],),
            )
            after = cur.fetchone()

    assert after == before


def test_submit_requires_authentication(
    client, expense_scenario
):
    response = client.post(
        "/api/v1/expenses",
        json=make_payload(expense_scenario),
    )
    assert response.status_code == 401


def test_cannot_submit_for_another_cost_centre(
    client, expense_scenario, auth_token
):
    payload = make_payload(expense_scenario)
    payload["cost_centre_id"] = 999999999

    response = client.post(
        "/api/v1/expenses",
        json=payload,
        headers={
            "Authorization": f"Bearer {auth_token}"
        },
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "amount",
    ["0", "-1", "1.234", "10000000000.00"],
)
def test_invalid_amount(
    client, expense_scenario, auth_token, amount
):
    payload = make_payload(expense_scenario)
    payload["amount"] = amount

    response = client.post(
        "/api/v1/expenses",
        json=payload,
        headers={
            "Authorization": f"Bearer {auth_token}"
        },
    )

    assert response.status_code == 422
