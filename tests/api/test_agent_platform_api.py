from app.main import app
from fastapi.testclient import TestClient


def test_agent_tool_and_workflow_metadata_endpoints() -> None:
    with TestClient(app) as client:
        agents = client.get("/api/v1/agents")
        tools = client.get("/api/v1/tools")
        workflows = client.get("/api/v1/workflows")

        assert agents.status_code == 200
        assert tools.status_code == 200
        assert workflows.status_code == 200
        assert [item["agent_id"] for item in agents.json()] == sorted(
            item["agent_id"] for item in agents.json()
        )
        assert [item["tool_id"] for item in tools.json()] == sorted(
            item["tool_id"] for item in tools.json()
        )
        assert [item["workflow_id"] for item in workflows.json()] == sorted(
            item["workflow_id"] for item in workflows.json()
        )
        assert len(agents.json()) == 8
        assert len(tools.json()) == 15
        assert len(workflows.json()) == 3
        assert all(item["version"] == "1.0.0" for item in agents.json())
        assert all(item["version"] == "1.0.0" for item in tools.json())
        assert all(item["version"] == "1.0.0" for item in workflows.json())


def test_metadata_detail_and_deterministic_404_endpoints() -> None:
    endpoint_cases = (
        ("/api/v1/agents/discovery_agent", "agent_id", "discovery_agent"),
        ("/api/v1/tools/url_normalization", "tool_id", "url_normalization"),
        (
            "/api/v1/workflows/full_website_analysis",
            "workflow_id",
            "full_website_analysis",
        ),
    )
    with TestClient(app) as client:
        for path, field, expected in endpoint_cases:
            response = client.get(path)
            assert response.status_code == 200
            assert response.json()[field] == expected

        missing_paths = (
            "/api/v1/agents/missing_agent",
            "/api/v1/tools/missing_tool",
            "/api/v1/workflows/missing_workflow",
        )
        for path in missing_paths:
            response = client.get(path)
            assert response.status_code == 404
            payload = response.json()
            assert payload["error"]["code"] == "NOT_FOUND"
            assert payload["error"]["message"] == "Resource not found."
