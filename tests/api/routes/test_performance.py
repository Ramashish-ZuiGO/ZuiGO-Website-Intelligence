import uuid
from collections.abc import Iterator

import pytest
from app.db.base import Base  # noqa: F401
from app.db.session import get_db
from app.main import app
from app.models.agent_platform import AgentExecution
from app.models.analysis_run import AnalysisRun
from app.models.performance import PerformanceSnapshot
from app.models.project import Project
from app.models.website import Website
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
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
    def do_connect(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_get_website_performance(client: TestClient, db_session):
    proj = Project(id=uuid.uuid4(), name="T")
    db_session.add(proj)
    website = Website(id=uuid.uuid4(), url="https://example.com", project_id=proj.id)
    db_session.add(website)
    db_session.commit()

    snap = PerformanceSnapshot(
        execution_id=uuid.uuid4(),
        website_id=website.id,
        url_or_origin="https://example.com",
        evidence_source="crux",
        evidence_type="field",
        scope="url",
        form_factor="desktop",
        metric_id="field_lcp",
        availability_status="available",
        raw_value=1500,
    )
    db_session.add(snap)
    db_session.commit()

    response = client.get(f"/api/v1/websites/{website.id}/performance")
    assert response.status_code == 200
    data = response.json()
    assert len(data["data"]) == 1
    assert data["data"][0]["metric_id"] == "field_lcp"
    assert data["data"][0]["raw_value"] == 1500


def test_get_analysis_run_performance(client: TestClient, db_session):
    proj = Project(id=uuid.uuid4(), name="T")
    db_session.add(proj)
    website = Website(id=uuid.uuid4(), url="https://example.com", project_id=proj.id)
    db_session.add(website)
    run = AnalysisRun(id=uuid.uuid4(), website_id=website.id)
    db_session.add(run)
    db_session.commit()

    snap = PerformanceSnapshot(
        execution_id=run.id,
        website_id=website.id,
        analysis_run_id=run.id,
        url_or_origin="https://example.com",
        evidence_source="crux",
        evidence_type="field",
        scope="url",
        form_factor="phone",
        metric_id="field_inp",
        availability_status="available",
        raw_value=300,
    )
    db_session.add(snap)
    db_session.commit()

    response = client.get(f"/api/v1/analysis-runs/{run.id}/performance")
    assert response.status_code == 200
    data = response.json()
    assert len(data["data"]) == 1
    assert data["data"][0]["metric_id"] == "field_inp"
    assert data["data"][0]["raw_value"] == 300


def test_get_analysis_run_performance_finds_execution_tagged_field_evidence(
    client: TestClient, db_session
):
    """FE-9: real field-performance (CrUX) evidence is collected once per
    page-analysis execution (worker_app/tasks/page_analysis.py) and tagged
    by execution_id, not analysis_run_id -- page analysis runs BEFORE the
    main AnalysisRun exists, so it never had a real analysis_run_id to tag
    rows with (same real constraint M15 already solved for L2 accessibility/
    lighthouse evidence). This is the endpoint the frontend Performance
    panel actually calls; without resolving execution_id via the workflow's
    structured_input, it would never find real field rows that exist in the
    database.
    """
    proj = Project(id=uuid.uuid4(), name="T")
    db_session.add(proj)
    website = Website(id=uuid.uuid4(), url="https://example.com", project_id=proj.id)
    db_session.add(website)
    run = AnalysisRun(id=uuid.uuid4(), website_id=website.id)
    db_session.add(run)
    db_session.commit()

    page_execution_id = uuid.uuid4()
    workflow = AgentExecution(
        execution_id=uuid.uuid4(),
        workflow_id="full_website_analysis",
        workflow_version="1.0.0",
        project_id=proj.id,
        analysis_run_id=run.id,
        input_fingerprint="a" * 64,
        idempotency_key="perf-route-workflow",
        structured_input={"page_analysis_execution_id": str(page_execution_id)},
    )
    db_session.add(workflow)

    snap = PerformanceSnapshot(
        execution_id=page_execution_id,
        website_id=website.id,
        analysis_run_id=None,
        url_or_origin="https://example.com",
        evidence_source="crux",
        evidence_type="field",
        scope="url",
        form_factor="desktop",
        metric_id="field_lcp",
        availability_status="available",
        raw_value=2100,
    )
    db_session.add(snap)
    db_session.commit()

    response = client.get(f"/api/v1/analysis-runs/{run.id}/performance")
    assert response.status_code == 200
    data = response.json()
    assert len(data["data"]) == 1
    assert data["data"][0]["metric_id"] == "field_lcp"
    assert data["data"][0]["raw_value"] == 2100
    assert data["data"][0]["analysis_run_id"] is None


def test_collect_performance_evidence_route(client: TestClient, db_session):
    proj = Project(id=uuid.uuid4(), name="T")
    db_session.add(proj)
    website = Website(id=uuid.uuid4(), url="https://example.com", project_id=proj.id)
    db_session.add(website)
    run = AnalysisRun(id=uuid.uuid4(), website_id=website.id)
    db_session.add(run)
    db_session.commit()

    response = client.post(f"/api/v1/analysis-runs/{run.id}/performance/collect")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ["failed", "partial", "success"]


def test_get_website_performance_comparison(client: TestClient, db_session):
    proj = Project(id=uuid.uuid4(), name="T")
    db_session.add(proj)
    website = Website(id=uuid.uuid4(), url="https://example.com", project_id=proj.id)
    db_session.add(website)
    db_session.commit()

    exec_id = uuid.uuid4()
    snap = PerformanceSnapshot(
        execution_id=exec_id,
        website_id=website.id,
        url_or_origin="https://example.com",
        evidence_source="crux",
        evidence_type="field",
        scope="url",
        form_factor="desktop",
        metric_id="field_lcp",
        availability_status="available",
        raw_value=1500,
    )
    db_session.add(snap)
    db_session.commit()

    response = client.get(f"/api/v1/websites/{website.id}/performance/comparison")
    assert response.status_code == 200
    data = response.json()
    assert "disagreement" in data
    assert "explanation" in data
    assert len(data["field_evidence"]) == 1
    assert len(data["lab_evidence"]) == 0
