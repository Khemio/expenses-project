
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

ExpenseStatus = Literal[
    "pending",
    "approved",
    "rejected",
    "escalated",
]

class ExpenseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    employee_id: int
    cost_centre_id: int
    budget_id: int
    amount: Decimal
    description: str
    expense_date: date
    status: ExpenseStatus
    created_at: datetime


class ExpensePage(BaseModel):
    items: list[ExpenseResponse]
    total: int
    limit: int
    offset: int
