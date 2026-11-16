
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path

from app.api.schemas.expenses import ExpenseResponse
from app.services.expense_queries import get_expense

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
) -> ExpenseResponse:
    expense = get_expense(expense_id)

    if expense is None:
        raise HTTPException(
            status_code=404,
            detail="Expense not found",
        )

    return ExpenseResponse.model_validate(expense)
    