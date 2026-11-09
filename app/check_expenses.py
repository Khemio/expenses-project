
import os

import psycopg
from dotenv import load_dotenv


load_dotenv()


def main():
    sql = """
        SELECT
            e.id,
            e.description,
            e.amount,
            e.status,
            emp.name AS employee_name,
            cc.name AS cost_centre
        FROM expenses e
        JOIN employees emp
            ON e.employee_id = emp.id
        JOIN cost_centres cc
            ON e.cost_centre_id = cc.id
        ORDER BY e.id;
    """

    with psycopg.connect(os.getenv("DATABASE_URL")) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()

    print("Existing expenses:")
    print("-" * 70)

    for row in rows:
        print(row)


if __name__ == "__main__":
    main()
