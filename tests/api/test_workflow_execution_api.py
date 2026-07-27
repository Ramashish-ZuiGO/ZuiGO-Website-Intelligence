import uuid
from collections.abc import Iterator

import pytest
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import AgentEvent, AgentExecution, AgentRun, Project, Website
from app.schemas.agent_platform import ExecutionStatus
from app.services.agent_platform_registry import AgentRegistry
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture
def execution_api(
    tmp_path: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, sessionmaker[Session], uuid.UUID, uuid.UUID, list[str]]]:
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'workflow-api.sqlite3'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        project = Project(name="Workflow API")
        db.add(project)
        db.flush()
        website = Website(
            project_id=project.id,
            url="https://example.test/",
            name="Fixture",
        )
        db.add(website)
        db.commit()
        project_id = project.id
        website_id = website.id

    def override_db() -> Iterator[Session]:
        with factory() as db:
            yield db

    dispatched: list[str] = []

    def enqueue(execution_id: str, *, attempt: int) -> str:
        task_id = f"workflow-execution:{execution_id}:attempt:{attempt}"
        dispatched.append(task_id)
        return task_id

    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(
        "app.api.routes.workflow_executions.enqueue_workflow_execution",
        enqueue,
    )
    monkeypatch.setattr(
        "app.api.routes.workflow_executions.enqueue_agent_retry",
        lambda run_id, next_attempt: f"agent-run:{run_id}:attempt:{next_attempt}",
    )
    monkeypatch.setattr(
        "app.api.routes.workflow_executions.revoke_workflow_task",
        lambda _task_id: None,
    )
    try:
        yield TestClient(app), factory, project_id, website_id, dispatched
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def _payload(project_id: uuid.UUID, website_id: uuid.UUID) -> dict[str, object]:
    return {
        "workflow_id": "full_website_analysis",
        "project_id": str(project_id),
        "website_id": str(website_id),
        "idempotency_key": "api-idempotency",
        "max_concurrency": 3,
    }


def test_execution_api_idempotent_start_get_filters_and_pagination(
    execution_api: tuple[
        TestClient,
        sessionmaker[Session],
        uuid.UUID,
        uuid.UUID,
        list[str],
    ],
) -> None:
    client, factory, project_id, website_id, dispatched = execution_api
    first = client.post(
        "/api/v1/workflow-executions",
        json=_payload(project_id, website_id),
    )
    repeated = client.post(
        "/api/v1/workflow-executions",
        json=_payload(project_id, website_id),
    )
    assert first.status_code == 202
    assert repeated.status_code == 202
    assert repeated.json()["execution_id"] == first.json()["execution_id"]
    assert len(dispatched) == 1

    execution_id = first.json()["execution_id"]
    detail = client.get(f"/api/v1/workflow-executions/{execution_id}")
    runs = client.get(
        f"/api/v1/workflow-executions/{execution_id}/runs",
        params={"limit": 1, "offset": 0, "status": "pending"},
    )
    events = client.get(
        f"/api/v1/workflow-executions/{execution_id}/events",
        params={"limit": 1, "offset": 0},
    )
    assert detail.status_code == 200
    assert runs.status_code == 200
    assert runs.json() == {"items": [], "total": 0, "limit": 1, "offset": 0}
    assert events.status_code == 200
    assert events.json() == {"items": [], "total": 0, "limit": 1, "offset": 0}

    with factory() as db:
        assert db.query(AgentExecution).count() == 1


def test_execution_api_cancel_resume_and_completed_conflicts(
    execution_api: tuple[
        TestClient,
        sessionmaker[Session],
        uuid.UUID,
        uuid.UUID,
        list[str],
    ],
) -> None:
    client, factory, project_id, website_id, dispatched = execution_api
    started = client.post(
        "/api/v1/workflow-executions",
        json=_payload(project_id, website_id),
    )
    execution_id = uuid.UUID(started.json()["execution_id"])
    cancelled = client.post(f"/api/v1/workflow-executions/{execution_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    resumed = client.post(f"/api/v1/workflow-executions/{execution_id}/resume")
    assert resumed.status_code == 202
    assert resumed.json()["status"] == "pending"
    assert resumed.json()["attempt"] == 2
    assert len(dispatched) == 2

    with factory() as db:
        execution = db.scalar(
            select(AgentExecution).where(AgentExecution.execution_id == execution_id)
        )
        assert execution is not None
        execution.status = ExecutionStatus.COMPLETED.value
        db.commit()
    conflict = client.post(f"/api/v1/workflow-executions/{execution_id}/cancel")
    resume_conflict = client.post(f"/api/v1/workflow-executions/{execution_id}/resume")
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "COMPLETED_EXECUTION_IMMUTABLE"
    assert resume_conflict.status_code == 409


def test_execution_api_run_retry_and_event_external_ids(
    execution_api: tuple[
        TestClient,
        sessionmaker[Session],
        uuid.UUID,
        uuid.UUID,
        list[str],
    ],
) -> None:
    client, factory, project_id, website_id, _dispatched = execution_api
    started = client.post(
        "/api/v1/workflow-executions",
        json=_payload(project_id, website_id),
    )
    execution_id = uuid.UUID(started.json()["execution_id"])
    with factory() as db:
        execution = db.scalar(
            select(AgentExecution).where(AgentExecution.execution_id == execution_id)
        )
        assert execution is not None
        definition = AgentRegistry.get("discovery_agent")
        assert definition is not None
        run = AgentRun(
            execution_id=execution.id,
            agent_id=definition.agent_id,
            agent_version=definition.version,
            input_fingerprint=execution.input_fingerprint,
            idempotency_key="api-retry",
            status=ExecutionStatus.FAILED.value,
            attempt=1,
            structured_input={},
            failure_details={"transient": True},
        )
        db.add(run)
        db.flush()
        event = AgentEvent(
            execution_id=execution.id,
            agent_run_id=run.id,
            event_type="agent_failed",
            sequence_number=0,
            status=ExecutionStatus.FAILED.value,
            structured_payload={"failure_code": "temporary_unavailable"},
        )
        db.add(event)
        execution.status = ExecutionStatus.FAILED.value
        db.commit()
        run_id = run.agent_run_id
        event_id = event.event_id

    runs = client.get(
        f"/api/v1/workflow-executions/{execution_id}/runs",
        params={"agent_id": "discovery_agent", "status": "failed"},
    )
    events = client.get(
        f"/api/v1/workflow-executions/{execution_id}/events",
        params={"event_type": "agent_failed", "status": "failed"},
    )
    retried = client.post(f"/api/v1/agent-runs/{run_id}/retry")
    assert runs.status_code == 200
    assert runs.json()["items"][0]["agent_run_id"] == str(run_id)
    assert events.status_code == 200
    assert events.json()["items"][0]["event_id"] == str(event_id)
    assert events.json()["items"][0]["agent_run_id"] == str(run_id)
    assert retried.status_code == 202
    assert retried.json()["status"] == "pending"


def test_execution_api_validation_ownership_and_deterministic_errors(
    execution_api: tuple[
        TestClient,
        sessionmaker[Session],
        uuid.UUID,
        uuid.UUID,
        list[str],
    ],
) -> None:
    client, factory, project_id, website_id, _dispatched = execution_api
    missing = client.get(f"/api/v1/workflow-executions/{uuid.uuid4()}")
    invalid = client.post(
        "/api/v1/workflow-executions",
        json={
            **_payload(project_id, website_id),
            "max_concurrency": 0,
        },
    )
    unknown_workflow = client.post(
        "/api/v1/workflow-executions",
        json={
            **_payload(project_id, website_id),
            "workflow_id": "unknown_workflow",
        },
    )
    with factory() as db:
        other_project = Project(name="Other project")
        db.add(other_project)
        db.commit()
        other_project_id = other_project.id
    mismatch = client.post(
        "/api/v1/workflow-executions",
        json=_payload(other_project_id, website_id),
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "WORKFLOW_EXECUTION_NOT_FOUND"
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "VALIDATION_ERROR"
    assert unknown_workflow.status_code == 404
    assert unknown_workflow.json()["error"]["code"] == "WORKFLOW_NOT_FOUND"
    assert mismatch.status_code == 422
    assert mismatch.json()["error"]["code"] == "WORKFLOW_SCOPE_MISMATCH"


def test_exact_execution_control_api_paths() -> None:
    expected = {
        ("POST", "/api/v1/workflow-executions"),
        ("GET", "/api/v1/workflow-executions/{execution_id}"),
        ("GET", "/api/v1/workflow-executions/{execution_id}/runs"),
        ("GET", "/api/v1/workflow-executions/{execution_id}/events"),
        ("POST", "/api/v1/workflow-executions/{execution_id}/cancel"),
        ("POST", "/api/v1/workflow-executions/{execution_id}/resume"),
        ("POST", "/api/v1/agent-runs/{run_id}/retry"),
    }
    actual = {
        (method, route.path)
        for route in app.routes
        for method in (route.methods or set())
        if (method, route.path) in expected
    }
    assert actual == expected
