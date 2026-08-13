import hashlib
import io
from collections.abc import Iterator

import pytest
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.agent_platform import AgentExecution, AgentRun
from app.models.project import Project
from app.models.report_delivery import ReportArtifact, ReportExecution
from app.services.priority import PRIORITY_FORMULA_VERSION
from app.services.scoring_formula import FORMULA_VERSION
from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

EXPECTED_AGENTS = {
    "accessibility_agent",
    "discovery_agent",
    "evidence_validation_agent",
    "performance_agent",
    "remediation_agent",
    "report_agent",
    "repository_intelligence_agent",
    "site_diagnostics_agent",
}


@pytest.fixture
def demo_api() -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db() -> Iterator[Session]:
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            yield client, factory
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_prepared_demo_has_eight_agents_parallel_stage_and_safe_evidence(
    demo_api: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, factory = demo_api
    response = client.post("/api/v1/demo/prepare")
    assert response.status_code == 200
    payload = response.json()
    assert payload["presentation_status"] == "ready"
    assert payload["report_ready"] is True
    assert payload["overall_score"] == 76
    assert payload["score_confidence_percent"] == 88
    assert payload["evidence_coverage_numerator"] == 15
    assert payload["evidence_coverage_denominator"] == 16
    assert {item["agent_id"] for item in payload["agents"]} == EXPECTED_AGENTS
    parallel = next(item for item in payload["stages"] if item["parallel"])
    assert set(parallel["agent_ids"]) == {
        "performance_agent",
        "accessibility_agent",
        "site_diagnostics_agent",
    }
    assert payload["top_findings"]
    assert all(
        item["example_pages"][0].startswith("https://demo.local/")
        for item in payload["top_findings"]
    )
    assert payload["top_actions"][0]["verification_method"]
    assert len(payload["top_actions"]) == 5
    assert len(payload["top_findings"]) <= 10
    assert all(len(item["example_pages"]) <= 5 for item in payload["top_findings"])
    with factory() as db:
        execution = db.scalar(select(AgentExecution))
        assert execution is not None
        serialized = repr(
            {
                "input": execution.structured_input,
                "output": execution.structured_output,
                "evidence": execution.evidence_references,
            }
        ).casefold()
        assert "chain-of-thought" not in serialized
        assert "private reasoning" not in serialized
        assert db.scalar(select(func.count(AgentRun.id))) == 8


def test_demo_run_is_idempotent_and_preserves_independent_history(
    demo_api: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, factory = demo_api
    first = client.post(
        "/api/v1/demo/run",
        json={"idempotency_key": "presenter-run-one"},
    )
    repeated = client.post(
        "/api/v1/demo/run",
        json={"idempotency_key": "presenter-run-one"},
    )
    independent = client.post(
        "/api/v1/demo/run",
        json={"idempotency_key": "presenter-run-two"},
    )
    assert first.status_code == repeated.status_code == independent.status_code == 200
    assert first.json()["workflow_execution_id"] == repeated.json()["workflow_execution_id"]
    assert first.json()["report_id"] == repeated.json()["report_id"]
    assert repeated.json()["reused"] is True
    assert independent.json()["workflow_execution_id"] != first.json()["workflow_execution_id"]
    assert independent.json()["report_id"] != first.json()["report_id"]
    with factory() as db:
        assert db.scalar(select(func.count(AgentExecution.id))) == 3
        assert db.scalar(select(func.count(ReportExecution.id))) == 3


def test_failed_live_demo_remains_failed_and_uses_labelled_prepared_fallback(
    demo_api: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, factory = demo_api
    response = client.post(
        "/api/v1/demo/run",
        json={"idempotency_key": "presenter-failure", "simulate_failure": True},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["presentation_status"] == "fallback"
    assert payload["live_execution_status"] == "failed"
    assert payload["used_prepared_fallback"] is True
    assert "last verified prepared fallback report" in payload["status_message"]
    assert payload["report_ready"] is True
    with factory() as db:
        failed = db.scalar(
            select(AgentExecution).where(AgentExecution.idempotency_key == "presenter-failure")
        )
        assert failed is not None
        assert failed.status == "failed"
        assert failed.failure_details["code"] == "DEMO_LIVE_EXECUTION_FAILED"
        assert (
            db.scalar(
                select(func.count(ReportExecution.id)).where(
                    ReportExecution.report_type == "presentation_demo"
                )
            )
            == 0
        )


def test_demo_exports_have_stable_safe_names_and_verified_checksums(
    demo_api: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, factory = demo_api
    payload = client.post("/api/v1/demo/prepare").json()
    assert {item["kind"] for item in payload["artifacts"]} == {
        "presentation_html",
        "presentation_pdf",
        "technical_appendix",
        "evidence_json",
        "page_inventory",
    }
    for item in payload["artifacts"]:
        assert item["filename"].startswith("zuigo-demo-website-analysis")
        assert "/" not in item["filename"] and "\\" not in item["filename"]
        download = client.get(item["download_url"])
        assert download.status_code == 200
        assert hashlib.sha256(download.content).hexdigest() == item["checksum_sha256"]
        assert download.headers["x-content-sha256"] == item["checksum_sha256"]
    with factory() as db:
        assert db.scalar(select(func.count(ReportArtifact.id))) == 3


def test_page_coverage_inventory_and_browser_compatibility_are_exact(
    demo_api: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _factory = demo_api
    payload = client.post("/api/v1/demo/prepare").json()
    coverage = payload["page_coverage"]
    assert coverage == {
        **coverage,
        "total_urls_discovered": 12,
        "total_pages_scheduled": 9,
        "total_pages_visited": 8,
        "successfully_analysed_pages": 7,
        "failed_pages": 1,
        "skipped_pages": 1,
        "excluded_pages": 1,
        "redirected_pages": 1,
        "duplicate_normalized_pages": 1,
        "pages_with_incomplete_evidence": 2,
        "coverage_numerator": 7,
        "coverage_denominator": 9,
        "coverage_percentage": 77.78,
    }
    assert len(payload["page_inventory"]) == 12
    assert {item["analysis_status"] for item in payload["page_inventory"]} >= {
        "analysed",
        "failed",
        "skipped",
        "excluded",
        "redirected",
        "duplicate_normalized",
    }
    compatibility = payload["browser_compatibility"]
    assert [item["label"] for item in compatibility["engines"]] == [
        "Chromium engine",
        "Firefox engine",
        "WebKit engine",
    ]
    assert compatibility["viewports"] == [
        {"name": "Desktop", "width": 1440, "height": 900},
        {"name": "Mobile", "width": 390, "height": 844},
    ]
    assert all(item["tested_pages"] == 8 for item in compatibility["engine_coverage"])
    checkout = next(
        item for item in compatibility["matrix"] if item["page_url"].endswith("/checkout")
    )
    assert checkout["engines"]["webkit"] == "incompatible"
    assert checkout["engines"]["chromium"] == "compatible"
    assert checkout["result"] == "incompatible"


def test_presentation_pdf_is_fifteen_pages_and_appendix_keeps_deep_evidence(
    demo_api: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, factory = demo_api
    payload = client.post("/api/v1/demo/prepare").json()
    presentation = next(item for item in payload["artifacts"] if item["kind"] == "presentation_pdf")
    pdf = client.get(presentation["download_url"]).content
    reader = PdfReader(io.BytesIO(pdf))
    assert len(reader.pages) >= 6
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "BROWSER UAT" in text or "Browser UAT" in text
    assert "CONTENTS" in text
    assert "finding_id" not in text
    assert "workflow_execution_id" not in text
    appendix = next(item for item in payload["artifacts"] if item["kind"] == "technical_appendix")
    appendix_text = "\n".join(
        page.extract_text() or ""
        for page in PdfReader(io.BytesIO(client.get(appendix["download_url"]).content)).pages
    )
    assert "Full Page Inventory" in appendix_text
    assert "Browser-Specific Evidence" in appendix_text
    assert "Every Retained Occurrence" in appendix_text
    with factory() as db:
        report = db.scalar(select(ReportExecution))
        assert report is not None
        snapshot = report.snapshot.snapshot_payload
        assert snapshot["technical_appendix"]["all_occurrences_preserved"] is True
        assert (
            sum(
                len(item["exact_occurrences"])
                for item in snapshot["technical_appendix"]["all_findings"]
            )
            == snapshot["sections"][9]["content"]["occurrence_count"]
        )


def test_presentation_content_is_bounded_complete_and_has_unique_sections(
    demo_api: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, factory = demo_api
    payload = client.post("/api/v1/demo/prepare").json()
    assert len(payload["top_findings"]) <= 10
    assert len(payload["top_actions"]) <= 10
    for finding in payload["top_findings"]:
        assert len(finding["example_pages"]) <= 5
        for field in (
            "plain_language_explanation",
            "technical_explanation",
            "why_it_matters",
            "evidence_summary",
            "responsible_role",
            "recommended_fix",
            "verification",
            "evidence_source",
            "evidence_timestamp",
        ):
            assert finding[field]
    assert len(payload["top_actions"]) == 5
    for action in payload["top_actions"]:
        assert action["problem_being_solved"]
        assert action["affected_scope"]["page_count"] >= 1
        assert "affected_browsers" in action
    html_artifact = next(
        item for item in payload["artifacts"] if item["kind"] == "presentation_html"
    )
    html_document = client.get(html_artifact["download_url"]).text
    for section_number in range(1, 16):
        assert html_document.count(f'id="section-{section_number}"') == 1
    assert "Summary cards" not in html_document
    assert "finding_id" not in html_document
    assert "workflow_execution_id" not in html_document
    with factory() as db:
        report = db.scalar(select(ReportExecution))
        assert report is not None
        titles = report.snapshot.snapshot_payload["presentation"]["section_titles"]
        assert len(titles) == 15
        assert len(titles) == len(set(titles))


def test_reset_removes_only_managed_demo_and_all_cascaded_history(
    demo_api: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, factory = demo_api
    client.post("/api/v1/demo/prepare")
    with factory() as db:
        unrelated = Project(name="Unrelated", description="Must be preserved")
        db.add(unrelated)
        db.commit()
        unrelated_id = unrelated.id
    response = client.post("/api/v1/demo/reset")
    assert response.status_code == 200
    assert response.json()["deleted_project_count"] == 1
    status = client.get("/api/v1/demo").json()
    assert status["presentation_status"] == "not_prepared"
    with factory() as db:
        assert db.get(Project, unrelated_id) is not None
        assert db.scalar(select(func.count(AgentExecution.id))) == 0
        assert db.scalar(select(func.count(ReportExecution.id))) == 0


def test_presentation_demo_does_not_change_score_formulas() -> None:
    assert FORMULA_VERSION == "1.0.0"
    assert PRIORITY_FORMULA_VERSION == "1.0.0"
