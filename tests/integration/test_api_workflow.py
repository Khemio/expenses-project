
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.database.postgres import get_connection
from app.services.auth_sessions import (
    create_session,
    hash_session_token,
)


pytestmark = pytest.mark.integration


@pytest.fixture
def client():
    with TestClient(create_app()) as test_client:
        yield test_client


def auth_header(token):
    return {"Authorization": f"Bearer {token}"}


def test_api_approval(
    client, decision_scenario, auth_token
):
    s = decision_scenario

    response = client.post(
        f"/api/v1/expenses/{s['expense_id']}/approve",
        json={"expected_version": s["version"]},
        headers=auth_header(auth_token),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    assert response.json()["approver_id"] == s["employee_id"]

    with get_connection() as conn:
        budget = conn.execute(
            """
            SELECT remaining, version
            FROM budgets WHERE id = %s
            """,
            (s["budget_id"],),
        ).fetchone()

        decisions = conn.execute(
            """
            SELECT decision, approver_id
            FROM decisions
            WHERE expense_id = %s
            """,
            (s["expense_id"],),
        ).fetchall()

    assert budget == (
        Decimal("1300"),
        s["version"] + 1,
    )
    assert decisions == [
        ("approved", s["employee_id"]),
    ]


def test_api_approval_requires_authentication(
    client, expense_scenario
):
    s = expense_scenario

    response = client.post(
        f"/api/v1/expenses/{s['expense_id']}/approve",
        json={"expected_version": s["version"]},
    )

    assert response.status_code == 401


def test_api_unauthorized_approval(
    client, decision_scenario
):
    s = decision_scenario
    token = create_session(s["unauthorized_employee_id"])

    try:
        response = client.post(
            f"/api/v1/expenses/{s['expense_id']}/approve",
            json={"expected_version": s["version"]},
            headers=auth_header(token),
        )
        assert response.status_code == 403

        with get_connection() as conn:
            status = conn.execute(
                "SELECT status FROM expenses WHERE id = %s",
                (s["expense_id"],),
            ).fetchone()[0]

            count = conn.execute(
                """
                SELECT COUNT(*) FROM decisions
                WHERE expense_id = %s
                """,
                (s["expense_id"],),
            ).fetchone()[0]

        assert status == "pending"
        assert count == 0

    finally:
        with get_connection() as conn:
            conn.execute(
                """
                DELETE FROM api_sessions
                WHERE token_hash = %s
                """,
                (hash_session_token(token),),
            )


def test_api_insufficient_budget(
    client, decision_scenario, auth_token
):
    s = decision_scenario

    with get_connection() as conn:
        conn.execute(
            "UPDATE expenses SET amount = 2500 WHERE id = %s",
            (s["expense_id"],),
        )

    response = client.post(
        f"/api/v1/expenses/{s['expense_id']}/approve",
        json={"expected_version": s["version"]},
        headers=auth_header(auth_token),
    )

    assert response.status_code == 409

    with get_connection() as conn:
        status = conn.execute(
            "SELECT status FROM expenses WHERE id = %s",
            (s["expense_id"],),
        ).fetchone()[0]

    assert status == "pending"


def test_api_approval_stale_version(
    client, decision_scenario, auth_token
):
    s = decision_scenario

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE budgets SET version = version + 1
            WHERE id = %s
            """,
            (s["budget_id"],),
        )

    response = client.post(
        f"/api/v1/expenses/{s['expense_id']}/approve",
        json={"expected_version": s["version"]},
        headers=auth_header(auth_token),
    )

    assert response.status_code == 409



def test_api_rejection(
    client, decision_scenario, auth_token
):
    s = decision_scenario
    response = client.post(
        f"/api/v1/expenses/{s['expense_id']}/reject",
        json={
            "expected_version": s["version"],
            "reason": "Incorrect receipt",
        },
        headers=auth_header(auth_token),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert response.json()["comment"] == "Incorrect receipt"

    with get_connection() as conn:
        budget = conn.execute(
            """
            SELECT remaining, version
            FROM budgets WHERE id = %s
            """,
            (s["budget_id"],),
        ).fetchone()

        decisions = conn.execute(
            """
            SELECT decision, comment
            FROM decisions WHERE expense_id = %s
            """,
            (s["expense_id"],),
        ).fetchall()

    assert budget == (Decimal("2000"), s["version"])
    assert decisions == [("rejected", "Incorrect receipt")]


def test_api_rejection_requires_authority(
    client, expense_scenario
):
    s = expense_scenario
    token = create_session(s["unauthorized_employee_id"])

    try:
        response = client.post(
            f"/api/v1/expenses/{s['expense_id']}/reject",
            json={
                "expected_version": s["version"],
                "reason": "Rejected",
            },
            headers=auth_header(token),
        )

        assert response.status_code == 403

    finally:
        with get_connection() as conn:
            conn.execute(
                """
                DELETE FROM api_sessions
                WHERE token_hash = %s
                """,
                (hash_session_token(token),),
            )


def test_api_rejection_requires_reason(
    client, decision_scenario, auth_token
):
    s = decision_scenario

    response = client.post(
        f"/api/v1/expenses/{s['expense_id']}/reject",
        json={
            "expected_version": s["version"],
            "reason": "   ",
        },
        headers=auth_header(auth_token),
    )

    assert response.status_code == 422



def test_api_escalation(client, decision_scenario):
    s = decision_scenario
    submitter_token = create_session(s["submitter_id"])

    try:
        response = client.post(
            f"/api/v1/expenses/{s['expense_id']}/escalate",
            json={"expected_version": s["version"]},
            headers=auth_header(submitter_token),
        )

        assert response.status_code == 200
        assert response.json()["status"] == "escalated"

        with get_connection() as conn:
            decisions = conn.execute(
                """
                SELECT decision, approver_id, target_approver_id
                FROM decisions
                WHERE expense_id = %s
                """,
                (s["expense_id"],),
            ).fetchall()

            budget = conn.execute(
                """
                SELECT remaining, version
                FROM budgets
                WHERE id = %s
                """,
                (s["budget_id"],),
            ).fetchone()

        assert decisions == [
            (
                "escalated",
                s["submitter_id"],
                s["approver_id"],
            ),
        ]

        assert budget == (
            Decimal("2000"),
            s["version"],
        )

    finally:
        with get_connection() as conn:
            conn.execute(
                """
                DELETE FROM api_sessions
                WHERE token_hash = %s
                """,
                (hash_session_token(submitter_token),),
            )



def test_api_non_submitter_cannot_escalate(
    client, expense_scenario
):
    s = expense_scenario
    token = create_session(s["unauthorized_employee_id"])

    try:
        response = client.post(
            f"/api/v1/expenses/{s['expense_id']}/escalate",
            json={"expected_version": s["version"]},
            headers=auth_header(token),
        )

        assert response.status_code == 403

        with get_connection() as conn:
            status = conn.execute(
                """
                SELECT status FROM expenses WHERE id = %s
                """,
                (s["expense_id"],),
            ).fetchone()[0]

        assert status == "pending"

    finally:
        with get_connection() as conn:
            conn.execute(
                """
                DELETE FROM api_sessions
                WHERE token_hash = %s
                """,
                (hash_session_token(token),),
            )
