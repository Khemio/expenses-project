
from app.database.neo4j import get_driver


class ReviewerConfigurationError(Exception):
    """Independent reviewer configuration is invalid."""


def find_independent_reviewer(
    cost_centre_id: int,
    submitter_id: int,
) -> int | None:
    """Find a distinct reviewer for the responsible owner's expense.

    Return None if the submitter is not the responsible
    owner or no reviewer is configured.

    Fail closed for ambiguous or self-review assignments.
    """
    query = """
    MATCH (owner:Employee)-[:RESPONSIBLE_FOR]->
          (cc:CostCentre {cost_centre_id: $cost_centre_id})
    WITH cc, collect(DISTINCT owner.employee_id) AS owners
    OPTIONAL MATCH (reviewer:Employee)-[:REVIEWER_FOR]->(cc)
    RETURN
        owners,
        collect(DISTINCT reviewer.employee_id) AS reviewers
    """

    with get_driver().session() as session:
        record = session.run(
            query,
            cost_centre_id=cost_centre_id,
        ).single()

    if record is None:
        return None

    owners = record["owners"]
    reviewers = [
        reviewer_id
        for reviewer_id in record["reviewers"]
        if reviewer_id is not None
    ]

    if len(owners) != 1:
        raise ReviewerConfigurationError(
            "Expected exactly one responsible owner"
        )

    if owners[0] != submitter_id:
        return None

    if not reviewers:
        return None

    if len(reviewers) != 1:
        raise ReviewerConfigurationError(
            "Expected exactly one independent reviewer"
        )

    reviewer_id = reviewers[0]

    if reviewer_id == submitter_id:
        raise ReviewerConfigurationError(
            "Independent reviewer cannot be the submitter"
        )

    return reviewer_id
