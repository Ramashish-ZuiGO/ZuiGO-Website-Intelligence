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
    AnalysisFinding,
    AnalysisResult,
    AnalysisRun,
    AnalysisScore,
    DiscoveryRun,
    FindingSeverity,
    FindingSource,
    PageAnalysisRun,
    Project,
    ReportExecution,
    SiteDiagnosticExecution,
    SiteDiagnosticFinding,
    SiteDiagnosticOccurrence,
    Website,
    WebsitePage,
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
        finding = AnalysisFinding(
            analysis_run_id=run.id,
            finding_code="render_blocking_demo",
            category="performance",
            title="Render-blocking resource",
            description="A retained stylesheet delayed first render.",
            severity=FindingSeverity.HIGH,
            affected_url=website.url,
            evidence={
                "selector": "head > link[rel=stylesheet]",
                "resource_url": "https://report.test/app.css",
                "observed_value": "blocking",
                "expected_value": "non-blocking where safe",
                "technical_impact": "The resource delays the retained laboratory render path.",
                "likely_cause": "The stylesheet is loaded synchronously in the document head.",
            },
            source=FindingSource.LIGHTHOUSE,
            confidence_percent=90,
        )
        diagnostic = SiteDiagnosticExecution(
            website_id=website.id,
            analysis_run_id=run.id,
            workflow_id="site_diagnostics",
            workflow_version="1.0.0",
            selected_profile_id="global_general",
            selected_profile_version="1.0.0",
            input_fingerprint="d" * 64,
            evidence_fingerprint="e" * 64,
            idempotency_key="report-diagnostics",
            diagnostic_engine_version="1.0.0",
            rule_registry_version="1.0.0",
            status="completed",
            total_page_count=51,
            processed_page_count=51,
            failed_page_count=0,
            evidence_coverage_numerator=51,
            evidence_coverage_denominator=51,
            evidence_coverage_ratio=1.0,
            error_metadata={},
            partial_completion_metadata={},
            completed_at=datetime.now(UTC),
        )
        db.add_all([result, legacy_score, workflow, finding, diagnostic])
        db.flush()
        diagnostic_finding = SiteDiagnosticFinding(
            execution_id=diagnostic.id,
            rule_id="duplicate_title_group",
            rule_version="1.0.0",
            category="metadata_content",
            severity="medium",
            confidence="high",
            scope="template",
            title="Repeated title template",
            description="The same normalized title occurs on 51 retained pages.",
            why_it_matters="Repeated titles reduce page-level metadata specificity.",
            affected_page_count=51,
            total_eligible_page_count=51,
            occurrence_count=51,
            affected_ratio=1.0,
            evidence_summary="All 51 normalized title values are identical.",
            evidence_references=[],
            remediation_guidance="Provide a page-specific title in the shared template.",
            responsible_role="Content engineering",
            verification_guidance="Re-run title grouping and verify every page title.",
        )
        db.add(diagnostic_finding)
        db.flush()
        db.add_all(
            [
                SiteDiagnosticOccurrence(
                    finding_id=diagnostic_finding.id,
                    normalized_url=f"https://report.test/products/{index}",
                    evidence_reference=f"demo:title:{index}",
                    occurrence_fingerprint=f"{index:064x}",
                    element_selector="head > title",
                    location="document head",
                    context={"status_code": 200, "page_title": "Repeated"},
                    observed_value="Repeated",
                    expected_value=f"Product {index}",
                    supporting_evidence={},
                )
                for index in range(51)
            ]
        )
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
        assert len(first.sections) == 16
        assert [item.section_key for item in first.sections] == [
            item
            for item in (
                "executive_summary",
                "scores",
                "performance",
                "accessibility",
                "site_diagnostics",
                "internal_link_graph",
                "canonical_indexability",
                "security_technical",
                "content_seo",
                "page_level_findings",
                "repeated_template_problems",
                "priority_action_plan",
                "remediation",
                "coverage_confidence",
                "multi_agent_execution",
                "methodology_limitations",
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


def test_partial_discovery_never_claims_full_site_coverage(
    report_api: tuple[
        TestClient,
        sessionmaker[Session],
        uuid.UUID,
        uuid.UUID,
        uuid.UUID,
        list[tuple[str, str, int]],
    ],
) -> None:
    _client, factory, _project_id, website_id, run_id, _dispatched = report_api
    with factory() as db:
        workflow = db.scalar(select(AgentExecution).where(AgentExecution.analysis_run_id == run_id))
        assert workflow is not None
        now = datetime.now(UTC)
        discovery = DiscoveryRun(
            website_id=website_id,
            status="partial",
            progress_percent=100,
            current_stage="completed",
            urls_discovered=1,
            urls_unique=1,
            urls_eligible=1,
            failure_code="SITEMAP_FETCH_FAILED",
            failure_message="A sitemap could not be processed after bounded retries.",
            completed_at=now,
        )
        db.add(discovery)
        db.flush()
        page = WebsitePage(
            website_id=website_id,
            normalized_url="https://report.test/",
            original_url="https://report.test/",
            final_url="https://report.test/",
            page_type="homepage",
            discovery_source="submitted_url",
            discovery_evidence=[{"source": "submitted_url"}],
            crawl_depth=0,
            origin_relation="same_origin",
            robots_status="allowed",
            eligibility_status="eligible",
            last_discovery_run_id=discovery.id,
            first_discovered_at=now,
            last_discovered_at=now,
        )
        page_execution_id = uuid.uuid4()
        page_run = PageAnalysisRun(
            website_page=page,
            discovery_run_id=discovery.id,
            page_analysis_execution_id=page_execution_id,
            analysis_level=1,
            status="completed",
            analysis_started_at=now,
            analysis_completed_at=now,
            requested_url=page.normalized_url,
            final_url=page.normalized_url,
            http_status_code=200,
        )
        workflow.structured_input = {
            **workflow.structured_input,
            "discovery_run_id": str(discovery.id),
            "page_analysis_execution_id": str(page_execution_id),
        }
        db.add_all([page, page_run])
        db.commit()

        generated, created = generate_report(
            db,
            run_id,
            idempotency_key="partial-discovery-report",
        )

        assert created is True
        assert generated.status == "partial"
        assert generated.snapshot is not None
        coverage = generated.snapshot.snapshot_payload["page_coverage"]
        assert coverage["discovery_completeness"] == "partial"
        assert coverage["coverage_numerator"] == 1
        assert coverage["coverage_denominator"] == 1
        assert coverage["analysed_page_coverage_percentage"] == 100.0
        assert coverage["full_site_coverage_percentage"] is None
        assert coverage["full_site_coverage_confidence"] == "not_established"
        executive = next(
            item
            for item in generated.snapshot.snapshot_payload["sections"]
            if item["section_key"] == "executive_summary"
        )
        assert any(
            "full-site coverage is not established" in item
            for item in executive["content"]["important_limitations"]
        )


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
    assert json_payload["schema_version"] == "1.1.0"
    assert len(json_payload["sections"]) == 16
    repeated = _generate_completed_report(factory, run_id)
    assert [item.checksum_sha256 for item in repeated.artifacts] == [
        item.checksum_sha256 for item in report.artifacts
    ]


def test_detailed_finding_contract_occurrences_attribution_and_links(
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
    report = _generate_completed_report(factory, run_id, key="detailed-report")
    sections = {section.section_key: section.content for section in report.sections}
    findings = sections["page_level_findings"]["findings"]
    finding = next(item for item in findings if item["finding_code"] == "render_blocking_demo")
    assert {
        "finding_id",
        "issue_title",
        "plain_language_explanation",
        "technical_explanation",
        "category",
        "severity",
        "confidence",
        "affected_pages",
        "exact_occurrences",
        "evidence_references",
        "evidence_source",
        "detecting_agent",
        "validating_agent",
        "likely_cause",
        "technical_impact",
        "business_impact",
        "recommended_remediation",
        "responsible_role",
        "estimated_effort_band",
        "verification_procedure",
        "related_finding_ids",
        "evidence_limitations",
        "evidence_state",
        "scope",
    } <= set(finding)
    assert finding["exact_occurrences"][0]["normalized_url"] == "https://report.test/"
    assert finding["exact_occurrences"][0]["final_url"] == "https://report.test/"
    assert finding["exact_occurrences"][0]["collection_status"] != "Unavailable"
    assert finding["exact_occurrences"][0]["selector"] == "head > link[rel=stylesheet]"
    assert finding["exact_occurrences"][0]["analysis_provider"] == "lighthouse"
    assert finding["business_impact"].startswith("No quantified business impact")
    assert finding["detecting_agent"] == "performance_agent"
    assert finding["validating_agent"] == "evidence_validation_agent"
    diagnostic_finding = next(
        item for item in findings if item["finding_code"] == "duplicate_title_group"
    )
    assert diagnostic_finding["affected_page_count"] == 51
    assert diagnostic_finding["occurrence_count"] == 51
    assert len(diagnostic_finding["exact_occurrences"]) == 51
    assert len(diagnostic_finding["affected_pages"]) == 51
    assert all("agent_attribution" in content for content in sections.values())
    assert sections["multi_agent_execution"]["agent_count"] == 8
    assert {item["agent_id"] for item in sections["multi_agent_execution"]["agents"]} == {
        "discovery_agent",
        "performance_agent",
        "accessibility_agent",
        "site_diagnostics_agent",
        "repository_intelligence_agent",
        "evidence_validation_agent",
        "remediation_agent",
        "report_agent",
    }
    repository_agent = next(
        item
        for item in sections["multi_agent_execution"]["agents"]
        if item["agent_id"] == "repository_intelligence_agent"
    )
    assert repository_agent["status"] == "not_applicable"
    assert repository_agent["status_explanation"] == ("Not applicable — no repository connected")
    score_links = {
        finding_id
        for category in sections["scores"]["categories"]
        for finding_id in category["related_finding_ids"]
    }
    assert finding["finding_id"] in score_links


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
    assert created.status_code == 201, created.text
    assert 0 <= created.json()["confidence_percent"] < 100
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
    for artifact_format in (
        "presentation_pdf",
        "technical_appendix",
        "page_inventory",
    ):
        download = client.get(f"/api/v1/reports/{report_id}/download/{artifact_format}")
        assert download.status_code == 200, download.text
        assert download.headers["content-disposition"].startswith("attachment; filename=")
        assert hashlib.sha256(download.content).hexdigest() == download.headers["x-content-sha256"]
    inventory = client.get(f"/api/v1/reports/{report_id}/download/page_inventory")
    assert isinstance(inventory.json(), list)
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
