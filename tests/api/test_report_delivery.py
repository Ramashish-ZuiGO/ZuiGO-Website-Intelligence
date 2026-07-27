import hashlib
import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import (
    AgentExecution,
    AgentRun,
    AnalysisResult,
    AnalysisRun,
    AnalysisScore,
    Project,
    ReportExecution,
    Website,
)
from app.services.priority import PRIORITY_FORMULA_VERSION
from app.services.report_delivery import (
    ReportDeliveryError,
    generate_report,
)
from app.services.scoring_formula import CATEGORY_WEIGHTS, FORMULA_VERSION
from app.services.scoring_intelligence import calculate_score_execution
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def report_api(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[
    tuple[
        TestClient,
        sessionmaker[Session],
        uuid.UUID,
        uuid.UUID,
        uuid.UUID,
        list[tuple[str, str, int]],
    ]
]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        project = Project(name="Report delivery")
        website = Website(
            project=project,
            url="https://report.test/",
            name="Report Fixture",
            profile_id="global_general",
        )
        run = AnalysisRun(
            website=website,
            status="completed",
            progress_percent=100,
            profile_id="global_general",
            profile_version="1.0.0",
            completed_at=datetime.now(UTC),
        )
        db.add_all([project, website, run])
        db.flush()
        result = AnalysisResult(
            analysis_run_id=run.id,
            requested_url=website.url,
            final_url=website.url,
            http_status_code=200,
            page_title="Report fixture",
            analysis_started_at=datetime.now(UTC),
            analysis_completed_at=datetime.now(UTC),
            raw_lighthouse_data={"categories": {"performance": {"score": 0.8}}},
            raw_playwright_data={"http_status_code": 200},
        )
        legacy_score = AnalysisScore(
            analysis_run_id=run.id,
            formula_version="1.0.0",
            overall_score=89,
            performance_score=80,
            accessibility_score=90,
            best_practices_score=70,
            seo_score=100,
            technical_quality_score=100,
            confidence_percent=100,
            available_categories=list(CATEGORY_WEIGHTS),
            unavailable_categories=[],
            weights=CATEGORY_WEIGHTS,
            deductions=[],
            calculation_details={"rounding": "round-half-up"},
        )
        workflow = AgentExecution(
            execution_id=uuid.uuid4(),
            workflow_id="full_website_analysis",
            workflow_version="1.0.0",
            project_id=project.id,
            analysis_run_id=run.id,
            input_fingerprint="a" * 64,
            idempotency_key="completed-workflow",
            status="completed",
            structured_input={
                "project_id": str(project.id),
                "website_id": str(website.id),
                "analysis_run_id": str(run.id),
                "repository_connection_id": None,
            },
            structured_output={"completed_agent_ids": ["report_agent"]},
            evidence_references=[],
            provider_version_metadata={},
            failure_details={},
            partial_completion_details={},
            completed_at=datetime.now(UTC),
        )
        db.add_all([result, legacy_score, workflow])
        db.commit()
        score, _ = calculate_score_execution(db, run.id, idempotency_key="report-score")
        run_id = run.id
        project_id = project.id
        website_id = website.id
        assert score.overall_score == 89

    dispatched: list[tuple[str, str, int]] = []

    def fake_enqueue(
        analysis_run_id: str,
        execution_id: str,
        *,
        workflow_attempt: int,
    ) -> tuple[str, str]:
        dispatched.append((analysis_run_id, execution_id, workflow_attempt))
        return (
            f"analysis-run:{analysis_run_id}",
            f"workflow-execution:{execution_id}:attempt:{workflow_attempt}",
        )

    monkeypatch.setattr(
        "app.api.routes.report_delivery.enqueue_analysis_journey",
        fake_enqueue,
    )

    def override_db() -> Iterator[Session]:
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    try:
        yield (
            TestClient(app),
            factory,
            project_id,
            website_id,
            run_id,
            dispatched,
        )
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def _generate_completed_report(
    factory: sessionmaker[Session],
    run_id: uuid.UUID,
    *,
    key: str = "report-key",
) -> ReportExecution:
    with factory() as db:
        report, _created = generate_report(db, run_id, idempotency_key=key)
        return report


def test_unified_start_idempotency_ownership_and_independent_history(
    report_api: tuple[
        TestClient,
        sessionmaker[Session],
        uuid.UUID,
        uuid.UUID,
        uuid.UUID,
        list[tuple[str, str, int]],
    ],
) -> None:
    client, factory, project_id, website_id, _run_id, dispatched = report_api
    payload = {"idempotency_key": "journey-one"}
    first = client.post(
        f"/api/v1/projects/{project_id}/websites/{website_id}/analysis/start",
        json=payload,
    )
    repeated = client.post(
        f"/api/v1/projects/{project_id}/websites/{website_id}/analysis/start",
        json=payload,
    )
    independent = client.post(
        f"/api/v1/projects/{project_id}/websites/{website_id}/analysis/start",
        json={"idempotency_key": "journey-two"},
    )
    assert first.status_code == repeated.status_code == independent.status_code == 202
    assert first.json()["analysis_run_id"] == repeated.json()["analysis_run_id"]
    assert first.json()["workflow_execution_id"] == repeated.json()["workflow_execution_id"]
    assert repeated.json()["reused"] is True
    assert independent.json()["analysis_run_id"] != first.json()["analysis_run_id"]
    assert len(dispatched) == 2
    assert (
        client.post(
            f"/api/v1/projects/{uuid.uuid4()}/websites/{website_id}/analysis/start",
            json={"idempotency_key": "wrong-owner"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/v1/projects/{project_id}/websites/{uuid.uuid4()}/analysis/start",
            json={"idempotency_key": "missing"},
        ).status_code
        == 404
    )
    with factory() as db:
        assert (
            db.query(AgentExecution)
            .filter(AgentExecution.idempotency_key.in_(["journey-one", "journey-two"]))
            .count()
            == 2
        )


def test_workflow_progress_states_coverage_and_safe_errors(
    report_api: tuple[
        TestClient,
        sessionmaker[Session],
        uuid.UUID,
        uuid.UUID,
        uuid.UUID,
        list[tuple[str, str, int]],
    ],
) -> None:
    client, factory, project_id, website_id, _run_id, _dispatched = report_api
    started = client.post(
        f"/api/v1/projects/{project_id}/websites/{website_id}/analysis/start",
        json={"idempotency_key": "progress"},
    ).json()
    execution_id = uuid.UUID(started["workflow_execution_id"])
    with factory() as db:
        execution = db.scalar(
            select(AgentExecution).where(AgentExecution.execution_id == execution_id)
        )
        assert execution is not None
        db.add(
            AgentRun(
                agent_run_id=uuid.uuid4(),
                execution_id=execution.id,
                agent_id="discovery_agent",
                agent_version="1.0.0",
                dependency_agent_run_ids=[],
                input_fingerprint="b" * 64,
                idempotency_key="progress:discovery",
                status="completed",
                structured_input={},
                structured_output={},
                tool_activity_summary=[
                    {
                        "tool_id": "website_discovery",
                        "status": "completed",
                    }
                ],
                evidence_references=[],
                provider_version_metadata={},
                failure_details={},
                partial_completion_details={},
                completed_at=datetime.now(UTC),
            )
        )
        db.commit()
    progress = client.get(f"/api/v1/workflow-executions/{execution_id}/progress")
    assert progress.status_code == 200
    payload = progress.json()
    assert payload["status"] == "pending"
    assert payload["completed_agent_ids"] == ["discovery_agent"]
    assert payload["current_stage"] == "accessibility_agent"
    assert payload["progress_percentage"] > 0
    assert payload["evidence_coverage"]["status"] == "unavailable"
    assert "retry_available" in payload and "resume_available" in payload
    assert "elapsed_seconds" in payload


def test_report_idempotency_history_sections_fallback_and_immutability(
    report_api: tuple[
        TestClient,
        sessionmaker[Session],
        uuid.UUID,
        uuid.UUID,
        uuid.UUID,
        list[tuple[str, str, int]],
    ],
) -> None:
    _client, factory, _project_id, _website_id, run_id, _dispatched = report_api
    with factory() as db:
        first, created = generate_report(db, run_id, idempotency_key="same")
        repeated, repeated_created = generate_report(db, run_id, idempotency_key="same")
        historical, historical_created = generate_report(
            db,
            run_id,
            idempotency_key="different",
        )
        assert created is True
        assert repeated_created is False
        assert historical_created is True
        assert repeated.report_id == first.report_id
        assert historical.report_id != first.report_id
        assert len(first.sections) == 12
        assert [item.section_key for item in first.sections] == [
            item
            for item in (
                "executive_summary",
                "scores",
                "performance",
                "accessibility",
                "site_diagnostics",
                "security_technical",
                "content_seo",
                "priority_action_plan",
                "remediation",
                "coverage_limitations",
                "methodology",
                "multi_agent_execution",
            )
        ]
        assert first.provider_version_metadata["generation_mode"] == "deterministic_fallback"
        assert first.status == "partial"
        assert "accessibility" in first.unavailable_sections
        original_fingerprint = first.input_fingerprint
        original_artifacts = [item.checksum_sha256 for item in first.artifacts]
        db.expire_all()
        persisted = db.scalar(
            select(ReportExecution).where(ReportExecution.report_id == first.report_id)
        )
        assert persisted is not None
        assert persisted.input_fingerprint == original_fingerprint
        assert [item.checksum_sha256 for item in first.artifacts] == original_artifacts
        assert db.query(ReportExecution).count() == 2


def test_html_pdf_json_artifacts_checksums_safety_and_repeatability(
    report_api: tuple[
        TestClient,
        sessionmaker[Session],
        uuid.UUID,
        uuid.UUID,
        uuid.UUID,
        list[tuple[str, str, int]],
    ],
) -> None:
    _client, factory, _project_id, _website_id, run_id, _dispatched = report_api
    report = _generate_completed_report(factory, run_id)
    artifacts = {item.format: item for item in report.artifacts}
    assert set(artifacts) == {"html", "pdf", "json"}
    for artifact in artifacts.values():
        assert artifact.size_bytes == len(artifact.content)
        assert artifact.checksum_sha256 == hashlib.sha256(artifact.content).hexdigest()
        assert "\\" not in artifact.filename and "/" not in artifact.filename
        assert artifact.storage_location.startswith("database://report-artifacts/")
    html_text = artifacts["html"].content.decode()
    assert "<main>" in html_text
    assert '<nav aria-label="Report sections">' in html_text
    assert "<caption>" in html_text
    assert "chain_of_thought" not in html_text
    assert "password" not in html_text.casefold()
    assert artifacts["pdf"].content.startswith(b"%PDF-1.4")
    assert b"Page 1 of " in artifacts["pdf"].content
    assert b"Table of contents" in artifacts["pdf"].content
    json_payload = json.loads(artifacts["json"].content)
    assert json_payload["schema_version"] == "1.0.0"
    assert len(json_payload["sections"]) == 12
    repeated = _generate_completed_report(factory, run_id)
    assert [item.checksum_sha256 for item in repeated.artifacts] == [
        item.checksum_sha256 for item in report.artifacts
    ]


def test_report_apis_filters_download_headers_and_errors(
    report_api: tuple[
        TestClient,
        sessionmaker[Session],
        uuid.UUID,
        uuid.UUID,
        uuid.UUID,
        list[tuple[str, str, int]],
    ],
) -> None:
    client, factory, _project_id, website_id, run_id, _dispatched = report_api
    workflow_id = None
    with factory() as db:
        workflow = db.scalar(
            select(AgentExecution).where(
                AgentExecution.analysis_run_id == run_id,
                AgentExecution.status == "completed",
            )
        )
        assert workflow is not None
        workflow_id = workflow.execution_id
    created = client.post(
        f"/api/v1/analysis-runs/{run_id}/reports/generate",
        json={
            "idempotency_key": "api-report",
            "workflow_execution_id": str(workflow_id),
        },
    )
    repeated = client.post(
        f"/api/v1/analysis-runs/{run_id}/reports/generate",
        json={
            "idempotency_key": "api-report",
            "workflow_execution_id": str(workflow_id),
        },
    )
    assert created.status_code == repeated.status_code == 201
    report_id = created.json()["report_id"]
    assert repeated.json()["report_id"] == report_id
    history = client.get(
        f"/api/v1/websites/{website_id}/reports/history",
        params={"limit": 1, "offset": 0, "status": "partial"},
    )
    assert history.status_code == 200
    assert history.json()["total"] == 1
    assert client.get(f"/api/v1/analysis-runs/{run_id}/reports?limit=1").status_code == 200
    assert client.get(f"/api/v1/reports/{report_id}").status_code == 200
    assert client.get(f"/api/v1/reports/{report_id}/status").status_code == 200
    assert len(client.get(f"/api/v1/reports/{report_id}/artifacts").json()["items"]) == 3
    for artifact_format in ("html", "pdf", "json"):
        download = client.get(f"/api/v1/reports/{report_id}/download/{artifact_format}")
        assert download.status_code == 200
        assert download.headers["content-disposition"].startswith("attachment; filename=")
        assert len(download.headers["x-content-sha256"]) == 64
        assert download.headers["x-content-type-options"] == "nosniff"
    assert client.get(f"/api/v1/reports/{report_id}/download/xml").status_code == 422
    assert client.get(f"/api/v1/reports/{uuid.uuid4()}").status_code == 404
    assert (
        client.post(
            f"/api/v1/analysis-runs/{run_id}/reports/generate",
            json={"idempotency_key": ""},
        ).status_code
        == 422
    )


def test_active_workflow_conflict_and_report_agent_internal_generation(
    report_api: tuple[
        TestClient,
        sessionmaker[Session],
        uuid.UUID,
        uuid.UUID,
        uuid.UUID,
        list[tuple[str, str, int]],
    ],
) -> None:
    _client, factory, project_id, _website_id, run_id, _dispatched = report_api
    with factory() as db:
        active = AgentExecution(
            execution_id=uuid.uuid4(),
            workflow_id="full_website_analysis",
            workflow_version="1.0.0",
            project_id=project_id,
            analysis_run_id=run_id,
            input_fingerprint="c" * 64,
            idempotency_key="active-workflow",
            status="running",
            structured_input={},
            structured_output={},
            evidence_references=[],
            provider_version_metadata={},
            failure_details={},
            partial_completion_details={},
        )
        db.add(active)
        db.commit()
        with pytest.raises(ReportDeliveryError) as error:
            generate_report(
                db,
                run_id,
                idempotency_key="active-rejected",
                workflow_execution_id=active.execution_id,
            )
        assert error.value.code == "WORKFLOW_NOT_TERMINAL"
        internal, created = generate_report(
            db,
            run_id,
            idempotency_key="active-agent",
            workflow_execution_id=active.execution_id,
            allow_active_workflow=True,
        )
        assert created is True
        assert internal.provider_version_metadata["report_agent_id"] == "report_agent"


def test_models_migration_no_private_reasoning_and_formulas_unchanged() -> None:
    tables = Base.metadata.tables
    assert {
        "report_executions",
        "report_snapshots",
        "report_sections",
        "report_artifacts",
    } <= set(tables)
    assert {
        constraint.ondelete for constraint in tables["report_executions"].foreign_key_constraints
    } == {"CASCADE", "SET NULL"}
    assert {index.name for index in tables["report_executions"].indexes} == {
        "ix_report_executions_project_status",
        "ix_report_executions_run_created",
        "ix_report_executions_website_created",
        "ix_report_executions_workflow",
    }
    columns = {
        column.name
        for table_name in (
            "report_executions",
            "report_snapshots",
            "report_sections",
            "report_artifacts",
        )
        for column in tables[table_name].columns
    }
    assert (
        not {
            "chain_of_thought",
            "hidden_reasoning",
            "private_reasoning",
            "internal_monologue",
        }
        & columns
    )
    migration = Path("apps/api/alembic/versions/20260729_0018_report_delivery.py").read_text(
        encoding="utf-8"
    )
    for table_name in (
        "report_executions",
        "report_snapshots",
        "report_sections",
        "report_artifacts",
    ):
        assert f'"{table_name}"' in migration
    assert FORMULA_VERSION == "1.0.0"
    assert PRIORITY_FORMULA_VERSION == "1.0.0"
    assert CATEGORY_WEIGHTS == {
        "performance": 25,
        "accessibility": 20,
        "best_practices": 15,
        "seo": 20,
        "technical_quality": 20,
    }
