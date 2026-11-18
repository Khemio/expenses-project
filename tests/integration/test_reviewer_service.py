
import pytest

from app.database.neo4j import get_driver
from app.services.reviewer_service import (
    find_independent_reviewer,
    ReviewerConfigurationError,
)


pytestmark = pytest.mark.integration


def assign_reviewer(s, reviewer_id):
    with get_driver().session() as session:
        session.run(
            """
            MATCH (reviewer:Employee {
                employee_id: $reviewer_id
            })
            MATCH (cc:CostCentre {
                cost_centre_id: $cost_centre_id
            })
            CREATE (reviewer)-[:REVIEWER_FOR]->(cc)
            """,
            reviewer_id=reviewer_id,
            cost_centre_id=s["cost_centre_id"],
        ).consume()


def test_independent_reviewer_resolution(expense_scenario):
    s = expense_scenario
    reviewer_id = s["unauthorized_employee_id"]

    assign_reviewer(s, reviewer_id)

    assert find_independent_reviewer(
        s["cost_centre_id"],
        s["employee_id"],
    ) == reviewer_id


def test_missing_reviewer_returns_none(expense_scenario):
    s = expense_scenario

    assert find_independent_reviewer(
        s["cost_centre_id"],
        s["employee_id"],
    ) is None


def test_regular_submitter_does_not_use_independent_path(
    expense_scenario,
):
    s = expense_scenario

    assign_reviewer(s, s["unauthorized_employee_id"])

    assert find_independent_reviewer(
        s["cost_centre_id"],
        s["unauthorized_employee_id"],
    ) is None


def test_self_review_configuration_is_rejected(expense_scenario):
    s = expense_scenario

    assign_reviewer(s, s["employee_id"])

    with pytest.raises(
        ReviewerConfigurationError,
        match="cannot be the submitter",
    ):
        find_independent_reviewer(
            s["cost_centre_id"],
            s["employee_id"],
        )


def test_reviewer_revocation(expense_scenario):
    s = expense_scenario
    reviewer_id = s["unauthorized_employee_id"]

    assign_reviewer(s, reviewer_id)

    assert find_independent_reviewer(
        s["cost_centre_id"],
        s["employee_id"],
    ) == reviewer_id

    with get_driver().session() as session:
        session.run(
            """
            MATCH (reviewer:Employee {
                employee_id: $reviewer_id
            })-[r:REVIEWER_FOR]->
            (cc:CostCentre {
                cost_centre_id: $cost_centre_id
            })
            DELETE r
            """,
            reviewer_id=reviewer_id,
            cost_centre_id=s["cost_centre_id"],
        ).consume()

    assert find_independent_reviewer(
        s["cost_centre_id"],
        s["employee_id"],
    ) is None
