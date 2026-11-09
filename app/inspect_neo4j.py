import os

from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()


def main():
    driver = GraphDatabase.driver(
        "bolt://localhost:7687",
        auth=("neo4j", os.getenv("NEO4J_PASSWORD")),
    )

    try:
        with driver.session() as session:

            print("\n=== EMPLOYEES ===")

            result = session.run("""
                MATCH (e:Employee)
                RETURN properties(e) AS properties
                LIMIT 10
            """)

            for record in result:
                print(record["properties"])

            print("\n=== COST CENTRES ===")

            result = session.run("""
                MATCH (c:CostCentre)
                RETURN properties(c) AS properties
                LIMIT 10
            """)

            for record in result:
                print(record["properties"])

            print("\n=== RELATIONSHIPS ===")

            result = session.run("""
                MATCH (a)-[r]->(b)
                RETURN
                    labels(a) AS from_labels,
                    properties(a) AS from_properties,
                    type(r) AS relationship_type,
                    properties(r) AS relationship_properties,
                    labels(b) AS to_labels,
                    properties(b) AS to_properties
                LIMIT 20
            """)

            for record in result:
                print(
                    record["from_labels"],
                    record["from_properties"],
                    "->",
                    record["relationship_type"],
                    record["relationship_properties"],
                    "->",
                    record["to_labels"],
                    record["to_properties"],
                )

    finally:
        driver.close()


if __name__ == "__main__":
    main()