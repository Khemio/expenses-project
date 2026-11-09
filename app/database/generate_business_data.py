import os
import random
from datetime import date, timedelta
from decimal import Decimal

import psycopg
from dotenv import load_dotenv

load_dotenv()

SEED = 42
EMPLOYEE_COUNT = 250
EXPENSE_COUNT = 250

COST_CENTRES = [
    "Synthetic - Finance",
    "Synthetic - Human Resources",
    "Synthetic - Engineering",
    "Synthetic - Sales",
    "Synthetic - Operations",
    "Synthetic - Research",
    "Synthetic - Customer Support",
    "Synthetic - Administration",
]

FIRST_NAMES = [
    "Anna", "Peter", "Emma", "David",
    "Maria", "Daniel", "Sofia", "Adam",
    "Julia", "Martin", "Laura", "Thomas",
]

LAST_NAMES = [
    "Kovacs", "Nagy", "Smith", "Miller",
    "Brown", "Horvath", "Wilson", "Taylor",
    "Varga", "Anderson", "Farkas", "Clark",
]

EXPENSE_TYPES = [
    ("Office equipment", 150, 1800),
    ("Software subscription", 20, 600),
    ("Business travel", 80, 1500),
    ("Professional training", 100, 1200),
    ("Office supplies", 10, 350),
    ("Client meeting", 30, 500),
    ("Conference registration", 100, 1000),
    ("Equipment maintenance", 50, 900),
]


def main():
    rng = random.Random(SEED)

    with psycopg.connect(os.getenv("DATABASE_URL")) as conn:
        with conn.cursor() as cur:

            # 1. Create dedicated synthetic cost centres.
            centre_ids = []

            for name in COST_CENTRES:
                cur.execute(
                    """
                    INSERT INTO cost_centres (name)
                    VALUES (%s)
                    ON CONFLICT (name) DO NOTHING
                    """,
                    (name,),
                )

                cur.execute(
                    """
                    SELECT id
                    FROM cost_centres
                    WHERE name = %s
                    """,
                    (name,),
                )

                centre_ids.append(cur.fetchone()[0])

            # 2. Create one budget per synthetic cost centre.
            budget_ids = {}

            for centre_id in centre_ids:
                cur.execute(
                    """
                    SELECT id
                    FROM budgets
                    WHERE cost_centre_id = %s
                    ORDER BY id
                    """,
                    (centre_id,),
                )

                existing = cur.fetchall()

                if len(existing) > 1:
                    raise RuntimeError(
                        f"Multiple budgets for synthetic centre "
                        f"{centre_id}; inspect before continuing"
                    )

                if existing:
                    budget_id = existing[0][0]
                else:
                    cur.execute(
                        """
                        INSERT INTO budgets (
                            cost_centre_id,
                            total,
                            remaining
                        )
                        VALUES (%s, 80000, 80000)
                        RETURNING id
                        """,
                        (centre_id,),
                    )

                    budget_id = cur.fetchone()[0]

                budget_ids[centre_id] = budget_id

            # 3. Create synthetic employees.
            employee_ids = []

            for number in range(1, EMPLOYEE_COUNT + 1):
                first = rng.choice(FIRST_NAMES)
                last = rng.choice(LAST_NAMES)
                centre_id = rng.choice(centre_ids)

                email = (
                    f"synthetic-expense-{number:04d}"
                    f"@example.test"
                )

                cur.execute(
                    """
                    INSERT INTO employees (
                        name,
                        email,
                        cost_centre_id
                    )
                    VALUES (%s, %s, %s)
                    ON CONFLICT (email) DO NOTHING
                    """,
                    (
                        f"{first} {last}",
                        email,
                        centre_id,
                    ),
                )

                cur.execute(
                    """
                    SELECT id
                    FROM employees
                    WHERE email = %s
                    """,
                    (email,),
                )

                employee_ids.append(cur.fetchone()[0])

            # 4. Create synthetic expenses.
            for number in range(1, EXPENSE_COUNT + 1):

                marker = f"[SYNTH-EXP-{number:04d}]"

                # Make the generator safe to rerun.
                cur.execute(
                    """
                    SELECT id
                    FROM expenses
                    WHERE description LIKE %s
                    """,
                    (f"{marker}%",),
                )

                if cur.fetchone() is not None:
                    continue

                employee_id = rng.choice(employee_ids)

                cur.execute(
                    """
                    SELECT cost_centre_id
                    FROM employees
                    WHERE id = %s
                    """,
                    (employee_id,),
                )

                centre_id = cur.fetchone()[0]

                expense_type, minimum, maximum = rng.choice(
                    EXPENSE_TYPES
                )

                amount = Decimal(
                    rng.randint(minimum * 100, maximum * 100)
                ) / Decimal("100")

                expense_date = (
                    date(2026, 1, 1)
                    + timedelta(days=rng.randint(0, 300))
                )

                description = (
                    f"{marker} {expense_type} "
                    f"for business operations"
                )

                cur.execute(
                    """
                    INSERT INTO expenses (
                        employee_id,
                        cost_centre_id,
                        budget_id,
                        amount,
                        description,
                        expense_date,
                        status
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, 'pending'
                    )
                    """,
                    (
                        employee_id,
                        centre_id,
                        budget_ids[centre_id],
                        amount,
                        description,
                        expense_date,
                    ),
                )

        conn.commit()

    print("SUCCESS: PostgreSQL synthetic data generated.")
    print("Synthetic employees:", EMPLOYEE_COUNT)
    print("Synthetic cost centres:", len(COST_CENTRES))
    print("Synthetic budgets:", len(budget_ids))
    print("Synthetic expenses:", EXPENSE_COUNT)


if __name__ == "__main__":
    main()