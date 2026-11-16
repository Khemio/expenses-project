
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.dependencies.auth import get_current_employee


router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)


class CurrentEmployeeResponse(BaseModel):
    id: int
    name: str
    email: str
    cost_centre_id: int


@router.get(
    "/me",
    response_model=CurrentEmployeeResponse,
)
def read_current_employee(
    employee: Annotated[
        dict,
        Depends(get_current_employee),
    ],
) -> CurrentEmployeeResponse:
    return CurrentEmployeeResponse.model_validate(employee)
