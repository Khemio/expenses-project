
from fastapi.testclient import TestClient

from app.api.main import create_app


def test_health_endpoint():
    app = create_app()

    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_schema_available():
    app = create_app()

    with TestClient(app) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200

    schema = response.json()

    assert schema["info"]["title"] == "Expense Approval API"
    assert "/api/v1/health" in schema["paths"]
