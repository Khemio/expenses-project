
from typing import Annotated

from fastapi import status
from fastapi import Depends
from fastapi import APIRouter, HTTPException, Path, Query

from app.api.schemas.expenses import ExpenseResponse, ExpensePage, ExpenseStatus
from app.api.dependencies.auth import get_current_employee
from app.services.expense_queries import get_expense, list_expenses
from app.services.expense_submission import (
    InvalidExpenseAssignment,
    submit_expense,
)


from app.api.schemas.expenses import ExpenseCreate

router = APIRouter(
    prefix="/expenses",
    tags=["Expenses"],
)


@router.get(
    "/{expense_id}",
    response_model=ExpenseResponse,
)
def read_expense(
    expense_id: Annotated[int, Path(gt=0)],
    employee: Annotated[
        dict, Depends(get_current_employee)
    ],
) -> ExpenseResponse:
    expense = get_expense(
        expense_id=expense_id,
        employee_id=employee["id"],
    )

    if expense is None:
        raise HTTPException(
            status_code=404,
            detail="Expense not found",
        )

    return ExpenseResponse.model_validate(expense)
    


@router.get("", response_model=ExpensePage)
def read_expenses(
    employee: Annotated[dict, Depends(get_current_employee)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    status: ExpenseStatus | None = None,
    cost_centre_id: Annotated[
        int | None, Query(gt=0)
    ] = None,
) -> ExpensePage:
    result = list_expenses(
        employee_id=employee["id"],
        limit=limit,
        offset=offset,
        status=status,
        cost_centre_id=cost_centre_id,
    )

    return ExpensePage.model_validate(result)



@router.post(
    "",
    response_model=ExpenseResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_expense(
    payload: ExpenseCreate,
    employee: Annotated[
        dict, Depends(get_current_employee)
    ],
) -> ExpenseResponse:
    try:
        expense = submit_expense(
            employee_id=employee["id"],
            cost_centre_id=payload.cost_centre_id,
            budget_id=payload.budget_id,
            amount=payload.amount,
            description=payload.description,
            expense_date=payload.expense_date,
        )
    except InvalidExpenseAssignment as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    return ExpenseResponse.model_validate(expense)
