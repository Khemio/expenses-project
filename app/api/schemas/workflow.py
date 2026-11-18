
from pydantic import BaseModel, Field


class ApprovalRequest(BaseModel):
    expected_version: int = Field(ge=1)


class WorkflowResponse(BaseModel):
    expense_id: int
    previous_status: str
    status: str
    approver_id: int
    comment: str



from pydantic import BaseModel, Field, field_validator


class RejectionRequest(BaseModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Rejection reason cannot be blank")
        return value


class EscalationRequest(BaseModel):
    expected_version: int = Field(ge=1)

