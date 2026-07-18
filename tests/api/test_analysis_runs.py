import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from app.api.routes import analysis_runs as analysis_routes
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import AnalysisRun, AnalysisStatus, Project, Website
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def db_session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection: object, connection_record: object) -> None:
        del connection_record
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def client(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    def override_get_db() -> Iterator[Session]:
        yield db_session

    monkeypatch.setattr(analysis_routes, "enqueue_analysis", lambda run_id: f"task-{run_id}")
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def create_website(db_session: Session) -> Website:
    project = Project(name="Analysis project")
    website = Website(project=project, url="https://example.com/")
    db_session.add_all([project, website])
    db_session.commit()
    db_session.refresh(website)
    return website


def test_start_analysis_creates_queued_run_and_stores_task_id(
    client: TestClient, db_session: Session
) -> None:
    website = create_website(db_session)

    response = client.post(f"/api/v1/websites/{website.id}/analysis-runs")

    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert response.json()["progress_percent"] == 0
    run = db_session.get(AnalysisRun, uuid.UUID(response.json()["id"]))
    assert run is not None
    assert run.status is AnalysisStatus.QUEUED
    assert run.celery_task_id == f"task-{run.id}"


def test_start_analysis_for_missing_website_returns_standard_error(client: TestClient) -> None:
    response = client.post("/api/v1/websites/00000000-0000-0000-0000-000000000000/analysis-runs")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "WEBSITE_NOT_FOUND"


def test_status_retrieval_and_missing_run(client: TestClient, db_session: Session) -> None:
    website = create_website(db_session)
    created = client.post(f"/api/v1/websites/{website.id}/analysis-runs").json()

    response = client.get(f"/api/v1/analysis-runs/{created['id']}")
    missing = client.get("/api/v1/analysis-runs/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "ANALYSIS_RUN_NOT_FOUND"


def test_analysis_history_is_newest_first(client: TestClient, db_session: Session) -> None:
    website = create_website(db_session)
    earlier = AnalysisRun(
        website_id=website.id,
        created_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    later = AnalysisRun(website_id=website.id, created_at=datetime.now(UTC))
    db_session.add_all([earlier, later])
    db_session.commit()

    response = client.get(f"/api/v1/websites/{website.id}/analysis-runs")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [str(later.id), str(earlier.id)]


def test_website_deletion_cascades_to_analysis_runs(db_session: Session) -> None:
    website = create_website(db_session)
    db_session.add(AnalysisRun(website_id=website.id))
    db_session.commit()

    db_session.delete(website)
    db_session.commit()

    assert db_session.scalar(select(func.count()).select_from(AnalysisRun)) == 0
