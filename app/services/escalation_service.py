import os

import psycopg
from dotenv import load_dotenv
from neo4j import GraphDatabase

from app.services.authorization_service import is_authorized_approver
from app.services.exceptions import BudgetConflict

load_dotenv()


class EscalationError(Exception):
    """Raised when an expense cannot be escalated."""
    pass


def find_responsible_approver(cost_centre_id: int):
    """
    Find the employee directly responsible for a cost centre.

    Returns the employee ID or None.
    """

    driver = GraphDatabase.driver(
        "bolt://localhost:7687",
        auth=("neo4j", os.getenv("NEO4J_PASSWORD")),
    )

    query = """
    MATCH (employee:Employee)-[:RESPONSIBLE_FOR]->(cc:CostCentre)
    WHERE cc.cost_centre_id = $cost_centre_id
    RETURN employee.employee_id AS employee_id
    ORDER BY employee.employee_id
    """

    try:
        with driver.session() as session:
            records = list(
                session.run(
                    query,
                    cost_centre_id=cost_centre_id,
                )
            )

            if not records:
                return None

            if len(records) != 1:
                raise EscalationError(
                    "Expected exactly one responsible employee"
                )

            return records[0]["employee_id"]

    finally:
        driver.close()


def escalate_expense(
    expense_id: int,
    current_approver_id: int,
    expected_version: int,
):
    """
    Escalate a pending expense to its responsible approver.

    Does not deduct money from the budget.
    """

    # 1. Read expense and budget information.
    with psycopg.connect(os.getenv("DATABASE_URL")) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    e.cost_centre_id,
                    e.amount,
                    e.expense_date,
                    e.status,
                    b.remaining,
                    b.version
                FROM expenses e
                JOIN budgets b ON e.budget_id = b.id
                WHERE e.id = %s
                """,
                (expense_id,),
            )

            expense = cur.fetchone()

    if expense is None:
        raise ValueError("Expense not found")

    (
        cost_centre_id,
        amount,
        expense_date,
        status,
        remaining,
        version,
    ) = expense

    if status != "pending":
        raise EscalationError("Expense is not pending")

    if version != expected_version:
        raise BudgetConflict("Budget version changed")

    if amount > remaining:
        raise EscalationError(
            "Insufficient budget; expense cannot be escalated"
        )

    # 2. Check whether the current approver already has authority.
    authorized = is_authorized_approver(
        approver_id=current_approver_id,
        cost_centre_id=cost_centre_id,
        amount=amount,
        expense_date=expense_date,
    )

    if authorized:
        raise EscalationError(
            "Current approver already has sufficient authority"
        )

    # 3. Find the responsible approver in Neo4j.
    target_approver_id = find_responsible_approver(
        cost_centre_id
    )

    if target_approver_id is None:
        raise EscalationError(
            "No responsible approver found"
        )

    if target_approver_id == current_approver_id:
        raise EscalationError(
            "Cannot escalate an expense to the same employee"
        )

    # 4. Verify the target's authority.
    target_authorized = is_authorized_approver(
        approver_id=target_approver_id,
        cost_centre_id=cost_centre_id,
        amount=amount,
        expense_date=expense_date,
    )

    if not target_authorized:
        raise EscalationError(
            "Responsible employee is not authorized"
        )

    # 5. Record escalation in PostgreSQL.
    with psycopg.connect(os.getenv("DATABASE_URL")) as conn:
        with conn.cursor() as cur:

            # Lock the expense to prevent duplicate decisions.
            cur.execute(
                """
                SELECT status, budget_id
                FROM expenses
                WHERE id = %s
                FOR UPDATE
                """,
                (expense_id,),
            )

            locked_expense = cur.fetchone()

            if locked_expense is None:
                raise ValueError("Expense disappeared")

            locked_status, budget_id = locked_expense

            if locked_status != "pending":
                raise EscalationError(
                    "Expense status changed during escalation"
                )

            # Recheck budget state after acquiring the expense lock.
            cur.execute(
                """
                SELECT remaining, version
                FROM budgets
                WHERE id = %s
                FOR UPDATE
                """,
                (budget_id,),
            )

            locked_budget = cur.fetchone()

            if locked_budget is None:
                raise ValueError("Budget not found")

            locked_remaining, locked_version = locked_budget

            if locked_version != expected_version:
                raise BudgetConflict(
                    "Budget version changed during escalation"
                )

            if locked_remaining < amount:
                raise EscalationError(
                    "Insufficient budget during escalation"
                )

            cur.execute(
                """
                UPDATE expenses
                SET status = 'escalated'
                WHERE id = %s
                  AND status = 'pending'
                """,
                (expense_id,),
            )

            if cur.rowcount != 1:
                raise EscalationError(
                    "Expense status changed"
                )

            cur.execute(
                """
                INSERT INTO decisions (
                    expense_id,
                    approver_id,
                    decision,
                    comment
                )
                VALUES (%s, %s, 'escalated', %s)
                """,
                (
                    expense_id,
                    current_approver_id,
                    f"Escalated to employee {target_approver_id}",
                ),
            )

        conn.commit()

    return {
        "expense_id": expense_id,
        "status": "escalated",
        "from_approver": current_approver_id,
        "to_approver": target_approver_id,
    }