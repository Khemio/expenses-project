import os

from psycopg.conninfo import conninfo_to_dict
from app.config import get_settings
from datetime import date
from uuid import uuid4

import pytest

from app.database.neo4j import get_driver
from app.database.postgres import get_connection
from tests.integration.factories import ExpenseFactory



@pytest.fixture(autouse=True)
def require_test_databases():
    """Refuse integration tests against development databases."""

    if os.getenv("EXPENSE_TEST_MODE") != "1":
        pytest.fail(
            "Integration tests must use the dedicated test runner."
        )

    settings = get_settings()
    pg = conninfo_to_dict(settings.database_url)

    expected_pg = {
        "host": "127.0.0.1",
        "port": "55432",
        "dbname": "expense_approval_test",
        "user": "expense_test",
    }

    for key, expected in expected_pg.items():
        if str(pg.get(key)) != expected:
            pytest.fail(
                f"Unsafe PostgreSQL test configuration: {key}"
            )

    if settings.neo4j_uri != "bolt://127.0.0.1:57687":
        pytest.fail(
            "Unsafe Neo4j test configuration"
        )


@pytest.fixture
def expense_scenario():
    """Create an isolated expense approval scenario.

    PostgreSQL stores the business records.
    Neo4j stores the corresponding approval authority.

    Both are cleaned up after the test.
    """
    run_id = uuid4().hex

    unauthorized_employee_id = None
    cost_centre_id = None
    employee_id = None
    budget_id = None
    expense_id = None
    expense_factory = None

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
                    INSERT INTO employees (
                        name, email, cost_centre_id
                    )
                    VALUES (%s, %s, %s)
                    RETURNING id
                    """,
                    (
                        "Unauthorized Test Employee",
                        f"pytest-unauthorized-{run_id}@example.test",
                        cost_centre_id,
                    ),
                )
                unauthorized_employee_id = cur.fetchone()[0]

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
                # created_expense_ids.append(expense_id)
                expense_factory = ExpenseFactory(
                    employee_id=employee_id,
                    cost_centre_id=cost_centre_id,
                    budget_id=budget_id,
                )

                expense_factory.track(expense_id)

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

                CREATE (:Employee {
                    employee_id: $unauthorized_employee_id,
                    name: 'Unauthorized Test Employee',
                    test_run_id: $run_id
                })
                """,
                unauthorized_employee_id=unauthorized_employee_id,
                employee_id=employee_id,
                cost_centre_id=cost_centre_id,
                centre_name=f"pytest-{run_id}",
                run_id=run_id,
            ).consume()


        # def create_expense(
        #     amount=700,
        #     description="Additional integration test expense",
        #     expense_date=date(2026, 11, 9),
        # ):
        #     """Create an expense using the scenario's existing budget."""

        #     with get_connection() as conn:
        #         with conn.cursor() as cur:
        #             cur.execute(
        #                 """
        #                 INSERT INTO expenses (
        #                     employee_id,
        #                     cost_centre_id,
        #                     budget_id,
        #                     amount,
        #                     description,
        #                     expense_date
        #                 )
        #                 VALUES (%s, %s, %s, %s, %s, %s)
        #                 RETURNING id
        #                 """,
        #                 (
        #                     employee_id,
        #                     cost_centre_id,
        #                     budget_id,
        #                     amount,
        #                     description,
        #                     expense_date,
        #                 ),
        #             )

        #             new_expense_id = cur.fetchone()[0]
        #             created_expense_ids.append(new_expense_id)

        #     return new_expense_id


        yield {
            "expense_id": expense_id,
            "employee_id": employee_id,
            "unauthorized_employee_id": unauthorized_employee_id,
            "budget_id": budget_id,
            "cost_centre_id": cost_centre_id,
            "version": version,
            # "create_expense": create_expense,
            "create_expense": expense_factory.create,
        }


    finally:
        try:
            # Remove Neo4j nodes belonging to this test.
            with get_driver().session() as session:
                session.run(
                    """
                    MATCH (n {test_run_id: $run_id})
                    DETACH DELETE n
                    """,
                    run_id=run_id,
                ).consume()

        finally:
            # Remove PostgreSQL records in dependency order.
            if cost_centre_id is not None:
                with get_connection() as conn:
                    with conn.cursor() as cur:
                        if expense_factory is not None:
                            expense_factory.cleanup(cur)

                        # 1. Decisions reference expenses and employees.
                        # if created_expense_ids:
                        #     cur.execute(
                        #         """
                        #         DELETE FROM decisions
                        #         WHERE expense_id = ANY(%s)
                        #         """,
                        #         (created_expense_ids,),
                        #     )

                        #     cur.execute(
                        #         """
                        #         DELETE FROM expenses
                        #         WHERE id = ANY(%s)
                        #         """,
                        #         (created_expense_ids,),
                        #     )

                        # # 3. Remove the budget.
                        if budget_id is not None:
                            cur.execute(
                                """
                                DELETE FROM budgets
                                WHERE id = %s
                                """,
                                (budget_id,),
                            )

                        # # 4. Remove both employees.
                        if unauthorized_employee_id is not None:
                            cur.execute(
                                """
                                DELETE FROM employees
                                WHERE id = %s
                                """,
                                (unauthorized_employee_id,),
                            )

                        if employee_id is not None:
                            cur.execute(
                                """
                                DELETE FROM employees
                                WHERE id = %s
                                """,
                                (employee_id,),
                            )

                        # # 5. Remove the cost centre last.
                        cur.execute(
                            """
                            DELETE FROM cost_centres
                            WHERE id = %s
                            """,
                            (cost_centre_id,),
                        )

