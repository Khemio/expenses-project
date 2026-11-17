
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.dependencies.auth import get_current_employee
from app.api.schemas.approvals import ApprovalQueuePage
from app.services.approval_queries import (
    list_actionable_expenses,
)


router = APIRouter(
    prefix="/approvals",
    tags=["Approvals"],
)


@router.get(
    "",
    response_model=ApprovalQueuePage,
)
def read_approval_queue(
    employee: Annotated[
        dict, Depends(get_current_employee)
    ],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ApprovalQueuePage:
    result = list_actionable_expenses(
        approver_id=employee["id"],
        limit=limit,
        offset=offset,
    )

    return ApprovalQueuePage.model_validate(result)
