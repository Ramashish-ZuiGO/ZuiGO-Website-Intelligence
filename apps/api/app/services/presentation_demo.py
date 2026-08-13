import copy
import hashlib
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.agent_platform import AgentExecution, AgentRun
from app.models.analysis_result import AnalysisResult
from app.models.analysis_run import AnalysisRun, AnalysisStatus
from app.models.analysis_score import AnalysisScore
from app.models.project import Project
from app.models.report_delivery import (
    ReportArtifact,
    ReportExecution,
    ReportSection,
    ReportSnapshot,
)
from app.models.website import Website
from app.services.agent_platform_registry import AgentRegistry
from app.services.presentation_exports import (
    FRIENDLY_AGENT_DETAILS,
    enrich_presentation_snapshot,
    render_demo_export,
)
from app.services.report_delivery import (
    REPORT_VERSION,
    TEMPLATE_ID,
    TEMPLATE_VERSION,
    fingerprint,
    render_additional_report_artifact,
)
from app.services.report_demo import DEMO_GENERATED_AT, build_demonstration_snapshot

DEMO_NAMESPACE = uuid.UUID("10000000-0000-4000-8000-000000000030")
DEMO_PROJECT_NAME = "ZuiGO Prepared Presentation"
DEMO_PROJECT_DESCRIPTION = (
    "[managed:task-030-presentation-demo:v1] Deterministic local presentation evidence."
)
DEMO_WEBSITE_NAME = "ZuiGO Demo Website"
DEMO_WEBSITE_URL = "https://demo.local/"
DEMO_PROFILE_ID = "global_general"
DEMO_PROFILE_VERSION = "1.0.0"
DEMO_WORKFLOW_ID = "full_website_analysis"
DEMO_WORKFLOW_VERSION = "1.0.0"
PREPARED_IDEMPOTENCY_KEY = "task-030-presentation-rescue-v2"
DEMO_TIMESTAMP = datetime.fromisoformat(DEMO_GENERATED_AT)

AGENT_CONTRIBUTIONS = {
    "discovery_agent": "Prepared the bounded four-page local inventory.",
    "performance_agent": "Retained laboratory and unavailable field-evidence states.",
    "accessibility_agent": "Detected automated evidence and kept manual-review limits.",
    "site_diagnostics_agent": "Grouped deterministic site-wide metadata patterns.",
    "evidence_validation_agent": "Validated provenance, coverage, and unsupported claims.",
    "repository_intelligence_agent": "Represented the configured local repository mapping.",
    "remediation_agent": "Produced evidence-linked remediation and verification guidance.",
    "report_agent": "Assembled the versioned report and three deterministic exports.",
}

STAGE_DEFINITIONS = (
    ("discovery", "Discovery", ("discovery_agent",), False),
    (
        "parallel_analysis",
        "Performance, accessibility, and site diagnostics",
        ("performance_agent", "accessibility_agent", "site_diagnostics_agent"),
        True,
    ),
    ("evidence_validation", "Evidence validation", ("evidence_validation_agent",), False),
    (
        "repository_intelligence",
        "Repository intelligence",
        ("repository_intelligence_agent",),
        False,
    ),
    ("remediation", "Remediation", ("remediation_agent",), False),
    ("report", "Report", ("report_agent",), False),
)


def _uuid(label: str) -> uuid.UUID:
    return uuid.uuid5(DEMO_NAMESPACE, label)


def _prepared_project(db: Session) -> Project | None:
    return db.scalar(
        select(Project).where(
            Project.name == DEMO_PROJECT_NAME,
            Project.description == DEMO_PROJECT_DESCRIPTION,
        )
    )


def _ensure_project_evidence(db: Session) -> tuple[Project, Website, AnalysisRun]:
    project = _prepared_project(db)
    if project is None:
        project = Project(
            id=_uuid("project"),
            name=DEMO_PROJECT_NAME,
            description=DEMO_PROJECT_DESCRIPTION,
        )
        db.add(project)
        db.flush()
    website = db.scalar(
        select(Website).where(
            Website.project_id == project.id,
            Website.url == DEMO_WEBSITE_URL,
        )
    )
    if website is None:
        website = Website(
            id=_uuid("website"),
            project_id=project.id,
            url=DEMO_WEBSITE_URL,
            name=DEMO_WEBSITE_NAME,
            profile_id=DEMO_PROFILE_ID,
        )
        db.add(website)
        db.flush()
    run = db.get(AnalysisRun, _uuid("analysis-run"))
    if run is None:
        run = AnalysisRun(
            id=_uuid("analysis-run"),
            website_id=website.id,
            status=AnalysisStatus.COMPLETED,
            progress_percent=100,
            current_step="Prepared deterministic report",
            profile_id=DEMO_PROFILE_ID,
            profile_version=DEMO_PROFILE_VERSION,
            started_at=DEMO_TIMESTAMP,
            completed_at=DEMO_TIMESTAMP,
        )
        db.add(run)
        db.flush()
        db.add(
            AnalysisResult(
                id=_uuid("analysis-result"),
                analysis_run_id=run.id,
                requested_url=DEMO_WEBSITE_URL,
                final_url=DEMO_WEBSITE_URL,
                http_status_code=200,
                page_title="ZuiGO deterministic demonstration",
                meta_description="Synthetic local evidence for presentation mode.",
                lighthouse_version="12.0.0-demo",
                user_agent="ZuiGO deterministic local fixture",
                analysis_started_at=DEMO_TIMESTAMP,
                analysis_completed_at=DEMO_TIMESTAMP,
                raw_lighthouse_data={
                    "source": "local_synthetic",
                    "performance_score": 68,
                    "field_evidence": "unavailable",
                },
                raw_playwright_data={
                    "source": "local_synthetic",
                    "page_count": 4,
                    "public_network_used": False,
                },
            )
        )
        db.add(
            AnalysisScore(
                id=_uuid("analysis-score"),
                analysis_run_id=run.id,
                formula_version="1.0.0",
                overall_score=76,
                performance_score=68,
                accessibility_score=74,
                best_practices_score=78,
                seo_score=91,
                technical_quality_score=73,
                confidence_percent=88,
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
                deductions=[],
                calculation_details={
                    "source": "deterministic_local_fixture",
                    "formula_unchanged": True,
                },
            )
        )
        db.flush()
    return project, website, run


def _execution_for_key(
    db: Session,
    project: Project,
    run: AnalysisRun,
    *,
    idempotency_key: str,
    failed: bool,
) -> tuple[AgentExecution, bool]:
    existing = db.scalar(
        select(AgentExecution)
        .options(selectinload(AgentExecution.runs))
        .where(
            AgentExecution.project_id == project.id,
            AgentExecution.workflow_id == DEMO_WORKFLOW_ID,
            AgentExecution.workflow_version == DEMO_WORKFLOW_VERSION,
            AgentExecution.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        return existing, False
    input_payload = {
        "website_url": DEMO_WEBSITE_URL,
        "fixture_version": "1.0.0",
        "mode": "simulated_failure" if failed else "prepared_local_execution",
    }
    execution_status = "failed" if failed else "completed"
    execution = AgentExecution(
        id=uuid.uuid4(),
        execution_id=uuid.uuid4(),
        workflow_id=DEMO_WORKFLOW_ID,
        workflow_version=DEMO_WORKFLOW_VERSION,
        project_id=project.id,
        analysis_run_id=run.id,
        input_fingerprint=fingerprint(input_payload),
        idempotency_key=idempotency_key,
        status=execution_status,
        attempt=1,
        structured_input=input_payload,
        structured_output={
            "presentation_fixture": True,
            "public_network_used": False,
            "report_generation_requested": not failed,
        },
        evidence_references=[
            {
                "evidence_type": "local_demo_fixture",
                "evidence_id": "task-030-v1",
                "source": "local_synthetic",
            }
        ],
        provider_version_metadata={
            "execution_mode": "deterministic_local",
            "llm_provider": "unavailable",
        },
        token_total=0,
        cost_total_usd=0.0,
        failure_details=(
            {
                "code": "DEMO_LIVE_EXECUTION_FAILED",
                "message": "The simulated live demo execution did not complete.",
            }
            if failed
            else {}
        ),
        partial_completion_details={},
        started_at=DEMO_TIMESTAMP,
        completed_at=DEMO_TIMESTAMP,
    )
    db.add(execution)
    db.flush()
    agent_run_ids = {definition.agent_id: uuid.uuid4() for definition in AgentRegistry.get_all()}
    for definition in AgentRegistry.get_all():
        if not failed:
            status = "completed"
        elif definition.agent_id == "discovery_agent":
            status = "completed"
        elif definition.agent_id == "performance_agent":
            status = "failed"
        else:
            status = "unavailable"
        db.add(
            AgentRun(
                agent_run_id=agent_run_ids[definition.agent_id],
                execution_id=execution.id,
                agent_id=definition.agent_id,
                agent_version=definition.version,
                dependency_agent_run_ids=[
                    str(agent_run_ids[dependency]) for dependency in definition.dependency_agent_ids
                ],
                input_fingerprint=fingerprint(
                    {
                        "execution_id": str(execution.execution_id),
                        "agent_id": definition.agent_id,
                    }
                ),
                idempotency_key=f"{idempotency_key}:{definition.agent_id}",
                status=status,
                attempt=1,
                structured_input={"fixture_version": "1.0.0"},
                structured_output={
                    "contribution": AGENT_CONTRIBUTIONS[definition.agent_id],
                    "evidence_state": (
                        "available"
                        if status == "completed"
                        else "failed"
                        if status == "failed"
                        else "unavailable"
                    ),
                },
                tool_activity_summary=[
                    {
                        "tool_id": tool_id,
                        "status": (
                            "unavailable"
                            if tool_id in {"approved_llm_completion", "crux_field_evidence"}
                            else "fixture_evidence"
                        ),
                    }
                    for tool_id in definition.allowed_tool_ids
                ],
                evidence_references=[
                    {
                        "evidence_type": "local_demo_fixture",
                        "evidence_id": definition.agent_id,
                        "source": "local_synthetic",
                    }
                ],
                provider_version_metadata={"provider": "deterministic_local_fixture"},
                token_total=0,
                cost_total_usd=0.0,
                failure_details=(
                    {
                        "code": "DEMO_AGENT_FAILED",
                        "message": "Synthetic failure used to verify fallback behavior.",
                    }
                    if status == "failed"
                    else {}
                ),
                partial_completion_details=(
                    {"reason": "Prerequisite execution did not complete."}
                    if status == "unavailable"
                    else {}
                ),
                started_at=DEMO_TIMESTAMP,
                completed_at=DEMO_TIMESTAMP,
            )
        )
    db.flush()
    db.refresh(execution)
    return execution, True


def _persist_report(
    db: Session,
    project: Project,
    website: Website,
    run: AnalysisRun,
    execution: AgentExecution,
    *,
    idempotency_key: str,
    report_type: str,
) -> ReportExecution:
    existing = db.scalar(
        select(ReportExecution)
        .options(
            selectinload(ReportExecution.sections),
            selectinload(ReportExecution.artifacts),
            selectinload(ReportExecution.snapshot),
        )
        .where(
            ReportExecution.analysis_run_id == run.id,
            ReportExecution.report_type == report_type,
            ReportExecution.report_version == REPORT_VERSION,
            ReportExecution.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        return existing
    report_id = uuid.uuid4()
    snapshot_payload = copy.deepcopy(build_demonstration_snapshot())
    sections_by_key = {
        item["section_key"]: item["content"] for item in snapshot_payload["sections"]
    }
    base_action = sections_by_key["priority_action_plan"]["actions"][0]
    action_specs = (
        (
            "Remove the insecure resource reference",
            94,
            "Frontend engineering",
            "Repeat browser analysis and confirm no insecure resource request remains.",
        ),
        (
            "Add meaningful alternative text to the hero image",
            88,
            "Content design",
            "Repeat the accessibility check and complete a manual screen-reader review.",
        ),
        (
            "Give each product page a distinct title",
            82,
            "SEO and content",
            "Repeat site diagnostics and confirm that the duplicate title group is absent.",
        ),
        (
            "Review the shared product metadata template",
            76,
            "Frontend engineering",
            "Inspect all four prepared pages and verify unique metadata evidence.",
        ),
        (
            "Enable approved field-performance evidence",
            70,
            "Platform operations",
            "Confirm provider availability; retain unavailable status until evidence exists.",
        ),
    )
    actions = []
    for index, (title, score, role, verification) in enumerate(action_specs, 1):
        action = copy.deepcopy(base_action)
        action.update(
            {
                "action_id": str(uuid.uuid5(report_id, f"action:{index}")),
                "priority_rank": index,
                "title": title,
                "priority_score": score,
                "responsible_role": role,
                "recommended_sequence": index,
                "verification_method": verification,
            }
        )
        actions.append(action)
    sections_by_key["priority_action_plan"]["actions"] = actions
    sections_by_key["executive_summary"]["five_most_important_actions"] = actions
    sections_by_key["executive_summary"]["quick_wins"] = actions[:2]
    sections_by_key["executive_summary"]["strategic_fixes"] = actions[2:]
    snapshot_payload.update(
        {
            "report_id": str(report_id),
            "project_id": str(project.id),
            "project_name": project.name,
            "website_id": str(website.id),
            "website_name": website.name,
            "website_url": website.url,
            "analysis_run_id": str(run.id),
            "workflow_execution_id": str(execution.execution_id),
            "score_execution_id": None,
        }
    )
    enrich_presentation_snapshot(snapshot_payload)
    report = ReportExecution(
        report_id=report_id,
        project_id=project.id,
        website_id=website.id,
        analysis_run_id=run.id,
        workflow_execution_id=execution.id,
        score_execution_id=None,
        report_type=report_type,
        report_version=REPORT_VERSION,
        template_id=TEMPLATE_ID,
        template_version=TEMPLATE_VERSION,
        input_fingerprint=fingerprint(snapshot_payload),
        idempotency_key=idempotency_key,
        status="partial",
        evidence_coverage_numerator=15,
        evidence_coverage_denominator=16,
        evidence_coverage_percentage=93.75,
        confidence_percent=88,
        unavailable_sections=["performance"],
        provider_version_metadata={
            "generation_mode": "deterministic_local_fixture",
            "llm_provider": "unavailable",
            "report_agent_id": "report_agent",
        },
        failure_details={},
        partial_completion_details={
            "unavailable_evidence": ["crux_field_evidence"],
            "meaning": "Unavailable evidence is not treated as a passed check.",
        },
        started_at=DEMO_TIMESTAMP,
        completed_at=DEMO_TIMESTAMP,
    )
    db.add(report)
    db.flush()
    all_evidence: list[dict[str, Any]] = []
    for section in snapshot_payload["sections"]:
        section_id = uuid.uuid5(report_id, f"section:{section['section_key']}")
        section["section_id"] = str(section_id)
        all_evidence.extend(section["evidence_references"])
        db.add(
            ReportSection(
                section_id=section_id,
                report_execution_id=report.id,
                section_key=section["section_key"],
                position=section["position"],
                title=section["title"],
                status=section["status"],
                content=section["content"],
                evidence_references=section["evidence_references"],
                unavailable_reason=section["unavailable_reason"],
            )
        )
    db.add(
        ReportSnapshot(
            snapshot_id=uuid.uuid5(report_id, "snapshot:1"),
            report_execution_id=report.id,
            snapshot_payload=snapshot_payload,
            evidence_references=all_evidence,
        )
    )
    for artifact_format in ("html", "pdf", "json"):
        export_kind = {
            "html": "presentation-html",
            "pdf": "presentation-pdf",
            "json": "evidence-json",
        }[artifact_format]
        content, media_type, filename = render_demo_export(export_kind, snapshot_payload)
        artifact_id = uuid.uuid5(report_id, f"artifact:{artifact_format}:1")
        db.add(
            ReportArtifact(
                artifact_id=artifact_id,
                report_execution_id=report.id,
                format=artifact_format,
                media_type=media_type,
                filename=filename,
                size_bytes=len(content),
                checksum_sha256=hashlib.sha256(content).hexdigest(),
                storage_location=f"database://report-artifacts/{artifact_id}",
                content=content,
            )
        )
    db.flush()
    return report


def _agent_payload(execution: AgentExecution) -> list[dict[str, Any]]:
    statuses = {run.agent_id: run.status for run in execution.runs}
    return [
        {
            "agent_id": definition.agent_id,
            "name": FRIENDLY_AGENT_DETAILS[definition.agent_id][0],
            "responsibility": FRIENDLY_AGENT_DETAILS[definition.agent_id][1],
            "status": statuses.get(definition.agent_id, "unavailable"),
            "processed_summary": FRIENDLY_AGENT_DETAILS[definition.agent_id][2],
        }
        for definition in AgentRegistry.get_all()
    ]


def _stage_payload(execution: AgentExecution) -> list[dict[str, Any]]:
    statuses = {run.agent_id: run.status for run in execution.runs}
    result = []
    for stage_id, name, agent_ids, parallel in STAGE_DEFINITIONS:
        stage_statuses = {statuses.get(agent_id, "unavailable") for agent_id in agent_ids}
        if "failed" in stage_statuses:
            status = "failed"
        elif stage_statuses == {"completed"}:
            status = "completed"
        elif "completed" in stage_statuses:
            status = "partial"
        else:
            status = "unavailable"
        result.append(
            {
                "stage_id": stage_id,
                "name": name,
                "agent_ids": list(agent_ids),
                "parallel": parallel,
                "status": status,
            }
        )
    return result


def _presentation_payload(
    execution: AgentExecution,
    report: ReportExecution,
    *,
    presentation_status: str,
    live_execution_status: str | None,
    used_fallback: bool,
    status_message: str,
    reused: bool,
) -> dict[str, Any]:
    snapshot = report.snapshot.snapshot_payload
    presentation = snapshot["presentation"]
    standard_artifacts = {artifact.format: artifact for artifact in report.artifacts}
    pdf_content = render_additional_report_artifact("pdf", snapshot)[0]
    pdf_checksum = hashlib.sha256(pdf_content).hexdigest()
    artifact_specs = (
        (
            "presentation_html",
            "Presentation HTML",
            standard_artifacts["html"].filename,
            standard_artifacts["html"].size_bytes,
            standard_artifacts["html"].checksum_sha256,
            f"/api/v1/reports/{report.report_id}/download/html",
        ),
        (
            "presentation_pdf",
            "Export Presentation PDF",
            standard_artifacts["pdf"].filename,
            len(pdf_content),
            pdf_checksum,
            f"/api/v1/reports/{report.report_id}/download/pdf",
        ),
        (
            "evidence_json",
            "Download Evidence JSON",
            standard_artifacts["json"].filename,
            standard_artifacts["json"].size_bytes,
            standard_artifacts["json"].checksum_sha256,
            f"/api/v1/reports/{report.report_id}/download/json",
        ),
    )
    artifacts = [
        {
            "kind": kind,
            "label": label,
            "filename": filename,
            "size_bytes": size,
            "checksum_sha256": checksum,
            "download_url": url,
        }
        for kind, label, filename, size, checksum, url in artifact_specs
    ]
    for kind, label, export_kind in (
        ("technical_appendix", "Export Technical Appendix", "technical-appendix"),
        ("page_inventory", "Download Page Inventory JSON", "page-inventory"),
    ):
        content, _media_type, filename = render_demo_export(export_kind, snapshot)
        artifacts.append(
            {
                "kind": kind,
                "label": label,
                "filename": filename,
                "size_bytes": len(content),
                "checksum_sha256": hashlib.sha256(content).hexdigest(),
                "download_url": (f"/api/v1/demo/reports/{report.report_id}/exports/{export_kind}"),
            }
        )
    return {
        "prepared": True,
        "presentation_status": presentation_status,
        "live_execution_status": live_execution_status,
        "used_prepared_fallback": used_fallback,
        "status_message": status_message,
        "project_id": report.project_id,
        "project_name": DEMO_PROJECT_NAME,
        "website_id": report.website_id,
        "website_name": DEMO_WEBSITE_NAME,
        "website_url": DEMO_WEBSITE_URL,
        "analysis_run_id": report.analysis_run_id,
        "workflow_execution_id": execution.execution_id,
        "report_id": report.report_id,
        "report_status": report.status,
        "report_ready": True,
        "overall_score": 76,
        "score_confidence_percent": 88,
        "evidence_coverage_numerator": 15,
        "evidence_coverage_denominator": 16,
        "evidence_coverage_percentage": 93.75,
        "page_coverage": presentation["coverage"],
        "page_inventory": presentation["page_inventory"],
        "browser_compatibility": presentation["browser_compatibility"],
        "category_scores": presentation["category_scores"],
        "agents": _agent_payload(execution),
        "stages": _stage_payload(execution),
        "top_findings": presentation["top_findings"],
        "top_actions": presentation["top_actions"],
        "artifacts": artifacts,
        "reused": reused,
    }


def prepare_demo(db: Session) -> dict[str, Any]:
    project, website, run = _ensure_project_evidence(db)
    execution, created = _execution_for_key(
        db,
        project,
        run,
        idempotency_key=PREPARED_IDEMPOTENCY_KEY,
        failed=False,
    )
    report = _persist_report(
        db,
        project,
        website,
        run,
        execution,
        idempotency_key=PREPARED_IDEMPOTENCY_KEY,
        report_type="presentation_prepared",
    )
    db.commit()
    db.refresh(execution)
    db.refresh(report)
    return _presentation_payload(
        execution,
        report,
        presentation_status="ready",
        live_execution_status=None,
        used_fallback=False,
        status_message="Verified prepared demo report is ready.",
        reused=not created,
    )


def run_demo(db: Session, *, idempotency_key: str, simulate_failure: bool) -> dict[str, Any]:
    prepared = prepare_demo(db)
    project = db.get(Project, prepared["project_id"])
    website = db.get(Website, prepared["website_id"])
    run = db.get(AnalysisRun, prepared["analysis_run_id"])
    assert project is not None and website is not None and run is not None
    execution, created = _execution_for_key(
        db,
        project,
        run,
        idempotency_key=idempotency_key,
        failed=simulate_failure,
    )
    if execution.status == "completed":
        report = _persist_report(
            db,
            project,
            website,
            run,
            execution,
            idempotency_key=idempotency_key,
            report_type="presentation_demo",
        )
        presentation_status = "completed"
        used_fallback = False
        message = "Demo analysis completed and its report is ready."
    else:
        report = db.scalar(
            select(ReportExecution)
            .options(
                selectinload(ReportExecution.sections),
                selectinload(ReportExecution.artifacts),
                selectinload(ReportExecution.snapshot),
            )
            .where(ReportExecution.report_id == prepared["report_id"])
        )
        assert report is not None
        presentation_status = "fallback"
        used_fallback = True
        message = "Live demo execution failed. Showing the last verified prepared fallback report."
    db.commit()
    db.refresh(execution)
    db.refresh(report)
    return _presentation_payload(
        execution,
        report,
        presentation_status=presentation_status,
        live_execution_status=execution.status,
        used_fallback=used_fallback,
        status_message=message,
        reused=not created,
    )


def demo_status(db: Session) -> dict[str, Any]:
    project = _prepared_project(db)
    if project is None:
        return {
            "prepared": False,
            "presentation_status": "not_prepared",
            "live_execution_status": None,
            "used_prepared_fallback": False,
            "status_message": "Prepared demo data has not been created.",
            "project_id": None,
            "project_name": None,
            "website_id": None,
            "website_name": None,
            "website_url": None,
            "analysis_run_id": None,
            "workflow_execution_id": None,
            "report_id": None,
            "report_status": None,
            "report_ready": False,
            "overall_score": None,
            "score_confidence_percent": None,
            "evidence_coverage_numerator": 0,
            "evidence_coverage_denominator": 0,
            "evidence_coverage_percentage": None,
            "page_coverage": {},
            "page_inventory": [],
            "browser_compatibility": {},
            "category_scores": [],
            "agents": [],
            "stages": [],
            "top_findings": [],
            "top_actions": [],
            "artifacts": [],
            "reused": False,
        }
    return prepare_demo(db)


def reset_demo(db: Session) -> int:
    projects = list(
        db.scalars(
            select(Project).where(
                Project.name == DEMO_PROJECT_NAME,
                Project.description == DEMO_PROJECT_DESCRIPTION,
            )
        )
    )
    for project in projects:
        db.delete(project)
    db.commit()
    return len(projects)
