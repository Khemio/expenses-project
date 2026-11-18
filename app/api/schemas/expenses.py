
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

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



class ExpenseCreate(BaseModel):
    cost_centre_id: int = Field(gt=0)
    budget_id: int = Field(gt=0)
    amount: Decimal = Field(
        gt=0,
        max_digits=12,
        decimal_places=2,
    )
    description: str = Field(
        min_length=1,
        max_length=2000,
    )
    expense_date: date

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("Description cannot be blank")

        return value
