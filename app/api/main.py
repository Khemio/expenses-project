
from fastapi import FastAPI

from app.api.routes.health import router as health_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="Expense Approval API",
        version="0.1.0",
        description=(
            "API for expense submission, approval, "
            "authorization, and retrieval."
        ),
    )

    app.include_router(
        health_router,
        prefix="/api/v1",
    )

    return app


app = create_app()
