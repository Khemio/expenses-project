
import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app

pytestmark = pytest.mark.integration

@pytest.fixture
def client():
    with TestClient(create_app()) as test_client:
        yield test_client

def test_get_existing_expense(client, expense_scenario):
    expense_id = expense_scenario["expense_id"]

    response = client.get(
        f"/api/v1/expenses/{expense_id}"
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

def test_get_nonexistent_expense(client):
    response = client.get(
        "/api/v1/expenses/999999999"
    )

    assert response.status_code == 404
    assert response.json() == {
        "detail": "Expense not found"
    }

def test_get_expense_invalid_id(client):
    response = client.get(
        "/api/v1/expenses/0"
    )

    assert response.status_code == 422