import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from app.api.routes import analysis_runs as analysis_routes
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import (
    AnalysisDiagnostic,
    AnalysisFinding,
    AnalysisInterpretation,
    AnalysisResult,
    AnalysisRun,
    AnalysisScore,
    AnalysisStatus,
    FindingSeverity,
    FindingSource,
    Project,
    Website,
)
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


def test_api_results_response_and_cascade(client: TestClient, db_session: Session) -> None:
    website = create_website(db_session)
    now = datetime.now(UTC)
    run = AnalysisRun(
        website_id=website.id,
        status=AnalysisStatus.COMPLETED,
        progress_percent=100,
        completed_at=now,
    )
    db_session.add(run)
    db_session.flush()
    db_session.add(
        AnalysisResult(
            analysis_run_id=run.id,
            requested_url=website.url,
            final_url=website.url,
            http_status_code=200,
            page_title="Example",
            analysis_started_at=now,
            analysis_completed_at=now,
            raw_lighthouse_data={
                "categories": {
                    "performance": {"score": 0.8},
                    "accessibility": {"score": 0.9},
                    "best-practices": {
                        "score": 1.0,
                        "auditRefs": [{"id": "manual-security"}],
                    },
                    "seo": {"score": 0.95},
                },
                "audits": {
                    "manual-security": {
                        "title": "Manual security review",
                        "score": None,
                        "scoreDisplayMode": "manual",
                    }
                },
                "lighthouseVersion": "13.3.0",
                "fetchTime": now.isoformat(),
                "configSettings": {
                    "formFactor": "desktop",
                    "throttlingMethod": "provided",
                    "screenEmulation": {"disabled": True},
                },
                "environment": {"hostUserAgent": "Chromium/140.0.0.0"},
            },
            raw_playwright_data={"h1_count": 0, "html_language": "en"},
        )
    )
    db_session.add(
        AnalysisDiagnostic(
            analysis_run_id=run.id,
            group_name="policy_diagnostics",
            payload={
                "status": "available",
                "verified_observations": {},
                "unavailable_observations": [],
                "evidence": [],
                "score": None,
                "limitations": [],
                "collected_at": now.isoformat(),
                "copyright": {
                    "status": "available",
                    "verified_observations": {
                        "detected_text": f"Copyright {now.year} Example",
                        "current_year_present": True,
                        "result": "current_year_detected",
                        "confidence_percent": 90,
                    },
                    "unavailable_observations": [],
                    "evidence": [{"code": "COPYRIGHT_CURRENT_YEAR"}],
                    "score": None,
                    "limitations": ["Copyright detection does not prove legal ownership."],
                    "collected_at": now.isoformat(),
                },
            },
        )
    )
    db_session.add(
        AnalysisFinding(
            analysis_run_id=run.id,
            finding_code="MISSING_H1",
            category="seo",
            title="Missing H1 heading",
            description="The homepage has no H1 heading.",
            severity=FindingSeverity.MEDIUM,
            affected_url=website.url,
            evidence={"h1_count": 0},
            source=FindingSource.PLAYWRIGHT,
            confidence_percent=100,
        )
    )
    db_session.add(
        AnalysisScore(
            analysis_run_id=run.id,
            formula_version="1.0.0",
            overall_score=88,
            performance_score=80,
            accessibility_score=90,
            best_practices_score=100,
            seo_score=95,
            technical_quality_score=92,
            confidence_percent=100,
            available_categories=[
                "performance",
                "accessibility",
                "best_practices",
                "seo",
                "technical_quality",
            ],
            unavailable_categories=[],
            weights={
                "performance": 25,
                "accessibility": 20,
                "best_practices": 15,
                "seo": 20,
                "technical_quality": 20,
            },
            deductions=[
                {
                    "finding_code": "MISSING_H1",
                    "severity": "medium",
                    "source": "playwright",
                    "deduction_amount": 8,
                }
            ],
            calculation_details={"rounding": "round-half-up"},
        )
    )
    db_session.commit()

    status_response = client.get(f"/api/v1/analysis-runs/{run.id}")
    results_response = client.get(f"/api/v1/analysis-runs/{run.id}/results")

    assert status_response.json()["result_summary"]["performance_score"] == 80
    assert status_response.json()["result_summary"]["finding_count"] == 1
    assert status_response.json()["result_summary"]["overall_score"] == 88
    assert results_response.status_code == 200
    assert results_response.json()["lighthouse_metrics"]["seo_score"] == 95
    assert (
        results_response.json()["lighthouse_metrics"]["lighthouse_context"]["form_factor"]
        == "desktop"
    )
    assert results_response.json()["lighthouse_metrics"]["lighthouse_audit_breakdown"][0][
        "manual_check"
    ]
    assert results_response.json()["findings"][0]["finding_code"] == "MISSING_H1"
    assert (
        results_response.json()["diagnostics"]["policy_diagnostics"]["copyright"][
            "verified_observations"
        ]["result"]
        == "current_year_detected"
    )

    report_response = client.get(f"/api/v1/analysis-runs/{run.id}/report")
    assert report_response.status_code == 200
    assert report_response.json()["score"]["technical_quality_score"] == 92
    assert report_response.json()["website"]["url"] == website.url
    assert report_response.json()["interpretation"] is None

    db_session.add(
        AnalysisInterpretation(
            analysis_run_id=run.id,
            generation_mode="deterministic_fallback",
            provider="disabled",
            model="not-configured",
            prompt_version="1.0.0",
            executive_summary="Verified summary.",
            overall_assessment="Verified assessment.",
            strengths=[],
            weaknesses=[{"text": "Missing H1.", "related_finding_codes": ["MISSING_H1"]}],
            priority_recommendations=[
                {
                    "recommendation_id": "REC-1",
                    "title": "Add H1",
                    "explanation": "Address the finding.",
                    "related_finding_codes": ["MISSING_H1"],
                    "priority": "medium",
                    "business_impact": "Improves structure.",
                    "recommended_fix": "Add one H1.",
                    "estimated_effort": "Small",
                    "responsible_role": "Developer",
                    "expected_improvement": "Resolves finding.",
                    "confidence_percent": 100,
                }
            ],
            action_plan=[{"timeframe": "short_term", "recommendation_ids": ["REC-1"]}],
            limitations=["Homepage only."],
            fallback_reason="provider_unavailable",
            generated_at=now,
        )
    )
    db_session.commit()
    interpreted_report = client.get(f"/api/v1/analysis-runs/{run.id}/report")
    assert interpreted_report.json()["interpretation"]["generation_mode"] == (
        "deterministic_fallback"
    )
    assert interpreted_report.json()["interpretation"]["priority_recommendations"][0][
        "related_finding_codes"
    ] == ["MISSING_H1"]

    db_session.delete(run)
    db_session.commit()
    assert db_session.scalar(select(func.count()).select_from(AnalysisResult)) == 0
    assert db_session.scalar(select(func.count()).select_from(AnalysisFinding)) == 0
    assert db_session.scalar(select(func.count()).select_from(AnalysisScore)) == 0
    assert db_session.scalar(select(func.count()).select_from(AnalysisInterpretation)) == 0
    assert db_session.scalar(select(func.count()).select_from(AnalysisDiagnostic)) == 0


def test_missing_report_returns_normalized_errors(client: TestClient, db_session: Session) -> None:
    website = create_website(db_session)
    run = AnalysisRun(website_id=website.id)
    db_session.add(run)
    db_session.commit()

    unavailable = client.get(f"/api/v1/analysis-runs/{run.id}/report")
    missing = client.get("/api/v1/analysis-runs/00000000-0000-0000-0000-000000000000/report")

    assert unavailable.status_code == 409
    assert unavailable.json()["error"]["code"] == "ANALYSIS_REPORT_NOT_AVAILABLE"
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "ANALYSIS_RUN_NOT_FOUND"
