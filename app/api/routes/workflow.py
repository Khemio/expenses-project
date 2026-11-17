
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
    RejectionRequest,
    EscalationRequest,
    WorkflowResponse,
)
from app.services.exceptions import (
    BudgetConflict,
    ExpenseNotFound,
    UnauthorizedApprover,
    WorkflowError,
)
from app.services.expense_workflow import (
    approve_expense,
    reject_expense,
    escalate_expense,
)


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



@router.post(
    "/{expense_id}/reject",
    response_model=WorkflowResponse,
)
def reject_expense_endpoint(
    expense_id: Annotated[int, Path(gt=0)],
    payload: RejectionRequest,
    employee: Annotated[
        dict, Depends(get_current_employee)
    ],
) -> WorkflowResponse:
    try:
        result = reject_expense(
            expense_id=expense_id,
            approver_id=employee["id"],
            expected_version=payload.expected_version,
            reason=payload.reason,
        )
    except ExpenseNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail="Expense not found",
        ) from exc
    except UnauthorizedApprover as exc:
        raise HTTPException(
            status_code=403,
            detail="Not authorized to reject this expense",
        ) from exc
    except (BudgetConflict, WorkflowError) as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    return WorkflowResponse.model_validate(result)



@router.post(
    "/{expense_id}/escalate",
    response_model=WorkflowResponse,
)
def escalate_expense_endpoint(
    expense_id: Annotated[int, Path(gt=0)],
    payload: EscalationRequest,
    employee: Annotated[
        dict, Depends(get_current_employee)
    ],
) -> WorkflowResponse:
    try:
        result = escalate_expense(
            expense_id=expense_id,
            employee_id=employee["id"],
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
            detail="Not authorized to escalate this expense",
        ) from exc
    except (BudgetConflict, WorkflowError) as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    return WorkflowResponse.model_validate(result)
