from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_health_returns_expected_response() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "service": "api"}


def test_health_allows_local_frontend_origin() -> None:
    response = client.get("/health", headers={"Origin": "http://localhost:3000"})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
