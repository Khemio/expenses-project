
from datetime import date
from uuid import uuid4

import pytest

from app.database.neo4j import get_driver
from app.database.postgres import get_connection


@pytest.fixture
def expense_scenario():
    """Create an isolated expense approval scenario.

    PostgreSQL stores the business records.
    Neo4j stores the corresponding approval authority.

    Both are cleaned up after the test.
    """
    run_id = uuid4().hex

    cost_centre_id = None
    employee_id = None
    budget_id = None
    expense_id = None

    try:
        # Create PostgreSQL records.
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO cost_centres (name)
                    VALUES (%s)
                    RETURNING id
                    """,
                    (f"pytest-{run_id}",),
                )
                cost_centre_id = cur.fetchone()[0]

                cur.execute(
                    """
                    INSERT INTO employees (
                        name, email, cost_centre_id
                    )
                    VALUES (%s, %s, %s)
                    RETURNING id
                    """,
                    (
                        "Test Approver",
                        f"pytest-{run_id}@example.test",
                        cost_centre_id,
                    ),
                )
                employee_id = cur.fetchone()[0]

                cur.execute(
                    """
                    INSERT INTO budgets (
                        cost_centre_id, total, remaining
                    )
                    VALUES (%s, 2000, 2000)
                    RETURNING id, version
                    """,
                    (cost_centre_id,),
                )
                budget_id, version = cur.fetchone()

                cur.execute(
                    """
                    INSERT INTO expenses (
                        employee_id,
                        cost_centre_id,
                        budget_id,
                        amount,
                        description,
                        expense_date
                    )
                    VALUES (%s, %s, %s, 700, %s, %s)
                    RETURNING id
                    """,
                    (
                        employee_id,
                        cost_centre_id,
                        budget_id,
                        "Integration test expense",
                        date(2026, 11, 9),
                    ),
                )
                expense_id = cur.fetchone()[0]

        # Create matching Neo4j authorization data.
        with get_driver().session() as session:
            session.run(
                """
                CREATE (e:Employee {
                    employee_id: $employee_id,
                    name: 'Test Approver',
                    test_run_id: $run_id
                })

                CREATE (cc:CostCentre {
                    cost_centre_id: $cost_centre_id,
                    name: $centre_name,
                    test_run_id: $run_id
                })

                CREATE (e)-[:RESPONSIBLE_FOR]->(cc)
                """,
                employee_id=employee_id,
                cost_centre_id=cost_centre_id,
                centre_name=f"pytest-{run_id}",
                run_id=run_id,
            ).consume()

        yield {
            "expense_id": expense_id,
            "employee_id": employee_id,
            "budget_id": budget_id,
            "cost_centre_id": cost_centre_id,
            "version": version,
        }

    finally:
        try:
            # Remove only nodes created by this test.
            with get_driver().session() as session:
                session.run(
                    """
                    MATCH (n {test_run_id: $run_id})
                    DETACH DELETE n
                    """,
                    run_id=run_id,
                ).consume()

        finally:
            # Remove relational records in dependency order.
            if cost_centre_id is not None:
                with get_connection() as conn:
                    with conn.cursor() as cur:
                        if expense_id is not None:
                            cur.execute(
                                """
                                DELETE FROM decisions
                                WHERE expense_id = %s
                                """,
                                (expense_id,),
                            )

                            cur.execute(
                                """
                                DELETE FROM expenses
                                WHERE id = %s
                                """,
                                (expense_id,),
                            )

                        if budget_id is not None:
                            cur.execute(
                                "DELETE FROM budgets WHERE id = %s",
                                (budget_id,),
                            )

                        if employee_id is not None:
                            cur.execute(
                                "DELETE FROM employees WHERE id = %s",
                                (employee_id,),
                            )

                        cur.execute(
                            "DELETE FROM cost_centres WHERE id = %s",
                            (cost_centre_id,),
                        )
