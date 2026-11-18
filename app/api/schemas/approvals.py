
from pydantic import BaseModel, Field

from app.api.schemas.expenses import ExpenseResponse


class ApprovalQueueItem(ExpenseResponse):
    budget_version: int = Field(ge=1)


class ApprovalQueuePage(BaseModel):
    items: list[ApprovalQueueItem]
    total: int
    limit: int
    offset: int
