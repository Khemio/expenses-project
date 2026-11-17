
import argparse

from app.database.neo4j import get_driver
from app.services.money import to_cents


MAX_INT64 = 2**63 - 1


def prepare_migration(tx):
    """Validate every legacy delegation before writing."""
    records = list(
        tx.run(
            """
            MATCH ()-[r:DELEGATED_TO]->()
            RETURN
                elementId(r) AS relationship_id,
                r.amount_limit AS old_limit,
                r.amount_limit_cents AS new_limit
            """
        )
    )

    updates = []
    missing = []
    already_migrated = 0

    for record in records:
        relationship_id = record["relationship_id"]
        old_limit = record["old_limit"]
        new_limit = record["new_limit"]

        if old_limit is None:
            if new_limit is None:
                missing.append(relationship_id)
            else:
                if type(new_limit) is not int or new_limit < 0:
                    raise ValueError(
                        f"Invalid existing cents: {relationship_id}"
                    )
                already_migrated += 1
            continue

        if type(old_limit) is not int or old_limit < 0:
            raise ValueError(
                f"Expected nonnegative integer euros: "
                f"{relationship_id}: {old_limit!r}"
            )

        expected = to_cents(old_limit)

        if expected > MAX_INT64:
            raise ValueError(
                f"Limit exceeds Neo4j integer range: "
                f"{relationship_id}"
            )

        if new_limit is not None:
            if type(new_limit) is not int or new_limit != expected:
                raise ValueError(
                    f"Conflicting cents value: {relationship_id}, "
                    f"expected {expected}, got {new_limit!r}"
                )
            already_migrated += 1
        else:
            updates.append({
                "id": relationship_id,
                "cents": expected,
            })

    if missing:
        raise ValueError(
            f"{len(missing)} delegations have neither limit "
            f"property; first ID: {missing[0]}"
        )

    return len(records), already_migrated, updates


def migrate(tx, apply: bool):
    total, existing, updates = prepare_migration(tx)

    print(f"Total delegations: {total}")
    print(f"Already migrated: {existing}")
    print(f"Pending updates: {len(updates)}")

    if not apply:
        print("DRY RUN: no changes written.")
        return

    if updates:
        result = tx.run(
            """
            UNWIND $updates AS item
            MATCH ()-[r:DELEGATED_TO]->()
            WHERE elementId(r) = item.id
              AND r.amount_limit_cents IS NULL
            SET r.amount_limit_cents = item.cents
            RETURN count(r) AS updated
            """,
            updates=updates,
        ).single()

        updated = result["updated"]

        if updated != len(updates):
            raise RuntimeError(
                f"Expected {len(updates)} updates, got {updated}"
            )

    # Check the transaction's final state before committing.
    remaining = tx.run(
        """
        MATCH ()-[r:DELEGATED_TO]->()
        WHERE r.amount_limit_cents IS NULL
        RETURN count(r) AS missing
        """
    ).single()["missing"]

    if remaining:
        raise RuntimeError(
            f"{remaining} delegations remain unmigrated"
        )

    print("Migration verified within transaction.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write validated delegation limits",
    )
    args = parser.parse_args()

    with get_driver().session() as session:
        if args.apply:
            session.execute_write(migrate, True)
        else:
            session.execute_read(migrate, False)

    print("Completed successfully.")


if __name__ == "__main__":
    main()
