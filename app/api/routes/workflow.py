
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Path,
)

from app.api.dependencies.auth import get_current_employee
from app.api.schemas.workflow import (
    ApprovalRequest,
    WorkflowResponse,
)
from app.services.exceptions import (
    BudgetConflict,
    ExpenseNotFound,
    UnauthorizedApprover,
    WorkflowError,
)
from app.services.expense_workflow import approve_expense


router = APIRouter(
    prefix="/expenses",
    tags=["Expense Workflow"],
)


@router.post(
    "/{expense_id}/approve",
    response_model=WorkflowResponse,
)
def approve_expense_endpoint(
    expense_id: Annotated[int, Path(gt=0)],
    payload: ApprovalRequest,
    employee: Annotated[
        dict,
        Depends(get_current_employee),
    ],
) -> WorkflowResponse:
    try:
        result = approve_expense(
            expense_id=expense_id,
            approver_id=employee["id"],
            expected_version=payload.expected_version,
        )
    except ExpenseNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail="Expense not found",
        ) from exc
    except UnauthorizedApprover as exc:
        raise HTTPException(
            status_code=403,
            detail="Not authorized to approve this expense",
        ) from exc
    except (BudgetConflict, WorkflowError) as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    return WorkflowResponse.model_validate(result)
