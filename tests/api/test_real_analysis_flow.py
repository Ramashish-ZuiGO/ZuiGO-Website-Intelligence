import importlib
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import (
    AgentExecution,
    AnalysisRun,
    DiscoveryRun,
    PageAnalysisRun,
    Project,
    Website,
    WebsitePage,
)
from app.schemas.report_delivery import RealWebsiteAnalysisStartRequest
from app.services.page_selection import DEFAULT_MAX_LIGHTHOUSE_PAGES, select_scheduled_pages
from app.services.priority import PRIORITY_FORMULA_VERSION
from app.services.public_url_safety import (
    PublicURLSafetyError,
    validate_and_normalize_public_url,
    validate_public_redirects,
)
from app.services.report_delivery import (
    _friendly_finding_title,
    _group_detailed_findings,
    _human_timestamp,
)
from app.services.resource_classification import (
    ResourceClassification,
    classify_resource,
)
from app.services.scoring_formula import FORMULA_VERSION
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

report_routes = importlib.import_module("app.api.routes.report_delivery")
workflow_routes = importlib.import_module("app.api.routes.workflow_executions")


def test_default_page_limit_and_deterministic_full_site_selection() -> None:
    request = RealWebsiteAnalysisStartRequest(
        website_url="https://example.com",
        idempotency_key="default-page-limit",
    )
    assert request.maximum_pages is None
    pages = [
        {
            "normalized_url": f"https://example.com/page-{index:02d}",
            "crawl_depth": 0 if index == 0 else 1,
            "page_type": "homepage" if index == 0 else "content",
        }
        for index in range(60)
    ]
    assert len(select_scheduled_pages(pages[:13])) == 13
    sampled = select_scheduled_pages(pages)
    assert len(sampled) == 60
    assert pages[0] in sampled
    assert sampled == select_scheduled_pages(list(reversed(pages)))
    capped = select_scheduled_pages(pages, 10)
    assert len(capped) == 10
    assert pages[0] in capped


def test_repeated_finding_occurrences_are_grouped_without_loss() -> None:
    shared = {
        "finding_code": "missing_alt_text",
        "issue_title": "Missing alternative text",
        "category": "accessibility",
        "scope": "page",
        "severity": "high",
        "finding_id": "first",
        "related_finding_ids": [],
        "evidence_references": [],
    }
    grouped = _group_detailed_findings(
        [
            {
                **shared,
                "exact_occurrences": [
                    {"normalized_url": "https://example.com/a", "selector": "img.hero"}
                ],
            },
            {
                **shared,
                "finding_id": "second",
                "exact_occurrences": [
                    {"normalized_url": "https://example.com/b", "selector": "img.logo"},
                    {"normalized_url": "https://example.com/b", "selector": "img.card"},
                ],
            },
        ]
    )
    assert len(grouped) == 1
    assert grouped[0]["affected_page_count"] == 2
    assert grouped[0]["occurrence_count"] == 3


def test_resource_classification_and_rule_identity_preserve_semantics() -> None:
    html = classify_resource(
        "https://example.com/page",
        content_type="text/html; charset=utf-8",
        eligibility_status="eligible",
    )
    document = classify_resource(
        "https://example.com/download",
        content_type="application/pdf",
        failure_code="unsupported_content_type",
        eligibility_status="eligible",
    )
    image = classify_resource(
        "https://example.com/photo.jpg",
        content_type="image/jpeg",
        failure_code="unsupported_content_type",
        eligibility_status="eligible",
    )
    assert html.classification == ResourceClassification.ELIGIBLE_HTML_PAGE
    assert html.browser_eligible is True
    assert document.classification == ResourceClassification.DOCUMENT_ASSET
    assert image.classification == ResourceClassification.MEDIA_STATIC_ASSET
    assert document.browser_eligible is image.browser_eligible is False

    base = {
        "finding_code": "repeated_issue_pattern",
        "issue_title": "Repeated issue pattern",
        "category": "technical_consistency",
        "scope": "site",
        "severity": "high",
        "related_finding_ids": [],
        "evidence_references": [],
        "exact_occurrences": [
            {
                "normalized_url": "https://example.com/",
                "observed_value": "missing",
            }
        ],
    }
    grouped = _group_detailed_findings(
        [
            {
                **base,
                "finding_id": "csp",
                "rule_signature": "CSP_MISSING",
            },
            {
                **base,
                "finding_id": "hsts",
                "rule_signature": "HSTS_MISSING",
            },
        ]
    )
    assert len(grouped) == 2
    assert (
        _friendly_finding_title(
            "repeated_missing_security_header:content_security_policy",
            "Repeated issue pattern",
        )
        == "Content Security Policy missing"
    )
    assert (
        _friendly_finding_title(
            "duplicate_normalized_internal_target",
            "Repeated issue pattern",
        )
        == "Duplicate normalized link targets"
    )
    assert _human_timestamp("2026-07-29T06:49:00+00:00") == ("29 July 2026, 06:49 AM UTC")


def _resolver(
    _hostname: str,
    port: int,
) -> list[tuple[object, object, object, object, tuple[object, ...]]]:
    return [(None, None, None, None, ("93.184.216.34", port))]


@pytest.fixture
def real_analysis_api(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, sessionmaker[Session], list[tuple[str, ...]]]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    dispatched: list[tuple[str, ...]] = []

    def override_db() -> Iterator[Session]:
        with factory() as db:
            yield db

    def validate(value: str) -> str:
        return validate_and_normalize_public_url(value, _resolver)

    def enqueue(*values: str, workflow_attempt: int) -> str:
        dispatched.append((*values, str(workflow_attempt)))
        return f"real-analysis-task-{len(dispatched)}"

    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(report_routes, "validate_and_normalize_public_url", validate)
    monkeypatch.setattr(report_routes, "enqueue_real_analysis_journey", enqueue)
    monkeypatch.setattr(workflow_routes, "enqueue_real_analysis_journey", enqueue)
    with TestClient(app) as client:
        yield client, factory, dispatched
    app.dependency_overrides.clear()


def test_public_url_normalization_ssrf_and_redirect_protection() -> None:
    assert (
        validate_and_normalize_public_url(
            "Example.COM:443//products///?b=2&a=1#fragment",
            _resolver,
        )
        == "https://example.com/products?b=2&a=1"
    )
    for blocked in (
        "http://localhost",
        "http://127.0.0.1",
        "http://169.254.169.254/latest/meta-data",
        "http://10.0.0.4",
        "http://metadata.google.internal",
        "ftp://example.com",
        "https://example.com/?access_token=secret",
    ):
        with pytest.raises(PublicURLSafetyError):
            validate_and_normalize_public_url(blocked, _resolver)
    assert validate_public_redirects(
        ["http://example.com", "https://example.com/final"],
        _resolver,
    ) == ["http://example.com/", "https://example.com/final"]
    with pytest.raises(PublicURLSafetyError, match="too many"):
        validate_public_redirects(
            ["https://example.com"] * 7,
            _resolver,
        )


def test_real_submission_creates_history_and_prevents_duplicate_dispatch(
    real_analysis_api: tuple[
        TestClient,
        sessionmaker[Session],
        list[tuple[str, ...]],
    ],
) -> None:
    client, factory, dispatched = real_analysis_api
    request = {
        "website_url": "Example.COM:443//products/",
        "idempotency_key": "real-homepage-one",
        "maximum_pages": 12,
        "browser_engines": ["webkit", "chromium", "firefox"],
        "include_mobile": True,
    }
    first = client.post("/api/v1/analysis/start", json=request)
    assert first.status_code == 202, first.text
    payload = first.json()
    assert payload["submitted_url"] == request["website_url"]
    assert payload["normalized_url"] == "https://example.com/products"
    assert payload["reused"] is False
    assert payload["workflow_status"] == "queued"
    repeated = client.post("/api/v1/analysis/start", json=request)
    assert repeated.status_code == 202
    assert repeated.json()["workflow_execution_id"] == payload["workflow_execution_id"]
    assert repeated.json()["reused"] is True
    assert len(dispatched) == 1

    independent = client.post(
        "/api/v1/analysis/start",
        json={**request, "idempotency_key": "real-homepage-two"},
    )
    assert independent.status_code == 202
    assert independent.json()["analysis_run_id"] != payload["analysis_run_id"]
    assert independent.json()["workflow_execution_id"] != payload["workflow_execution_id"]
    assert independent.json()["project_id"] == payload["project_id"]
    assert independent.json()["website_id"] == payload["website_id"]
    assert len(dispatched) == 2

    conflict = client.post(
        "/api/v1/analysis/start",
        json={
            **request,
            "website_url": "different.example",
            "idempotency_key": "real-homepage-one",
        },
    )
    assert conflict.status_code == 409
    with factory() as db:
        assert db.query(Project).count() == 1
        assert db.query(Website).count() == 1
        assert db.query(AnalysisRun).count() == 2
        assert db.query(DiscoveryRun).count() == 2
        assert db.query(AgentExecution).count() == 2
        execution = db.scalar(
            select(AgentExecution).where(
                AgentExecution.execution_id == uuid.UUID(payload["workflow_execution_id"])
            )
        )
        assert execution is not None
        assert execution.structured_input["execute_repository_agent"] is True
        # Standard workflow schedules engineering-signal engines only; firefox
        # is outside the locked customer UAT contract and is not scheduled.
        assert execution.structured_input["browser_engines"] == [
            "chromium",
            "webkit",
        ]
        assert execution.structured_input["maximum_pages"] == 12
        assert execution.status == "pending"
        assert execution.structured_output["journey_status"] == "queued"
        assert execution.provider_version_metadata["dispatch_count"] == 1
        discovery = db.get(DiscoveryRun, uuid.UUID(payload["discovery_run_id"]))
        assert discovery is not None
        assert discovery.configuration["submitted_url"] == request["website_url"]
        assert discovery.configuration["normalized_url"] == payload["normalized_url"]
        assert "max_discovered_urls" not in discovery.configuration
        assert discovery.configuration["max_html_pages"] == 12
        # M15 (docs/REPORT_QUALITY_INITIATIVE.md): was hardcoded to 0, silently
        # disabling real Lighthouse/axe-core (Level 2) coverage in production.
        assert discovery.configuration["max_lighthouse_pages"] == DEFAULT_MAX_LIGHTHOUSE_PAGES

    recent = client.get("/api/v1/analysis/recent?limit=10")
    assert recent.status_code == 200, recent.text
    assert len(recent.json()) == 2
    assert all(item["normalized_url"] == payload["normalized_url"] for item in recent.json())
    progress = client.get(
        f"/api/v1/workflow-executions/{payload['workflow_execution_id']}/progress"
    )
    assert progress.status_code == 200, progress.text
    progress_payload = progress.json()
    assert progress_payload["submitted_website"] == request["website_url"]
    assert {item["agent_id"] for item in progress_payload["agent_states"]} == {
        "discovery_agent",
        "performance_agent",
        "accessibility_agent",
        "site_diagnostics_agent",
        "repository_intelligence_agent",
        "evidence_validation_agent",
        "remediation_agent",
        "report_agent",
    }
    assert (
        next(
            item["status"]
            for item in progress_payload["agent_states"]
            if item["agent_id"] == "repository_intelligence_agent"
        )
        == "not_applicable"
    )
    assert {item["engine"] for item in progress_payload["browser_engine_progress"]["engines"]} == {
        "chromium",
        "webkit",
    }
    assert progress_payload["page_coverage"]["coverage_denominator"] == 0

    with factory() as db:
        execution = db.scalar(
            select(AgentExecution).where(
                AgentExecution.execution_id == uuid.UUID(payload["workflow_execution_id"])
            )
        )
        assert execution is not None
        execution.status = "failed"
        execution.failure_details = {
            "code": "TEST_TRANSIENT_FAILURE",
            "message": "The local fixture stopped.",
            "transient": True,
        }
        db.commit()
    failed_progress = client.get(
        f"/api/v1/workflow-executions/{payload['workflow_execution_id']}/progress"
    )
    assert failed_progress.json()["resume_available"] is True
    resumed = client.post(f"/api/v1/workflow-executions/{payload['workflow_execution_id']}/resume")
    assert resumed.status_code == 202, resumed.text
    assert resumed.json()["attempt"] == 2
    assert len(dispatched) == 3


def test_real_and_prepared_demo_routes_are_explicitly_separate(
    real_analysis_api: tuple[
        TestClient,
        sessionmaker[Session],
        list[tuple[str, ...]],
    ],
) -> None:
    client, _factory, _dispatched = real_analysis_api
    real = client.post(
        "/api/v1/analysis/start",
        json={
            "website_url": "example.com",
            "idempotency_key": "not-a-demo",
            "maximum_pages": 2,
            "browser_engines": ["chromium"],
        },
    )
    assert real.status_code == 202
    assert "demo" not in real.json()["normalized_url"]
    prepared = client.post("/api/v1/demo/prepare")
    assert prepared.status_code == 200
    assert prepared.json()["presentation_status"] == "ready"
    assert FORMULA_VERSION == "1.0.0"
    assert PRIORITY_FORMULA_VERSION == "1.0.0"


def test_progress_counts_use_page_attempts_and_explain_page_limit(
    real_analysis_api: tuple[
        TestClient,
        sessionmaker[Session],
        list[tuple[str, ...]],
    ],
) -> None:
    client, factory, _dispatched = real_analysis_api
    started = client.post(
        "/api/v1/analysis/start",
        json={
            "website_url": "example.com",
            "idempotency_key": "count-invariants",
            "maximum_pages": 13,
            "browser_engines": ["chromium", "firefox", "webkit"],
        },
    ).json()
    now = datetime.now(UTC)
    with factory() as db:
        discovery = db.get(DiscoveryRun, uuid.UUID(started["discovery_run_id"]))
        execution = db.scalar(
            select(AgentExecution).where(
                AgentExecution.execution_id == uuid.UUID(started["workflow_execution_id"])
            )
        )
        assert discovery is not None and execution is not None
        discovery.status = "completed"
        discovery.current_stage = "completed"
        discovery.progress_percent = 100
        discovery.urls_discovered = 52
        discovery.urls_unique = 41
        discovery.urls_eligible = 41
        discovery.completed_at = now
        pages = []
        for index in range(41):
            page = WebsitePage(
                website_id=uuid.UUID(started["website_id"]),
                normalized_url=f"https://example.com/page-{index:02d}",
                original_url=f"https://example.com/page-{index:02d}",
                page_type="content",
                discovery_source="crawl",
                discovery_evidence=[],
                crawl_depth=0 if index == 0 else 1,
                origin_relation="same_origin",
                eligibility_status="eligible",
                last_discovery_run_id=discovery.id,
                first_discovered_at=now,
                last_discovered_at=now,
            )
            db.add(page)
            pages.append(page)
        db.flush()
        selected_pages = select_scheduled_pages(pages, 13)
        for index, page in enumerate(selected_pages):
            status = "completed" if index < 11 else "failed" if index == 11 else "partial"
            db.add(
                PageAnalysisRun(
                    website_page_id=page.id,
                    discovery_run_id=discovery.id,
                    page_analysis_execution_id=uuid.UUID(started["page_analysis_execution_id"]),
                    analysis_level=1,
                    status=status,
                    analysis_started_at=now,
                    analysis_completed_at=now,
                    requested_url=page.normalized_url,
                    final_url=page.normalized_url if status == "completed" else None,
                    http_status_code=200 if status == "completed" else None,
                )
            )
        output = dict(execution.structured_output)
        output.update(
            {
                "journey_stage": "browser_compatibility",
                "journey_status": "running",
                "journey_updated_at": now.isoformat(),
                "failed_stage_id": "multi_agent_analysis",
                "completed_stage_ids": ["setup", "website_discovery", "page_analysis"],
                "browser_compatibility": {
                    "status": "not_started",
                    "eligible_page_count": 3,
                    "engines": [],
                },
            }
        )
        execution.structured_output = output
        execution.status = "running"
        db.commit()

    response = client.get(
        f"/api/v1/workflow-executions/{started['workflow_execution_id']}/progress"
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    coverage = payload["page_coverage"]
    assert coverage == {
        "discovery_status": "completed",
        "discovery_completeness": "complete",
        "discovery_failure_code": None,
        "discovery_failure_message": None,
        "discovery_retry_available": False,
        "discovered_pages": 52,
        "normalized_pages": 41,
        "eligible_pages": 41,
        "scheduled_pages": 13,
        "not_scheduled_pages": 28,
        "visited_pages": 13,
        "successfully_analysed_pages": 11,
        "failed_pages": 1,
        "failed_page_details": [
            {
                "url": "https://example.com/page-38",
                "reason": "The page analysis failed without a safe reason.",
                "reason_code": "PAGE_ANALYSIS_FAILED",
            }
        ],
        "document_assets": 0,
        "media_static_assets": 0,
        "resource_inventory": [],
        "skipped_pages": 0,
        "incomplete_pages": 1,
        "coverage_numerator": 11,
        "coverage_denominator": 41,
        "coverage_percentage": 26.8,
        "analysed_page_coverage_percentage": 26.8,
        "full_site_coverage_percentage": 26.8,
        "full_site_coverage_confidence": "established",
        "discovery_stage_status": "completed",
        "discovery_completeness_message": (
            "Website discovery completed. Full-site coverage was established."
        ),
    }
    assert (
        coverage["successfully_analysed_pages"]
        <= coverage["visited_pages"]
        <= coverage["scheduled_pages"]
        <= coverage["eligible_pages"]
        <= coverage["discovered_pages"]
    )
    assert (
        coverage["failed_pages"]
        + coverage["skipped_pages"]
        + coverage["incomplete_pages"]
        + coverage["successfully_analysed_pages"]
        <= coverage["scheduled_pages"]
    )
    assert payload["progress_percentage"] > 0
    assert payload["failed_stage_id"] is None
    assert payload["browser_engine_progress"]["status"] == "running"
    assert payload["browser_engine_progress"]["eligible_page_count"] == 13
    assert all(
        item["eligible_pages"] == 13 for item in payload["browser_engine_progress"]["engines"]
    )
    assert all(item["tested_pages"] == 0 for item in payload["browser_engine_progress"]["engines"])
    assert payload["active_stage_id"] == "browser_compatibility"
    assert payload["current_stage"] == "browser_compatibility"
    assert (
        next(item for item in payload["stages"] if item["stage_id"] == "browser_compatibility")[
            "status"
        ]
        == "running"
    )
    assert payload["report_generation_available"] is False

    with factory() as db:
        discovery = db.get(DiscoveryRun, uuid.UUID(started["discovery_run_id"]))
        assert discovery is not None
        discovery.status = "partial"
        discovery.failure_code = "SITEMAP_FETCH_FAILED"
        discovery.failure_message = "A sitemap could not be processed after bounded retries."
        db.commit()
    partial = client.get(
        f"/api/v1/workflow-executions/{started['workflow_execution_id']}/progress"
    ).json()
    assert partial["page_coverage"]["discovery_completeness"] == "partial"
    assert partial["page_coverage"]["analysed_page_coverage_percentage"] == 26.8
    assert partial["page_coverage"]["full_site_coverage_percentage"] is None
    assert partial["page_coverage"]["full_site_coverage_confidence"] == "not_established"
    assert partial["page_coverage"]["discovery_retry_available"] is True
    assert partial["retry_available"] is True
    assert partial["resume_available"] is True
    assert {
        "code": "SITEMAP_FETCH_FAILED",
        "message": "A sitemap could not be processed after bounded retries.",
    } in partial["safe_error_summaries"]

    with factory() as db:
        discovery = db.get(DiscoveryRun, uuid.UUID(started["discovery_run_id"]))
        execution = db.scalar(
            select(AgentExecution).where(
                AgentExecution.execution_id == uuid.UUID(started["workflow_execution_id"])
            )
        )
        assert discovery is not None and execution is not None
        discovery.status = "completed"
        discovery.failure_code = None
        discovery.failure_message = None
        output = dict(execution.structured_output)
        output["journey_updated_at"] = (now - timedelta(minutes=20)).isoformat()
        execution.structured_output = output
        db.commit()
    stale = client.get(
        f"/api/v1/workflow-executions/{started['workflow_execution_id']}/progress"
    ).json()
    assert stale["stale"] is True
    assert stale["status"] == "failed"
    assert stale["failed_stage_id"] == "browser_compatibility"
    assert stale["browser_engine_progress"]["status"] == "timed_out"
    assert all(
        item["queued_pages"] == 0 and item["timed_out_pages"] == 13
        for item in stale["browser_engine_progress"]["engines"]
    )
    assert stale["retry_available"] is True
    assert stale["resume_available"] is True
    resumed = client.post(f"/api/v1/workflow-executions/{started['workflow_execution_id']}/resume")
    assert resumed.status_code == 202, resumed.text
    assert resumed.json()["status"] == "pending"
    assert resumed.json()["attempt"] == 2
    with factory() as db:
        execution = db.scalar(
            select(AgentExecution).where(
                AgentExecution.execution_id == uuid.UUID(started["workflow_execution_id"])
            )
        )
        assert execution is not None
        assert execution.structured_output["journey_status"] == "queued"
        assert execution.provider_version_metadata["dispatch_count"] == 2


def test_live_browser_stage_counters_use_persisted_incremental_progress(
    real_analysis_api: tuple[
        TestClient,
        sessionmaker[Session],
        list[tuple[str, ...]],
    ],
) -> None:
    """Liveness regression (Fluid Controls stall): during a live or interrupted
    browser stage, full observation lists are not yet persisted but the
    per-engine incremental counters are. The progress endpoint must report
    those counters instead of a false 0-tested state."""
    client, factory, _dispatched = real_analysis_api
    started = client.post(
        "/api/v1/analysis/start",
        json={
            "website_url": "example.com",
            "idempotency_key": "liveness-counters",
            "browser_engines": ["chromium", "webkit"],
        },
    ).json()
    now = datetime.now(UTC)
    with factory() as db:
        discovery = db.get(DiscoveryRun, uuid.UUID(started["discovery_run_id"]))
        execution = db.scalar(
            select(AgentExecution).where(
                AgentExecution.execution_id == uuid.UUID(started["workflow_execution_id"])
            )
        )
        assert discovery is not None and execution is not None
        discovery.status = "completed"
        discovery.progress_percent = 100
        discovery.completed_at = now
        pages = []
        for index in range(5):
            page = WebsitePage(
                website_id=uuid.UUID(started["website_id"]),
                normalized_url=f"https://example.com/live-{index}",
                original_url=f"https://example.com/live-{index}",
                page_type="content",
                discovery_source="crawl",
                discovery_evidence=[],
                crawl_depth=0 if index == 0 else 1,
                origin_relation="same_origin",
                eligibility_status="eligible",
                last_discovery_run_id=discovery.id,
                first_discovered_at=now,
                last_discovered_at=now,
            )
            db.add(page)
            pages.append(page)
        db.flush()
        for page in pages:
            db.add(
                PageAnalysisRun(
                    website_page_id=page.id,
                    discovery_run_id=discovery.id,
                    page_analysis_execution_id=uuid.UUID(started["page_analysis_execution_id"]),
                    analysis_level=1,
                    status="completed",
                    analysis_started_at=now,
                    analysis_completed_at=now,
                    requested_url=page.normalized_url,
                    final_url=page.normalized_url,
                    http_status_code=200,
                )
            )
        output = dict(execution.structured_output)
        output.update(
            {
                "journey_stage": "browser_compatibility",
                "journey_status": "running",
                "journey_updated_at": now.isoformat(),
                "completed_stage_ids": ["setup", "website_discovery", "page_analysis"],
                "browser_compatibility": {
                    "status": "running",
                    "eligible_page_count": 5,
                    # Incremental counters persisted by the stage progress
                    # callback; no observations yet (stage still running).
                    "engines": [
                        {"engine": "chromium", "attempted_pages": 3, "tested_pages": 3},
                        {"engine": "webkit", "attempted_pages": 2, "tested_pages": 2},
                    ],
                },
            }
        )
        execution.structured_output = output
        execution.status = "running"
        db.commit()

    payload = client.get(
        f"/api/v1/workflow-executions/{started['workflow_execution_id']}/progress"
    ).json()
    engines = {item["engine"]: item for item in payload["browser_engine_progress"]["engines"]}
    assert engines["chromium"]["tested_pages"] == 3
    assert engines["webkit"]["tested_pages"] == 2
    assert engines["chromium"]["availability_status"] == "available"
