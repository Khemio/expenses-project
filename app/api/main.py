from fastapi import FastAPI

from app.api.routes.health import router as health_router
from app.api.routes.expenses import router as expenses_router
from app.api.routes.auth import router as auth_router

def create_app() -> FastAPI:
    app = FastAPI(
        title="Expense Approval API",
        version="0.1.0",
        description=(
            "API for expense submission, approval, "
            "authorization, and retrieval."
        ),
    )

    app.include_router(health_router, prefix="/api/v1")
    app.include_router(expenses_router, prefix="/api/v1")
    app.include_router(auth_router, prefix="/api/v1")

    return app

app = create_app()