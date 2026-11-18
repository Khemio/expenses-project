
import pytest
from fastapi.testclient import TestClient
from datetime import date

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
    client, approval_handoff_scenario, auth_token
):
    s = approval_handoff_scenario

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
    client, decision_scenario, auth_token
):
    s = decision_scenario

    escalate_expense(
        expense_id=s["expense_id"],
        employee_id=s["submitter_id"],
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




def test_queue_pagination_after_authorization(
    client, decision_scenario, auth_token
):
    s = decision_scenario

    first_id = s["expense_id"]

    with get_connection() as conn:
        second_id = conn.execute(
            """
            INSERT INTO expenses (
                employee_id,
                cost_centre_id,
                budget_id,
                amount,
                description,
                expense_date
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                s["submitter_id"],
                s["cost_centre_id"],
                s["budget_id"],
                100,
                "Second queued expense",
                date(2026, 11, 9),
            ),
        ).fetchone()[0]

        third_id = conn.execute(
            """
            INSERT INTO expenses (
                employee_id,
                cost_centre_id,
                budget_id,
                amount,
                description,
                expense_date
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                s["submitter_id"],
                s["cost_centre_id"],
                s["budget_id"],
                200,
                "Third queued expense",
                date(2026, 11, 9),
            ),
        ).fetchone()[0]

    s["track_expense"](second_id)
    s["track_expense"](third_id)

    response = client.get(
        "/api/v1/approvals",
        params={"limit": 1, "offset": 1},
        headers=headers(auth_token),
    )

    assert response.status_code == 200

    page = response.json()

    assert page["total"] == 3
    assert page["limit"] == 1
    assert page["offset"] == 1

    assert [item["id"] for item in page["items"]] == [
        second_id
    ]

    assert first_id < second_id < third_id



def test_queue_reflects_revoked_authority(
    client, decision_scenario, auth_token
):
    from app.database.neo4j import get_driver

    s = decision_scenario

    before = client.get(
        "/api/v1/approvals",
        headers=headers(auth_token),
    )

    assert before.status_code == 200
    assert s["expense_id"] in {
        item["id"] for item in before.json()["items"]
    }

    # Remove the cost centre owner's authority.
    with get_driver().session() as session:
        session.run(
            """
            MATCH (e:Employee {
                employee_id: $employee_id
            })-[r:RESPONSIBLE_FOR]->(cc:CostCentre {
                cost_centre_id: $cost_centre_id
            })
            DELETE r
            """,
            employee_id=s["employee_id"],
            cost_centre_id=s["cost_centre_id"],
        ).consume()

    after = client.get(
        "/api/v1/approvals",
        headers=headers(auth_token),
    )

    assert after.status_code == 200
    assert after.json()["items"] == []
    assert after.json()["total"] == 0


def test_handoff_expense_visible_to_approver(
    client,
    approval_handoff_scenario,
):
    s = approval_handoff_scenario

    token = create_session(s["approver_id"])

    try:
        response = client.get(
            "/api/v1/approvals",
            headers=headers(token),
        )

        assert response.status_code == 200

        items = response.json()["items"]
        ids = {item["id"] for item in items}

        assert s["expense_id"] in ids

        expense = next(
            item for item in items
            if item["id"] == s["expense_id"]
        )

        assert expense["status"] == "pending"
        assert expense["budget_version"] == s["version"]

    finally:
        with get_connection() as conn:
            conn.execute(
                """
                DELETE FROM api_sessions
                WHERE token_hash = %s
                """,
                (hash_session_token(token),),
            )


def test_queue_excludes_own_expenses(
    client, expense_scenario, auth_token
):
    s = expense_scenario

    response = client.get(
        "/api/v1/approvals",
        headers=headers(auth_token),
    )

    assert response.status_code == 200

    ids = {
        item["id"]
        for item in response.json()["items"]
    }

    assert s["expense_id"] not in ids
