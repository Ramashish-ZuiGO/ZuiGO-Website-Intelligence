from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_get_all_metrics():
    response = client.get("/api/v1/metadata/metrics")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) > 0

    # Check that required fields are serialized correctly
    first_metric = data[0]
    assert "metric_id" in first_metric
    assert "label" in first_metric
    assert "category" in first_metric


def test_get_metrics_with_category_filter():
    response = client.get("/api/v1/metadata/metrics?category=site_score")
    assert response.status_code == 200
    data = response.json()
    assert len(data) > 0
    for metric in data:
        assert metric["category"] == "site_score"


def test_get_metrics_with_value_type_filter():
    response = client.get("/api/v1/metadata/metrics?value_type=percentage")
    assert response.status_code == 200
    data = response.json()
    assert len(data) > 0
    for metric in data:
        assert metric["value_type"] == "percentage"


def test_get_metric_by_id():
    response = client.get("/api/v1/metadata/metrics/overall_score")
    assert response.status_code == 200
    data = response.json()
    assert data["metric_id"] == "overall_score"
    assert data["label"] == "Overall Score"


def test_get_unknown_metric():
    response = client.get("/api/v1/metadata/metrics/unknown_metric_123")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
