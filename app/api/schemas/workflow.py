
from pydantic import BaseModel, Field


class ApprovalRequest(BaseModel):
    expected_version: int = Field(ge=1)


class WorkflowResponse(BaseModel):
    expense_id: int
    previous_status: str
    status: str
    approver_id: int
    comment: str
