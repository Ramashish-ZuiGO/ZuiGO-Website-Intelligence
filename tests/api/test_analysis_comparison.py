import copy
import io
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import (
    AgentExecution,
    AnalysisComparison,
    AnalysisRun,
    Project,
    ReportExecution,
    ReportSnapshot,
    Website,
)
from app.services.agent_platform_registry import AgentRegistry, WorkflowRegistry
from app.services.analysis_comparison import build_comparison_payload
from app.services.priority import PRIORITY_FORMULA_VERSION
from app.services.scoring_formula import FORMULA_VERSION
from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


def finding(
    code: str,
    title: str,
    severity: str,
    url: str,
    *,
    observed: str = "retained observation",
) -> dict:
    return {
        "finding_code": code,
        "issue_title": title,
        "category": "seo",
        "scope": "page",
        "severity": severity,
        "exact_occurrences": [
            {
                "normalized_url": url,
                "selector": "head > title",
                "observed_value": observed,
            }
        ],
        "recommended_remediation": "Correct the page metadata and re-run the analysis.",
        "evidence_limitations": "",
    }


def snapshot(
    *,
    score: int,
    urls: list[str],
    findings: list[dict],
    browser_urls: list[str] | None = None,
    action_titles: list[str] | None = None,
) -> dict:
    browser_pages = browser_urls if browser_urls is not None else urls
    categories = [
        {
            "category_id": category,
            "score": score - index,
            "band": "good",
            "included": True,
        }
        for index, category in enumerate(
            ("performance", "accessibility", "best_practices", "seo", "technical_quality")
        )
    ]
    return {
        "website_name": "Comparison fixture",
        "website_url": "https://comparison.test/",
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "completed",
        "overall_score": score,
        "page_coverage": {
            "total_urls_discovered": len(urls),
            "total_pages_scheduled": len(urls),
            "total_pages_visited": len(urls),
            "successfully_analysed_pages": len(urls),
            "coverage_numerator": len(urls),
            "coverage_denominator": len(urls),
            "coverage_percentage": 100.0 if urls else None,
        },
        "page_inventory": [{"url": url, "analysis_status": "completed"} for url in urls],
        "browser_compatibility": {
            "engines": [
                {"engine": engine, "label": engine.title()}
                for engine in ("chromium", "firefox", "webkit")
            ],
            "matrix": [
                {
                    "page_url": url,
                    "engines": {
                        "chromium": "compatible",
                        "firefox": "compatible",
                        "webkit": "compatible",
                    },
                }
                for url in browser_pages
            ],
        },
        "sections": [
            {
                "section_key": "scores",
                "content": {
                    "overall_score": score,
                    "formula_id": "overall_score",
                    "formula_version": FORMULA_VERSION,
                    "categories": categories,
                },
            },
            {
                "section_key": "page_level_findings",
                "content": {"findings": findings},
            },
            {
                "section_key": "priority_action_plan",
                "content": {
                    "actions": [
                        {
                            "title": title,
                            "priority_score": 70,
                            "status": "recommended",
                            "affected_scope": {"final_url": "https://comparison.test/a"},
                            "verification_method": "Reanalyse the affected page.",
                        }
                        for title in (action_titles or [])
                    ]
                },
            },
        ],
    }


def add_report(
    db: Session,
    project: Project,
    website: Website,
    run: AnalysisRun,
    payload: dict,
    suffix: str,
) -> None:
    report = ReportExecution(
        report_id=uuid.uuid4(),
        project_id=project.id,
        website_id=website.id,
        analysis_run_id=run.id,
        report_type="final_analysis",
        report_version="1.0.0",
        template_id="website_analysis",
        template_version="1.0.0",
        input_fingerprint=suffix * 64,
        idempotency_key=f"report-{suffix}",
        status="completed",
        evidence_coverage_numerator=len(payload["page_inventory"]),
        evidence_coverage_denominator=len(payload["page_inventory"]),
        evidence_coverage_percentage=100,
        unavailable_sections=[],
        provider_version_metadata={},
        failure_details={},
        partial_completion_details={},
        completed_at=datetime.now(UTC),
    )
    db.add(report)
    db.flush()
    db.add(
        ReportSnapshot(
            snapshot_id=uuid.uuid4(),
            report_execution_id=report.id,
            snapshot_payload=payload,
            evidence_references=[{"source": "retained_test_evidence"}],
        )
    )


@pytest.fixture
def comparison_api(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, sessionmaker[Session], uuid.UUID, uuid.UUID, uuid.UUID, list[str]]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        project = Project(name="Comparison project")
        website = Website(
            project=project,
            url="https://comparison.test/",
            name="Comparison fixture",
            profile_id="global_general",
        )
        baseline = AnalysisRun(
            website=website,
            status="completed",
            progress_percent=100,
            profile_id="global_general",
            profile_version="1.0.0",
            completed_at=datetime.now(UTC),
        )
        current = AnalysisRun(
            website=website,
            baseline_analysis_run_id=None,
            status="completed",
            progress_percent=100,
            profile_id="global_general",
            profile_version="1.0.0",
            completed_at=datetime.now(UTC),
        )
        db.add_all([project, website, baseline, current])
        db.flush()
        current.baseline_analysis_run_id = baseline.id
        baseline_payload = snapshot(
            score=70,
            urls=[
                "https://comparison.test/a/",
                "https://comparison.test/b",
                "https://comparison.test/c",
            ],
            findings=[
                finding("missing_title", "Missing title", "high", "https://comparison.test/a/"),
                finding(
                    "duplicate_title",
                    "Duplicate title",
                    "high",
                    "https://comparison.test/b",
                ),
            ],
            action_titles=["Missing title", "Duplicate title"],
        )
        current_payload = snapshot(
            score=82,
            urls=[
                "https://comparison.test/a",
                "https://comparison.test/b/",
                "https://comparison.test/c",
            ],
            findings=[
                finding(
                    "duplicate_title",
                    "Duplicate title",
                    "low",
                    "https://comparison.test/b/",
                ),
                finding("missing_h1", "Missing heading", "medium", "https://comparison.test/c"),
            ],
            action_titles=["Duplicate title", "Missing heading"],
        )
        add_report(db, project, website, baseline, baseline_payload, "a")
        add_report(db, project, website, current, current_payload, "b")
        workflow = AgentExecution(
            execution_id=uuid.uuid4(),
            workflow_id="full_website_analysis",
            workflow_version="1.0.0",
            project_id=project.id,
            analysis_run_id=baseline.id,
            input_fingerprint="w" * 64,
            idempotency_key="baseline-workflow",
            status="completed",
            structured_input={
                "website_id": str(website.id),
                "analysis_run_id": str(baseline.id),
                "maximum_pages": 3,
                "browser_engines": ["chromium", "firefox", "webkit"],
                "include_mobile": True,
                "max_concurrency": 2,
            },
            structured_output={
                "completed_agent_ids": [agent.agent_id for agent in AgentRegistry.get_all()]
            },
            evidence_references=[],
            provider_version_metadata={},
            failure_details={},
            partial_completion_details={},
            completed_at=datetime.now(UTC),
        )
        db.add(workflow)
        db.commit()
        website_id = website.id
        baseline_id = baseline.id
        current_id = current.id

    dispatched: list[str] = []

    def enqueue(*args: str, **kwargs: int) -> str:
        dispatched.append("|".join(args))
        return "comparison-task"

    monkeypatch.setattr(
        "app.api.routes.analysis_comparison.enqueue_real_analysis_journey",
        enqueue,
    )

    def override_db() -> Iterator[Session]:
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    try:
        yield TestClient(app), factory, baseline_id, current_id, website_id, dispatched
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_reanalysis_creates_independent_linked_run_without_mutating_baseline(
    comparison_api,
) -> None:
    client, factory, baseline_id, _, _, dispatched = comparison_api
    with factory() as db:
        baseline_before = copy.deepcopy(db.get(AnalysisRun, baseline_id).__dict__)
    request = {
        "confirmed": True,
        "idempotency_key": "repeat-comparison-analysis",
        "maximum_pages": 5,
        "browser_engines": ["webkit", "chromium"],
        "include_mobile": False,
        "max_concurrency": 2,
    }
    settings = client.get(f"/api/v1/analysis-runs/{baseline_id}/reanalysis-settings")
    assert settings.status_code == 200
    assert settings.json()["maximum_pages"] == 3
    assert settings.json()["browser_engines"] == [
        "chromium",
        "firefox",
        "webkit",
    ]
    first = client.post(f"/api/v1/analysis-runs/{baseline_id}/reanalyse", json=request)
    second = client.post(f"/api/v1/analysis-runs/{baseline_id}/reanalyse", json=request)
    independent_request = {**request, "idempotency_key": "independent-reanalysis"}
    independent = client.post(
        f"/api/v1/analysis-runs/{baseline_id}/reanalyse",
        json=independent_request,
    )
    conflict = client.post(
        f"/api/v1/analysis-runs/{baseline_id}/reanalyse",
        json={**request, "maximum_pages": 6},
    )
    assert first.status_code == 202
    assert second.status_code == 202
    assert independent.status_code == 202
    assert conflict.status_code == 409
    assert first.json()["analysis_run_id"] == second.json()["analysis_run_id"]
    assert first.json()["analysis_run_id"] != independent.json()["analysis_run_id"]
    assert first.json()["reused"] is False
    assert second.json()["reused"] is True
    assert len(dispatched) == 2
    with factory() as db:
        baseline_after = db.get(AnalysisRun, baseline_id)
        new_run = db.get(AnalysisRun, uuid.UUID(first.json()["analysis_run_id"]))
        assert new_run is not None
        assert new_run.id != baseline_id
        assert new_run.baseline_analysis_run_id == baseline_id
        for key in (
            "status",
            "progress_percent",
            "completed_at",
            "profile_id",
            "profile_version",
        ):
            assert getattr(baseline_after, key) == baseline_before[key]
        execution = db.scalar(
            select(AgentExecution).where(AgentExecution.analysis_run_id == new_run.id)
        )
        assert execution.workflow_id == "full_website_analysis"
        assert execution.structured_input["baseline_analysis_run_id"] == str(baseline_id)
        workflow = WorkflowRegistry.get(execution.workflow_id)
        assert workflow is not None
        registered_agents = {agent.agent_id for agent in AgentRegistry.get_all()}
        assert {node.agent_id for node in workflow.nodes} == registered_agents
        assert len(registered_agents) == 8


def test_comparison_classifies_scores_findings_actions_and_exports(
    comparison_api,
) -> None:
    client, factory, baseline_id, current_id, website_id, _ = comparison_api
    response = client.post(
        f"/api/v1/analysis-runs/{current_id}/comparisons/{baseline_id}/generate",
        json={"idempotency_key": "comparison-1"},
    )
    assert response.status_code == 201
    body = response.json()
    reused = client.post(
        f"/api/v1/analysis-runs/{current_id}/comparisons/{baseline_id}/generate",
        json={"idempotency_key": "comparison-1"},
    )
    independent = client.post(
        f"/api/v1/analysis-runs/{current_id}/comparisons/{baseline_id}/generate",
        json={"idempotency_key": "comparison-2"},
    )
    assert reused.status_code == 200
    assert independent.status_code == 201
    assert reused.json()["comparison_id"] == body["comparison_id"]
    assert independent.json()["comparison_id"] != body["comparison_id"]
    payload = body["result_payload"]
    assert payload["scores"]["overall_delta"] == 12
    assert payload["scores"]["direction"] == "Improved"
    assert len(payload["scores"]["categories"]) == 5
    assert [item["category"] for item in payload["scores"]["categories"]] == [
        "performance",
        "accessibility",
        "best practices",
        "seo",
        "technical quality",
    ]
    assert [item["title"] for item in payload["findings"]["resolved"]] == ["Missing title"]
    assert [item["title"] for item in payload["findings"]["persistent"]] == ["Duplicate title"]
    assert [item["title"] for item in payload["findings"]["new"]] == ["Missing heading"]
    assert payload["findings"]["changed_severity"][0]["direction"] == "Improved"
    assert payload["findings"]["resolved"][0]["affected_urls"] == ["https://comparison.test/a"]
    action_states = {item["title"]: item["classification"] for item in payload["action_plan"]}
    assert action_states["Missing title"] == "Completed or likely resolved through evidence"
    assert action_states["Duplicate title"] == "Partially improved"
    assert action_states["Missing heading"] == "New action"
    assert {item["format"] for item in body["artifacts"]} == {"html", "pdf", "json"}
    comparison_id = body["comparison_id"]
    html_response = client.get(f"/api/v1/analysis-comparisons/{comparison_id}/download/html")
    pdf_response = client.get(f"/api/v1/analysis-comparisons/{comparison_id}/download/pdf")
    json_response = client.get(f"/api/v1/analysis-comparisons/{comparison_id}/download/json")
    assert html_response.status_code == pdf_response.status_code == json_response.status_code == 200
    assert b"<main>" in html_response.content
    assert "prepared demo" not in html_response.text.casefold()
    assert 8 <= len(PdfReader(io.BytesIO(pdf_response.content)).pages) <= 15
    assert json_response.json()["scores"]["formula_version_after"] == FORMULA_VERSION
    history = client.get(f"/api/v1/websites/{website_id}/analysis-comparisons/history").json()
    assert history["total"] == 2
    with factory() as db:
        assert db.scalar(select(AnalysisComparison)) is not None


def test_incomplete_page_and_browser_coverage_prevents_false_improvement() -> None:
    old = snapshot(
        score=70,
        urls=["https://comparison.test/a", "https://comparison.test/b"],
        findings=[finding("missing_title", "Missing title", "high", "https://comparison.test/a")],
    )
    new = snapshot(
        score=75,
        urls=["https://comparison.test/b"],
        findings=[],
        browser_urls=["https://comparison.test/b"],
    )
    payload, limitations = build_comparison_payload(old, new)
    assert payload["findings"]["resolved"] == []
    assert payload["findings"]["inconclusive"][0]["title"] == "Missing title"
    assert payload["coverage"]["direction"] == "Inconclusive"
    for engine in payload["browser_compatibility"]["engines"]:
        assert engine["direction"] == "Inconclusive"
        assert engine["resolved_failures"] == []
    assert any("Page sets differ" in item for item in limitations)

    reduced_elsewhere = snapshot(
        score=75,
        urls=["https://comparison.test/a"],
        findings=[],
        browser_urls=[],
    )
    browser_finding = finding(
        "browser_render_failure",
        "Browser render failure",
        "high",
        "https://comparison.test/a",
    )
    browser_finding["affected_browser_engines"] = ["chromium"]
    old_with_browser = snapshot(
        score=70,
        urls=["https://comparison.test/a", "https://comparison.test/b"],
        findings=[browser_finding],
    )
    reduced_payload, _ = build_comparison_payload(old_with_browser, reduced_elsewhere)
    assert reduced_payload["findings"]["resolved"] == []
    assert reduced_payload["findings"]["inconclusive"][0]["title"] == "Browser render failure"


def test_unrelated_websites_cannot_be_compared(comparison_api) -> None:
    client, factory, baseline_id, current_id, _, _ = comparison_api
    with factory() as db:
        project = db.scalar(select(Project))
        other_website = Website(
            project_id=project.id,
            url="https://other.test/",
            name="Other",
            profile_id="global_general",
        )
        other = AnalysisRun(
            website=other_website,
            status="completed",
            progress_percent=100,
            profile_id="global_general",
            profile_version="1.0.0",
        )
        db.add_all([other_website, other])
        db.commit()
        other_id = other.id
    response = client.post(
        f"/api/v1/analysis-runs/{other_id}/comparisons/{baseline_id}/generate",
        json={"idempotency_key": "wrong-scope"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "COMPARISON_SCOPE_MISMATCH"
    assert current_id != other_id


def test_comparison_models_constraints_and_formula_versions_are_unchanged() -> None:
    analysis_run = Base.metadata.tables["analysis_runs"]
    comparisons = Base.metadata.tables["analysis_comparisons"]
    artifacts = Base.metadata.tables["analysis_comparison_artifacts"]
    assert analysis_run.c.baseline_analysis_run_id.foreign_keys
    assert len(comparisons.foreign_keys) == 4
    assert len(artifacts.foreign_keys) == 1
    assert {constraint.name for constraint in comparisons.constraints} >= {
        "uq_analysis_comparisons_pair_idempotency",
        "ck_analysis_comparisons_distinct_runs",
    }
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    assert {item["name"] for item in inspector.get_indexes("analysis_comparisons")} >= {
        "ix_analysis_comparisons_website_created",
        "ix_analysis_comparisons_current_created",
        "ix_analysis_comparisons_baseline_created",
    }
    assert FORMULA_VERSION == "1.0.0"
    assert PRIORITY_FORMULA_VERSION == "1.0.0"
    engine.dispose()
