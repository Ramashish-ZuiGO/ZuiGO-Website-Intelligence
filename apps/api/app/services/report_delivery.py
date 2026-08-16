import hashlib
import html
import json
import re
import textwrap
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from io import BytesIO
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models import (
    AccessibilityAudit,
    AccessibilityFinding,
    AccessibilityNode,
    ActionGenerationExecution,
    ActionItem,
    AgentArtifact,
    AgentExecution,
    AgentRun,
    AnalysisFinding,
    AnalysisRun,
    DiscoveryRun,
    DiscoveryRunPage,
    PageAnalysisRun,
    ReportArtifact,
    ReportExecution,
    ReportSection,
    ReportSnapshot,
    ScoreExecution,
    SiteDiagnosticExecution,
    SiteDiagnosticFinding,
    SiteDiagnosticOccurrence,
    WebsitePage,
)
from app.services.action_generation import FINDING_TO_ACTION_MAP
from app.services.agent_platform_registry import AgentRegistry
from app.services.browser_compatibility import (
    ENGINE_LABELS,
    ENGINE_UAT_LABELS,
    UAT_VERIFICATION_STATE_LABELS,
    VERIFICATION_STATE_LABELS,
    _build_browser_uat_matrix,
    browser_uat_completion,
)
from app.services.browser_uat_tier0 import (
    fetch_latest_tier0_page_results,
    fetch_latest_tier0_structural_results,
)
from app.services.canonical_report_metrics import (
    _assign_limitation_id,
    deduplicate_limitations,
    reconcile_affected_pages,
)
from app.services.page_selection import select_scheduled_pages
from app.services.resource_classification import (
    ResourceClassification,
    classify_resource,
)
from app.services.scoring_formula import FORMULA_ID, FORMULA_VERSION

REPORT_VERSION = "1.1.0"
TEMPLATE_ID = "zuigo_evidence_report"
TEMPLATE_VERSION = "2.1.0"
# Customer-facing product name for generated artifacts. Internal identifiers
# (template ids, package names, historical snapshots) are not renamed.
CUSTOMER_PRODUCT_NAME = "ZuiGO WebIQ"
ARTIFACT_MEDIA_TYPES = {
    "html": "text/html; charset=utf-8",
    "pdf": "application/pdf",
    "json": "application/json",
}
TERMINAL_WORKFLOW_STATUSES = {"completed", "partial", "failed", "cancelled", "unavailable"}
FRIENDLY_FINDING_LABELS = {
    "CSP_MISSING": "Content Security Policy missing",
    "HSTS_MISSING": "Strict Transport Security missing",
    "FRAME_PROTECTION_MISSING": "Frame protection missing",
    "FAILED_NETWORK_REQUESTS": "Failed network requests",
    "duplicate_meta_description_group": "Duplicate meta descriptions",
    "duplicate_normalized_internal_target": "Duplicate normalized link targets",
    "duplicate_normalized_targets": "Duplicate normalized link targets",
    "duplicate_title_group": "Duplicate page titles",
}
SECTION_DEFINITIONS = (
    ("executive_summary", "Executive Summary"),
    ("scores", "Overall and Category Scores"),
    ("performance", "Performance"),
    ("accessibility", "Accessibility"),
    ("site_diagnostics", "Site-Wide Diagnostics"),
    ("internal_link_graph", "Internal Link Graph"),
    ("canonical_indexability", "Canonical and Indexability"),
    ("security_technical", "Security and Technical Findings"),
    ("content_seo", "Content and SEO Findings"),
    ("page_level_findings", "Page-Level Findings"),
    ("repeated_template_problems", "Repeated and Template Problems"),
    ("priority_action_plan", "Priority Action Plan"),
    ("remediation", "Remediation Guidance"),
    ("coverage_confidence", "Evidence Coverage and Confidence"),
    ("multi_agent_execution", "Multi-Agent Execution Summary"),
    ("methodology_limitations", "Methodology, Versions and Limitations"),
)
AGENT_IDS = tuple(agent.agent_id for agent in AgentRegistry.get_all())
AGENT_DEFINITION_BY_ID = {agent.agent_id: agent for agent in AgentRegistry.get_all()}
SECTION_AGENT_IDS = {
    "executive_summary": ("evidence_validation_agent", "report_agent"),
    "scores": ("evidence_validation_agent", "report_agent"),
    "performance": ("performance_agent", "evidence_validation_agent", "report_agent"),
    "accessibility": ("accessibility_agent", "evidence_validation_agent", "report_agent"),
    "site_diagnostics": (
        "site_diagnostics_agent",
        "evidence_validation_agent",
        "report_agent",
    ),
    "internal_link_graph": (
        "discovery_agent",
        "site_diagnostics_agent",
        "evidence_validation_agent",
        "report_agent",
    ),
    "canonical_indexability": (
        "site_diagnostics_agent",
        "evidence_validation_agent",
        "report_agent",
    ),
    "security_technical": (
        "performance_agent",
        "evidence_validation_agent",
        "report_agent",
    ),
    "content_seo": (
        "site_diagnostics_agent",
        "evidence_validation_agent",
        "report_agent",
    ),
    "page_level_findings": (
        "performance_agent",
        "accessibility_agent",
        "site_diagnostics_agent",
        "evidence_validation_agent",
        "report_agent",
    ),
    "repeated_template_problems": (
        "site_diagnostics_agent",
        "evidence_validation_agent",
        "report_agent",
    ),
    "priority_action_plan": (
        "evidence_validation_agent",
        "remediation_agent",
        "report_agent",
    ),
    "remediation": (
        "repository_intelligence_agent",
        "remediation_agent",
        "report_agent",
    ),
    "coverage_confidence": ("evidence_validation_agent", "report_agent"),
    "multi_agent_execution": AGENT_IDS,
    "methodology_limitations": ("evidence_validation_agent", "report_agent"),
}
SEVERITY_ORDER = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
    "informational": 4,
    "info": 4,
}
# Finding codes whose per-page observed-value text legitimately differs (a
# tap-target count, an overlap count) but which represent ONE site-wide rule,
# not a distinct issue per page -- _group_detailed_findings suppresses
# observed_signature for these so they merge into one Complete Findings
# Register entry across every affected page, same as browser_engine_compatibility.
MERGE_ACROSS_PAGES_FINDING_CODES = frozenset(
    {
        "browser_engine_compatibility",
        "tier0_horizontal_overflow",
        "tier0_clipped_elements",
        "tier0_overlapping_elements",
        "tier0_small_tap_targets",
    }
)
SAFE_FILENAME_PATTERN = re.compile(r"[^a-z0-9._-]+")
PRIVATE_KEYS = {
    "chain_of_thought",
    "hidden_reasoning",
    "internal_monologue",
    "private_reasoning",
    "reasoning",
    "scratchpad",
}
SECRET_MARKERS = ("api_key", "authorization", "cookie", "credential", "password", "secret")
PRIVATE_TEXT_PATTERN = re.compile(
    r"\b(chain[_ -]?of[_ -]?thought|hidden[_ -]?reasoning|private[_ -]?reasoning|"
    r"internal[_ -]?monologue|scratchpad)\b",
    re.IGNORECASE,
)
SECRET_TEXT_PATTERNS = (
    re.compile(r"\b(?:api[_ -]?key|password|secret|token)\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
)
INTERNAL_PATH_PATTERNS = (
    re.compile(r"\b[A-Za-z]:\\(?:[^\\\r\n]+\\)*[^\\\r\n]*"),
    re.compile(r"(?:/Users/|/home/|/var/lib/|/workspace/)[^\s\"']+"),
)


class ReportDeliveryError(Exception):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message
        self.status_code = status_code


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _sanitize_text(value: str) -> str:
    if PRIVATE_TEXT_PATTERN.search(value):
        return "[PRIVATE REASONING OMITTED]"
    sanitized = value
    for pattern in SECRET_TEXT_PATTERNS:
        sanitized = pattern.sub("[REDACTED]", sanitized)
    for pattern in INTERNAL_PATH_PATTERNS:
        sanitized = pattern.sub("[INTERNAL PATH OMITTED]", sanitized)
    return sanitized


def sanitize_persisted_value(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            normalized = key.casefold()
            if normalized in PRIVATE_KEYS:
                continue
            if any(marker in normalized for marker in SECRET_MARKERS):
                sanitized[key] = "[REDACTED]"
            else:
                sanitized[key] = sanitize_persisted_value(item)
        return sanitized
    if isinstance(value, (list, tuple, set)):
        return [sanitize_persisted_value(item) for item in value]
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, str):
        return _sanitize_text(value)
    return value


def _evidence(evidence_type: str, evidence_id: uuid.UUID | str) -> dict[str, str]:
    return {
        "evidence_type": evidence_type,
        "evidence_id": str(evidence_id),
        "source": "database",
    }


def _safe_filename(website_name: str | None, report_id: uuid.UUID, artifact_format: str) -> str:
    base = SAFE_FILENAME_PATTERN.sub(
        "-",
        (website_name or "website-report").strip().casefold(),
    ).strip("-._")
    base = base[:80] or "website-report"
    return f"{base}-{str(report_id)[:8]}.{artifact_format}"


def _section(
    key: str,
    *,
    status: str,
    content: dict[str, Any],
    evidence: list[dict[str, Any]],
    attribution: dict[str, Any],
    unavailable_reason: str | None = None,
) -> dict[str, Any]:
    title = dict(SECTION_DEFINITIONS)[key]
    return {
        "section_key": key,
        "title": title,
        "status": status,
        "content": sanitize_persisted_value({**content, "agent_attribution": attribution}),
        "evidence_references": sanitize_persisted_value(evidence),
        "agent_attribution": sanitize_persisted_value(attribution),
        "unavailable_reason": unavailable_reason,
    }


def _tool_ids(run: AgentRun | None) -> list[str]:
    if run is None:
        return []
    return sorted(
        {
            str(activity["tool_id"])
            for activity in run.tool_activity_summary
            if isinstance(activity, dict) and activity.get("tool_id")
        }
    )


def _agent_attribution(
    section_key: str,
    agent_runs: list[AgentRun],
    *,
    fallback_behavior: str,
    repository_connected: bool,
) -> dict[str, Any]:
    latest_runs: dict[str, AgentRun] = {}
    for run in agent_runs:
        current = latest_runs.get(run.agent_id)
        if current is None or (run.attempt, run.created_at, str(run.id)) > (
            current.attempt,
            current.created_at,
            str(current.id),
        ):
            latest_runs[run.agent_id] = run

    agents = []
    unavailable_tools: set[str] = set()
    unavailable_providers: set[str] = set()
    evidence_produced: list[dict[str, Any]] = []
    for agent_id in SECTION_AGENT_IDS[section_key]:
        definition = AGENT_DEFINITION_BY_ID[agent_id]
        run = latest_runs.get(agent_id)
        tools_used = _tool_ids(run)
        if run:
            evidence_produced.extend(sanitize_persisted_value(run.evidence_references))
            for activity in run.tool_activity_summary:
                if not isinstance(activity, dict):
                    continue
                if activity.get("status") == "unavailable" and activity.get("tool_id"):
                    unavailable_tools.add(str(activity["tool_id"]))
                provider = activity.get("provider")
                if activity.get("status") == "unavailable" and provider:
                    unavailable_providers.add(str(provider))
            provider_state = run.provider_version_metadata
            for provider in provider_state.get("unavailable_providers", []):
                unavailable_providers.add(str(provider))
        agents.append(
            {
                "agent_id": agent_id,
                "agent_name": definition.name,
                "agent_version": run.agent_version if run else definition.version,
                "execution_status": (
                    "not_applicable"
                    if agent_id == "repository_intelligence_agent" and not repository_connected
                    else run.status
                    if run
                    else "execution_status_not_recorded"
                ),
                "tools_used": tools_used,
                "allowed_tool_ids": list(definition.allowed_tool_ids),
                "evidence_reference_count": len(run.evidence_references) if run else 0,
                "limitations": definition.limitations,
            }
        )
    return {
        "agents_involved": agents,
        "tools_used": sorted({tool for item in agents for tool in item["tools_used"]}),
        "execution_status": (
            "failed"
            if any(item["execution_status"] == "failed" for item in agents)
            else "partial"
            if any(
                item["execution_status"]
                in {"partial", "unavailable", "execution_status_not_recorded"}
                for item in agents
            )
            else "completed"
        ),
        "evidence_produced": evidence_produced,
        "unavailable_tools": sorted(unavailable_tools),
        "unavailable_providers": sorted(unavailable_providers),
        "fallback_behavior": fallback_behavior,
        "private_reasoning_included": False,
    }


def _latest_score(db: Session, run_id: uuid.UUID) -> ScoreExecution | None:
    return db.scalar(
        select(ScoreExecution)
        .options(
            selectinload(ScoreExecution.categories),
            selectinload(ScoreExecution.contributions),
            selectinload(ScoreExecution.explanation),
        )
        .where(ScoreExecution.analysis_run_id == run_id)
        .order_by(ScoreExecution.created_at.desc(), ScoreExecution.id.desc())
    )


def _workflow_or_raise(
    db: Session,
    run: AnalysisRun,
    workflow_execution_id: uuid.UUID | None,
    *,
    allow_active_workflow: bool,
) -> AgentExecution:
    statement = select(AgentExecution).where(
        AgentExecution.analysis_run_id == run.id,
        AgentExecution.project_id == run.website.project_id,
        AgentExecution.workflow_id == "full_website_analysis",
    )
    if workflow_execution_id is not None:
        statement = statement.where(AgentExecution.execution_id == workflow_execution_id)
    else:
        statement = statement.order_by(AgentExecution.created_at.desc(), AgentExecution.id.desc())
    workflow = db.scalar(statement)
    if workflow is None:
        raise ReportDeliveryError(
            "WORKFLOW_EXECUTION_NOT_FOUND",
            "No full website analysis workflow exists for this analysis run.",
            404,
        )
    if not allow_active_workflow and workflow.status not in TERMINAL_WORKFLOW_STATUSES:
        raise ReportDeliveryError(
            "WORKFLOW_NOT_TERMINAL",
            "The report cannot be generated until the workflow reaches a terminal state.",
            409,
        )
    return workflow


def _loaded_run(db: Session, run_id: uuid.UUID) -> AnalysisRun:
    run = db.scalar(
        select(AnalysisRun)
        .options(
            selectinload(AnalysisRun.website),
            selectinload(AnalysisRun.result),
            selectinload(AnalysisRun.score),
            selectinload(AnalysisRun.interpretation),
            selectinload(AnalysisRun.findings),
            selectinload(AnalysisRun.diagnostics),
        )
        .where(AnalysisRun.id == run_id)
    )
    if run is None:
        raise ReportDeliveryError("ANALYSIS_RUN_NOT_FOUND", "Analysis run not found.", 404)
    return run


def _compute_report_quality(
    *,
    numerator: int,
    denominator: int,
    overall_score: float | None,
    confidence: int | None,
    discovery_completeness: str | None,
) -> str:
    if denominator == 0 or numerator == 0:
        return "FAILED"
    if discovery_completeness == "failed":
        return "FAILED"
    section_ratio = numerator / denominator
    if (
        section_ratio >= 0.9
        and overall_score is not None
        and confidence is not None
        and confidence >= 50
    ):
        return "COMPLETE"
    if section_ratio >= 0.4 or overall_score is not None:
        return "PARTIAL"
    return "INCONCLUSIVE"


def _section_content_by_key(sections: list[dict[str, Any]], key: str) -> dict[str, Any]:
    for section in sections:
        if section.get("section_key") == key:
            content = section.get("content")
            return content if isinstance(content, dict) else {}
    return {}


def _finding_totals(sections: list[dict[str, Any]]) -> dict[str, Any]:
    """Canonical unique-finding vs occurrence accounting for every artifact.

    Client artifacts must never imply that Top Findings are the complete
    result: these totals make the distinction explicit and reconcilable.
    """
    content = _section_content_by_key(sections, "page_level_findings")
    findings = content.get("findings") or []
    severity_totals: dict[str, int] = {}
    for item in findings:
        severity = str(item.get("severity") or "unknown").casefold()
        severity_totals[severity] = severity_totals.get(severity, 0) + 1
    executive = _section_content_by_key(sections, "executive_summary")
    top_problems = executive.get("top_five_problems") or []
    occurrence_count = content.get("total_occurrence_count")
    if occurrence_count is None:
        occurrence_count = sum(len(item.get("exact_occurrences") or []) for item in findings)
    return {
        "total_unique_findings": len(findings),
        "top_finding_count": len(top_problems),
        "occurrence_count": int(occurrence_count),
        "affected_page_count": int(content.get("affected_page_count") or 0),
        "severity_totals": severity_totals,
        "occurrences_are_capped": bool(content.get("occurrences_are_capped", False)),
        "complete_register_location": (
            "All unique findings appear in the findings register; every retained "
            "occurrence appears in the Technical Appendix."
        ),
    }


_COMPLETION_STATUS_BY_QUALITY = {
    "COMPLETE": "complete",
    "PARTIAL": "completed_with_limitations",
    "FAILED": "failed",
    "INCONCLUSIVE": "inconclusive",
}


def _completion_semantics(
    *,
    report_quality: str,
    confidence_components: dict[str, Any],
    discovery_completeness: str | None,
    unavailable_sections: list[str],
    browser_compatibility: dict[str, Any],
    generation_mode: str | None,
    repository_applicable: bool,
) -> dict[str, Any]:
    """Canonical machine-readable completion + limitation reasons.

    Required analysis evidence (discovery, page coverage, report sections,
    deterministic scoring) determines the analysis status. Optional
    capabilities and not-applicable components are reported as limitations
    but never silently downgrade an otherwise complete analysis. Branded
    Browser UAT keeps its own independently visible completeness status and
    is never a prerequisite for report delivery.
    """
    reasons: list[dict[str, str]] = []

    def reason(code: str, kind: str, component: str, message: str) -> None:
        reasons.append({"code": code, "kind": kind, "component": component, "message": message})

    formula_confidence = confidence_components.get("formula_determinism_percent")
    if formula_confidence is not None and float(formula_confidence) < 100:
        reason(
            "SCORE_CONFIDENCE_REDUCED",
            "required",
            "scoring",
            (
                f"Deterministic score confidence is {int(formula_confidence)}% "
                "because part of the required category evidence was incomplete."
            ),
        )
    page_confidence = confidence_components.get("analysed_page_coverage_percent")
    if page_confidence is not None and float(page_confidence) < 100:
        reason(
            "PAGE_COVERAGE_INCOMPLETE",
            "required",
            "page_analysis",
            f"Analysed-page coverage is {page_confidence}% of eligible pages.",
        )
    if discovery_completeness not in (None, "complete"):
        reason(
            "DISCOVERY_NOT_COMPLETE",
            "required",
            "discovery",
            f"Website discovery completeness is '{discovery_completeness}'.",
        )
    for section_key in unavailable_sections:
        reason(
            "REPORT_SECTION_UNAVAILABLE",
            "required",
            section_key,
            f"The '{section_key}' report section had no available evidence.",
        )
    for engine in browser_compatibility.get("engines", []):
        if isinstance(engine, dict) and engine.get("availability_status") == "unavailable":
            reason(
                "BROWSER_ENGINE_UNAVAILABLE",
                "optional",
                str(engine.get("engine")),
                (
                    f"The {engine.get('engine')} engine was unavailable in this "
                    "environment; its evidence is reported as unavailable, not failed."
                ),
            )
    uat_completion = (browser_compatibility.get("browser_uat") or {}).get("completion") or {}
    if uat_completion.get("status") not in (None, "complete"):
        reason(
            "BRANDED_UAT_ENVIRONMENT_UNAVAILABLE",
            "optional_infrastructure",
            "browser_uat",
            (
                "Mandatory branded-browser UAT environments (Google Chrome, "
                "Microsoft Edge, Apple Safari) were not verified in the current "
                "environment. Browser UAT completeness is reported separately "
                "and does not block report delivery."
            ),
        )
    if generation_mode == "deterministic_fallback":
        reason(
            "NARRATIVE_DETERMINISTIC_FALLBACK",
            "optional",
            "narrative",
            "Narrative generation used the deterministic fallback.",
        )
    if not repository_applicable:
        reason(
            "REPOSITORY_NOT_APPLICABLE",
            "not_applicable",
            "repository_intelligence_agent",
            "No repository is connected, so repository intelligence is not applicable.",
        )
    required_limited = any(item["kind"] == "required" for item in reasons)
    status = _COMPLETION_STATUS_BY_QUALITY.get(report_quality, "inconclusive")
    return {
        "analysis_status": status,
        "required_evidence_limited": required_limited,
        "limitation_reasons": reasons,
        "browser_uat": uat_completion,
        "statement": (
            "All required analysis evidence is complete."
            if not required_limited
            else (
                "Required analysis evidence was limited; the machine-readable "
                "limitation reasons identify each affected component."
            )
        ),
    }


def _discovery_message(
    stage_status: str | None,
    completeness: str | None,
    discovery: Any,
) -> str:
    _PENDING = {"queued", "pending", "initializing", "not_started"}
    if stage_status in _PENDING:
        return "Website discovery is waiting to start."
    if stage_status == "running":
        return (
            "Website discovery is in progress. "
            "Full-site coverage will be evaluated after completion."
        )
    if completeness == "complete":
        return "Website discovery completed. Full-site coverage was established."
    if completeness == "partial":
        return (
            "Website discovery completed with partial coverage. "
            "Some website areas may not have been discovered."
        )
    if completeness == "failed":
        reason = discovery.failure_message if discovery else "unknown reason"
        return f"Website discovery failed: {reason or 'unknown reason'}."
    if completeness == "inconclusive":
        return "Website discovery was inconclusive. Full-site coverage could not be established."
    return "Website discovery status is not yet available."


def _real_evidence_summary(
    db: Session,
    run: AnalysisRun,
    workflow: AgentExecution,
    sections: list[dict[str, Any]],
) -> dict[str, Any]:
    discovery_id = workflow.structured_input.get("discovery_run_id")
    discovery = db.get(DiscoveryRun, uuid.UUID(str(discovery_id))) if discovery_id else None
    raw_discovery_status = (
        discovery.status.value
        if discovery and hasattr(discovery.status, "value")
        else str(discovery.status)
        if discovery
        else None
    )
    _TERMINAL_COMPLETENESS = {
        "completed": "complete",
        "partial": "partial",
        "failed": "failed",
        "inconclusive": "inconclusive",
    }
    _ACTIVE_STATUSES = {"queued", "pending", "running", "initializing"}
    if raw_discovery_status is None:
        discovery_completeness = None
        discovery_stage_status = "not_started"
    elif raw_discovery_status in _ACTIVE_STATUSES:
        discovery_completeness = None
        discovery_stage_status = raw_discovery_status
    else:
        discovery_completeness = _TERMINAL_COMPLETENESS.get(raw_discovery_status)
        discovery_stage_status = raw_discovery_status
    discovery_complete = discovery_completeness == "complete"
    _raw_limit = workflow.structured_input.get("maximum_pages")
    page_limit = int(_raw_limit) if _raw_limit is not None else None
    page_execution_id = workflow.structured_input.get("page_analysis_execution_id")
    page_runs = (
        list(
            db.scalars(
                select(PageAnalysisRun)
                .where(
                    PageAnalysisRun.page_analysis_execution_id == uuid.UUID(str(page_execution_id)),
                    PageAnalysisRun.discovery_run_id == discovery.id,
                    PageAnalysisRun.analysis_level == 1,
                )
                .order_by(PageAnalysisRun.created_at, PageAnalysisRun.id)
            )
        )
        if discovery and page_execution_id
        else []
    )
    historical_page_ids = {item.website_page_id for item in page_runs}
    pages = list(
        db.scalars(
            select(WebsitePage)
            .where(
                WebsitePage.website_id == run.website_id,
                *(
                    [
                        or_(
                            # Run-scoped membership: this run's discovered pages,
                            # immutable and unaffected by concurrent same-site runs.
                            WebsitePage.id.in_(
                                select(DiscoveryRunPage.website_page_id).where(
                                    DiscoveryRunPage.discovery_run_id == discovery.id
                                )
                            ),
                            # Legacy fallback for data written before the membership
                            # table existed. Safe under concurrency: this pointer can
                            # only ever equal this run's own discovery id.
                            WebsitePage.last_discovery_run_id == discovery.id,
                            WebsitePage.id.in_(historical_page_ids),
                        )
                    ]
                    if discovery
                    else []
                ),
            )
            .order_by(WebsitePage.crawl_depth, WebsitePage.normalized_url, WebsitePage.id)
        )
    )
    page_run_by_page_id = {item.website_page_id: item for item in page_runs}
    classifications = {
        page.id: classify_resource(
            page.normalized_url,
            final_url=(
                page_run_by_page_id[page.id].final_url
                if page.id in page_run_by_page_id
                else page.final_url
            ),
            content_type=(
                page_run_by_page_id[page.id].content_type
                if page.id in page_run_by_page_id
                else None
            ),
            failure_code=(
                page_run_by_page_id[page.id].failure_reason_code
                if page.id in page_run_by_page_id
                else None
            ),
            eligibility_status=page.eligibility_status,
            exclusion_reason=page.exclusion_reason,
            skip_reason=page.skip_reason,
            origin_relation=page.origin_relation,
        )
        for page in pages
    }
    eligible = [
        item
        for item in pages
        if classifications[item.id].classification == ResourceClassification.ELIGIBLE_HTML_PAGE
    ]
    selected_ids = {
        uuid.UUID(str(item))
        for item in workflow.structured_output.get("page_analysis_summary", {}).get(
            "selected_page_ids", []
        )
    } or set(page_run_by_page_id)
    scheduled = (
        [item for item in eligible if item.id in selected_ids]
        if selected_ids
        else select_scheduled_pages(eligible, page_limit)
    )
    scheduled_ids = {item.id for item in scheduled}
    browser_artifact = db.scalar(
        select(AgentArtifact).where(
            AgentArtifact.execution_id == workflow.id,
            AgentArtifact.artifact_type == "browser_compatibility_evidence",
        )
    )
    # Completed stages persist a full evidence artifact. While the stage is
    # still running (or was interrupted) only the journey's incremental
    # progress block exists — use it so live counters are truthful instead of
    # reporting a false unavailable/0-tested state (Fluid Controls liveness
    # regression).
    live_browser_progress = workflow.structured_output.get("browser_compatibility")
    browser = (
        dict(browser_artifact.artifact_metadata)
        if browser_artifact
        else dict(live_browser_progress)
        if isinstance(live_browser_progress, dict) and live_browser_progress.get("engines")
        else {
            "status": "unavailable",
            "engines": [],
            "viewports": [],
            "matrix": [],
            "observations": [],
            "limitations": [
                "Cross-browser evidence was unavailable and is not represented as passed."
            ],
        }
    )
    observations_by_url: dict[str, set[str]] = {}
    tested_urls_by_engine: dict[str, set[str]] = {}
    for observation in browser.get("observations", []):
        if observation.get("state") in {"not_tested", "unavailable"}:
            continue
        page_url = str(observation["page_url"])
        engine = str(observation.get("engine"))
        observations_by_url.setdefault(page_url, set()).add(engine)
        tested_urls_by_engine.setdefault(engine, set()).add(page_url)
    all_findings = []
    for section in sections:
        values = section["content"].get("findings", [])
        if isinstance(values, list):
            all_findings.extend(item for item in values if isinstance(item, dict))
    finding_by_url: dict[str, list[dict[str, Any]]] = {}
    for finding in all_findings:
        for occurrence in finding.get("exact_occurrences", []):
            if isinstance(occurrence, dict) and occurrence.get("normalized_url"):
                finding_by_url.setdefault(
                    str(occurrence["normalized_url"]),
                    [],
                ).append(finding)
    severity_order = {
        "critical": 0,
        "high": 1,
        "medium": 2,
        "low": 3,
        "informational": 4,
    }
    inventory = []
    for page in pages:
        page_run = page_run_by_page_id.get(page.id)
        resource = classifications[page.id]
        is_eligible = resource.classification == ResourceClassification.ELIGIBLE_HTML_PAGE
        is_scheduled = page.id in scheduled_ids
        visited = bool(is_eligible and page_run and page_run.analysis_started_at)
        successfully_analysed = bool(
            is_eligible
            and page_run
            and page_run.status == "completed"
            and page_run.final_url
            and page_run.http_status_code is not None
        )
        result = (
            resource.classification.value
            if not is_eligible
            else "not_scheduled"
            if not is_scheduled
            else page_run.status
            if page_run
            else "skipped"
        )
        findings = finding_by_url.get(page.normalized_url, [])
        highest = (
            min(
                (str(item.get("severity", "informational")) for item in findings),
                key=lambda value: severity_order.get(value, 99),
            )
            if findings
            else None
        )
        inventory.append(
            {
                "url": page.normalized_url,
                "page_title": page_run.page_title
                if page_run and page_run.page_title
                else page.page_title,
                "page_type": page.page_type,
                "http_status": page_run.http_status_code if page_run else None,
                "final_url": page_run.final_url if page_run else page.final_url,
                "response_content_type": page_run.content_type if page_run else None,
                "detected_content_type": None,
                "content_type_detection": (
                    "No independent content sniff was persisted."
                    if page_run and page_run.content_type
                    else "Content type evidence was unavailable."
                ),
                "resource_classification": resource.classification.value,
                "classification_basis": resource.evidence_basis,
                "eligibility": (
                    "eligible"
                    if resource.classification == ResourceClassification.ELIGIBLE_HTML_PAGE
                    else "not_eligible"
                ),
                "scheduled": is_scheduled,
                "visited": visited,
                "analysed": successfully_analysed,
                "analysis_status": result,
                "browser_engines_tested": sorted(
                    observations_by_url.get(
                        page_run.final_url
                        if page_run and page_run.final_url
                        else page.normalized_url,
                        set(),
                    )
                ),
                "result": result,
                "exclusion_reason": (
                    resource.classification.value
                    if not is_eligible
                    else "Not scheduled for analysis"
                    if not is_scheduled
                    else None
                ),
                "failure_reason": page_run.failure_reason_text if page_run else page.skip_reason,
                "failure_stage": (
                    "Page analysis response validation"
                    if page_run and page_run.failure_reason_code == "unsupported_content_type"
                    else "Page analysis"
                    if page_run and page_run.status == "failed"
                    else None
                ),
                "browser_navigation": (
                    "Eligible for browser navigation."
                    if is_eligible
                    else "Not browser-eligible HTML; asset navigation was not attempted."
                ),
                "issue_count": len(
                    {str(item.get("finding_id")) for item in findings if item.get("finding_id")}
                ),
                "highest_severity": highest,
                "evidence_coverage": (
                    100.0
                    if successfully_analysed
                    else 50.0
                    if page_run and page_run.status == "partial"
                    else 0.0
                ),
            }
        )
    scheduled_page_runs = [item for item in page_runs if item.website_page_id in scheduled_ids]
    successful = [
        item
        for item in scheduled_page_runs
        if item.status == "completed" and item.final_url and item.http_status_code is not None
    ]
    failed = [item for item in scheduled_page_runs if item.status == "failed"]
    incomplete = [
        item
        for item in scheduled_page_runs
        if item.status in {"pending", "running", "partial"}
        or (
            item.status == "completed" and (item.final_url is None or item.http_status_code is None)
        )
    ]
    visited = [item for item in scheduled_page_runs if item.analysis_started_at is not None]
    skipped = [item for item in scheduled_page_runs if item.status == "skipped"]
    skipped_count = len(skipped) + max(0, len(scheduled) - len(scheduled_page_runs))
    denominator = len(eligible)
    analysed_page_coverage = round(len(successful) / denominator * 100, 1) if denominator else None
    engine_rows = {
        str(item.get("engine")): dict(item)
        for item in browser.get("engines", [])
        if isinstance(item, dict) and item.get("engine")
    }
    unavailable_engines: set[str] = set()
    for observation in browser.get("observations", []):
        if observation.get("state") == "unavailable":
            unavailable_engines.add(str(observation.get("engine")))
    browser_engines = []
    for engine in workflow.structured_input.get("browser_engines", []):
        row = engine_rows.get(engine, {})
        # Live/interrupted browser stages persist incremental per-engine
        # counters via the progress callback, while full observation lists are
        # only written at stage completion. Use whichever evidence is larger so
        # an in-flight (or interrupted) stage never truthlessly reports 0
        # tested pages when work demonstrably happened.
        tested_pages = max(
            len(tested_urls_by_engine.get(engine, set())),
            int(row.get("tested_pages") or 0),
        )
        browser_stage_unavailable = browser.get("status") == "unavailable"
        all_unavailable = browser_stage_unavailable or (
            engine in unavailable_engines and tested_pages == 0
        )
        browser_engines.append(
            {
                **row,
                "engine": engine,
                "eligible_pages": len(scheduled),
                "tested_pages": tested_pages,
                "attempted_pages": int(row.get("attempted_pages") or tested_pages),
                "queued_pages": max(0, len(scheduled) - int(row.get("attempted_pages") or 0)),
                "availability_status": "unavailable" if all_unavailable else "available",
            }
        )
    uat_date = datetime.now(UTC).date().isoformat()
    # M5: real Tier 0 desktop-lane evidence, if any exists for this analysis
    # run, folds real VERIFIED/PARTIALLY_VERIFIED results into the matrix
    # below. Absence is not an error -- Tier 0 is on-demand (see M2), so most
    # analyses will have none, and the matrix falls back to today's
    # engine-only NOT_VERIFIED placeholders exactly as before.
    tier0_page_results = fetch_latest_tier0_page_results(db, analysis_run_id=run.id)
    branded_uat_matrix = _build_browser_uat_matrix(
        [
            {
                "engine": item["engine"],
                "tested_pages": int(item.get("tested_pages") or 0),
                "eligible_pages": int(item.get("eligible_pages") or 0),
            }
            for item in browser_engines
        ],
        uat_date=uat_date,
        tier0_page_results=tier0_page_results,
    )
    browser = {
        **browser,
        "eligible_page_count": len(scheduled),
        "engines": browser_engines,
        "engine_coverage": browser_engines,
        "status_labels": dict(VERIFICATION_STATE_LABELS),
        "engine_uat_labels": dict(ENGINE_UAT_LABELS),
        "browser_uat_matrix": branded_uat_matrix,
        "browser_uat": {
            "scope_locked": True,
            "uat_date": uat_date,
            "verification_state_labels": dict(UAT_VERIFICATION_STATE_LABELS),
            "matrix": branded_uat_matrix,
            "completion": browser_uat_completion(branded_uat_matrix),
        },
    }
    return {
        "submitted_url": workflow.structured_input.get("submitted_url"),
        "normalized_url": workflow.structured_input.get("normalized_url") or run.website.url,
        "page_coverage": {
            "discovery_stage_status": discovery_stage_status,
            "discovery_status": raw_discovery_status,
            "discovery_completeness": discovery_completeness,
            "discovery_completeness_message": _discovery_message(
                discovery_stage_status,
                discovery_completeness,
                discovery,
            ),
            "discovery_failure_code": discovery.failure_code if discovery else None,
            "discovery_failure_message": discovery.failure_message if discovery else None,
            "total_urls_discovered": discovery.urls_discovered if discovery else 0,
            "normalized_pages": discovery.urls_unique if discovery else len(pages),
            "eligible_pages": len(eligible),
            "total_pages_scheduled": len(scheduled),
            "not_scheduled_pages": max(0, len(eligible) - len(scheduled)),
            "total_pages_visited": len(visited),
            "successfully_analysed_pages": len(successful),
            "analysed_pages": len(successful),
            "failed_pages": len(failed),
            "document_assets": sum(
                item.classification == ResourceClassification.DOCUMENT_ASSET
                for item in classifications.values()
            ),
            "media_static_assets": sum(
                item.classification == ResourceClassification.MEDIA_STATIC_ASSET
                for item in classifications.values()
            ),
            "skipped_pages": skipped_count,
            "excluded_pages": discovery.urls_excluded if discovery else 0,
            "redirected_pages": sum(
                bool(page.final_url and page.final_url != page.normalized_url) for page in pages
            ),
            "duplicate_normalized_pages": (
                max(0, discovery.urls_discovered - discovery.urls_unique) if discovery else 0
            ),
            "pages_with_incomplete_evidence": len(incomplete),
            "coverage_numerator": len(successful),
            "coverage_denominator": denominator,
            "coverage_percentage": analysed_page_coverage,
            "analysed_page_coverage_percentage": analysed_page_coverage,
            "full_site_coverage_percentage": (
                analysed_page_coverage if discovery_complete else None
            ),
            "full_site_coverage_confidence": (
                "established"
                if discovery_complete
                else "pending"
                if discovery_completeness is None
                else "not_established"
            ),
            "started_at": (
                discovery.started_at.isoformat()
                if discovery and discovery.started_at
                else run.started_at.isoformat()
                if run.started_at
                else None
            ),
            "completed_at": (
                workflow.completed_at.isoformat()
                if workflow.completed_at
                else run.completed_at.isoformat()
                if run.completed_at
                else None
            ),
            "duration_seconds": (
                max(
                    0.0,
                    (
                        (
                            (workflow.completed_at or datetime.now(UTC)).replace(
                                tzinfo=((workflow.completed_at or datetime.now(UTC)).tzinfo or UTC)
                            )
                        )
                        - (
                            (discovery.started_at or run.started_at).replace(
                                tzinfo=((discovery.started_at or run.started_at).tzinfo or UTC)
                            )
                        )
                    ).total_seconds(),
                )
                if discovery and (discovery.started_at or run.started_at)
                else None
            ),
        },
        "page_inventory": inventory,
        "browser_compatibility": browser,
    }


def _finding_sort_key(item: dict[str, Any]) -> tuple[int, str, str]:
    return (
        SEVERITY_ORDER.get(str(item.get("severity", "")).casefold(), 99),
        str(item.get("category", "")),
        str(item.get("finding_id", "")),
    )


def _friendly_finding_title(code: str, fallback: str) -> str:
    if code.startswith("repeated_missing_security_header:"):
        header = code.partition(":")[2]
        header_names = {
            "content_security_policy": "Content Security Policy",
            "permissions_policy": "Permissions Policy",
            "referrer_policy": "Referrer Policy",
            "strict_transport_security": "Strict Transport Security",
            "x_content_type_options": "X-Content-Type-Options",
            "x_frame_options": "X-Frame-Options",
        }
        return f"{header_names.get(header, header.replace('_', ' ').title())} missing"
    return FRIENDLY_FINDING_LABELS.get(code, fallback)


def _category_has_dedicated_audit(
    category_id: str,
    *,
    accessibility_available: bool,
    diagnostics_available: bool,
    performance_available: bool,
) -> bool:
    return {
        "performance": performance_available,
        "accessibility": accessibility_available,
        "best_practices": diagnostics_available,
        "seo": diagnostics_available,
        "technical_quality": diagnostics_available,
    }.get(category_id, False)


def _category_score_limitation(
    category_id: str,
    *,
    score_value: int | None,
    included: bool,
    accessibility_available: bool,
    diagnostics_available: bool,
    performance_available: bool,
) -> str | None:
    if not included or score_value is None:
        return None
    has_audit = _category_has_dedicated_audit(
        category_id,
        accessibility_available=accessibility_available,
        diagnostics_available=diagnostics_available,
        performance_available=performance_available,
    )
    if has_audit:
        return None
    label = category_id.replace("_", " ")
    return (
        f"Score calculated from available formula inputs; "
        f"dedicated {label} audit evidence was unavailable."
    )


def _human_timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return f"{parsed.day} {parsed.strftime('%B %Y, %I:%M %p')} UTC"


_SEVERITY_EFFORT = {
    "critical": ("high", "developer"),
    "high": ("high", "developer"),
    "medium": ("medium", "developer"),
    "low": ("low", "developer"),
    "informational": ("low", "content_editor"),
    "info": ("low", "content_editor"),
}
_SEVERITY_PRIORITY = {
    "critical": 95,
    "high": 80,
    "medium": 60,
    "low": 40,
    "informational": 20,
    "info": 20,
}


_CATEGORY_VERIFICATION_METHODS = {
    "performance": (
        "Re-measure the affected pages with the performance analysis and "
        "confirm the related metric improves past its threshold."
    ),
    "accessibility": (
        "Re-run the automated accessibility audit on the affected pages and "
        "confirm the rule passes; manually verify flagged interactions."
    ),
    "seo": (
        "Re-crawl the affected pages and confirm the tag or content issue is "
        "resolved in the retained page evidence."
    ),
    "content": (
        "Re-crawl the affected pages and confirm the content issue is "
        "resolved in the retained page evidence."
    ),
    "technical": (
        "Re-run site diagnostics on the affected URLs and confirm the "
        "observation no longer appears."
    ),
    "security": (
        "Re-run site diagnostics on the affected URLs and confirm the "
        "security observation no longer appears."
    ),
}


def _deterministic_actions_from_findings(
    all_findings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    sorted_findings = sorted(
        all_findings,
        key=lambda f: SEVERITY_ORDER.get(str(f.get("severity", "")).casefold(), 99),
    )
    actions: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    # Findings that share the same remediation collapse into one action with an
    # aggregated scope instead of repeating near-identical action cards.
    action_by_remediation: dict[str, dict[str, Any]] = {}
    for finding in sorted_findings:
        title = str(finding.get("issue_title", "")).strip()
        if not title or title.casefold() in seen_titles:
            continue
        seen_titles.add(title.casefold())
        severity = str(finding.get("severity", "medium")).casefold()
        category = str(finding.get("category", "")).casefold()
        occurrence_pages = len(finding.get("exact_occurrences", []) or []) or 1
        finding_ids = [finding.get("finding_id")] if finding.get("finding_id") else []
        remediation = str(finding.get("recommendation") or "").strip()
        remediation_key = remediation.casefold()
        if remediation_key and remediation_key in action_by_remediation:
            existing = action_by_remediation[remediation_key]
            existing["affected_scope"]["page_count"] += occurrence_pages
            existing["related_finding_ids"].extend(finding_ids)
            existing["deduplicated_finding_count"] = (
                existing.get("deduplicated_finding_count", 1) + 1
            )
            continue
        effort, role = _SEVERITY_EFFORT.get(severity, ("medium", "developer"))
        priority_score = _SEVERITY_PRIORITY.get(severity, 40)
        rank = len(actions) + 1
        verification = _CATEGORY_VERIFICATION_METHODS.get(
            category,
            f"Re-run analysis and confirm the finding '{title}' no longer appears.",
        )
        action = {
            "action_id": f"det-{rank}",
            "priority_rank": rank,
            "title": title,
            "severity": severity,
            "priority_score": priority_score,
            "priority_formula_version": "1.0.0",
            "score_contribution": None,
            "impact": (
                finding.get("business_impact")
                or f"Resolve {severity}-severity {finding.get('category', 'issue')}"
            ),
            "effort": effort,
            "responsible_role": role,
            "affected_scope": {
                "page_count": occurrence_pages,
                "requested_url": finding.get("requested_url"),
                "final_url": finding.get("final_url"),
            },
            "dependencies": [],
            "recommended_sequence": rank,
            "expected_measurable_outcome": finding.get("recommendation", f"Fix: {title}"),
            "verification_method": verification,
            "evidence_references": finding.get("evidence_references", []),
            "related_agents": [],
            "related_finding_ids": finding_ids,
            "status": "pending",
            "generation_method": "deterministic_from_findings",
        }
        actions.append(action)
        if remediation_key:
            action_by_remediation[remediation_key] = action
        if rank >= 20:
            break
    return actions


def _group_detailed_findings(
    findings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str, str, str, str], dict[str, Any]] = {}
    for finding in findings:
        occurrences = [
            item for item in finding.get("exact_occurrences", []) if isinstance(item, dict)
        ]
        observed_signature = canonical_json(
            sorted(
                {
                    str(item.get("observed_value", "")).strip().casefold()
                    for item in occurrences
                    if item.get("observed_value")
                }
            )
        )
        browser_signature = canonical_json(
            sorted(
                {
                    str(browser).casefold()
                    for item in occurrences
                    for browser in item.get("browser_engines_affected", [])
                }
            )
        )
        resource_signature = canonical_json(
            sorted(
                {
                    "resource"
                    if item.get("resource_url")
                    else "element"
                    if item.get("selector")
                    else "location"
                    if item.get("location")
                    else "page"
                    for item in occurrences
                }
            )
        )
        merges_across_pages = (
            str(finding.get("finding_code", "")).casefold() in MERGE_ACROSS_PAGES_FINDING_CODES
        )
        key = (
            str(
                finding.get("rule_signature")
                or finding.get("finding_code")
                or finding.get("issue_title", "")
            ).casefold(),
            "" if merges_across_pages else str(finding.get("issue_title", "")).casefold(),
            str(finding.get("category", "")).casefold(),
            str(finding.get("scope", "")).casefold(),
            "" if merges_across_pages else observed_signature,
            browser_signature,
            resource_signature,
        )
        if key not in grouped:
            grouped[key] = dict(finding)
            continue
        retained = grouped[key]
        retained["severity"] = min(
            (retained.get("severity", "informational"), finding.get("severity", "informational")),
            key=lambda value: SEVERITY_ORDER.get(str(value).casefold(), 99),
        )
        retained["exact_occurrences"] = list(retained.get("exact_occurrences", [])) + list(
            finding.get("exact_occurrences", [])
        )
        retained["evidence_references"] = list(
            {
                canonical_json(reference): reference
                for reference in [
                    *retained.get("evidence_references", []),
                    *finding.get("evidence_references", []),
                ]
            }.values()
        )
        retained["related_finding_ids"] = sorted(
            {
                *retained.get("related_finding_ids", []),
                *finding.get("related_finding_ids", []),
                str(finding.get("finding_id", "")),
            }
            - {"", str(retained.get("finding_id", ""))}
        )

    output = []
    for retained in grouped.values():
        occurrences = list(
            {
                canonical_json(occurrence): occurrence
                for occurrence in retained.get("exact_occurrences", [])
            }.values()
        )
        occurrences.sort(
            key=lambda item: (
                str(item.get("normalized_url", "")),
                str(item.get("selector") or item.get("resource_url") or item.get("location") or ""),
                canonical_json(item),
            )
        )
        affected_pages = list(
            {
                str(item.get("normalized_url")): item
                for item in occurrences
                if item.get("normalized_url")
            }.values()
        )
        retained["exact_occurrences"] = occurrences
        retained["affected_pages"] = affected_pages
        retained["affected_page_count"] = len(affected_pages)
        retained["occurrence_count"] = len(occurrences)
        if (
            str(retained.get("finding_code", "")).casefold() == "browser_engine_compatibility"
            and len(affected_pages) > 1
        ):
            engines = sorted(
                {str(b) for occ in occurrences for b in occ.get("browser_engines_affected", [])}
            )
            retained["issue_title"] = (
                f"Browser-engine compatibility differs across {len(affected_pages)} pages"
                + (f" ({', '.join(engines)})" if engines else "")
            )
        output.append(retained)
    return sorted(output, key=_finding_sort_key)


def _page_detail(
    *,
    normalized_url: str,
    page: WebsitePage | None,
    status_code: int | None,
    page_title: str | None,
    selector: str | None,
    resource_url: str | None,
    location: str | None,
    observed_value: str | None,
    expected_value: str | None,
    evidence_timestamp: datetime,
    provider: str,
    provider_version: str | None,
    artifact_reference: Any = None,
    scope: str = "page",
    final_url: str | None = None,
    collection_status: str | None = None,
) -> dict[str, Any]:
    return {
        "normalized_url": normalized_url,
        "final_url": final_url or normalized_url,
        "status_code": status_code,
        "collection_status": collection_status
        or (f"HTTP {status_code}" if status_code is not None else "Evidence recorded"),
        "page_title": page.page_title if page and page.page_title else page_title,
        "page_type": page.page_type if page else "unknown",
        "section": (
            normalized_url.split("/", 4)[3]
            if normalized_url.count("/") >= 3 and normalized_url.split("/", 4)[3]
            else "root"
        ),
        "selector": selector,
        "resource_url": resource_url,
        "location": location,
        "observed_value": observed_value,
        "expected_value": expected_value,
        "evidence_timestamp": evidence_timestamp.isoformat(),
        "analysis_provider": provider,
        "analysis_provider_version": provider_version,
        "artifact_reference": artifact_reference,
        "scope": scope,
    }


def _action_for(
    actions_by_identity: dict[str, ActionItem],
    *identities: str,
) -> ActionItem | None:
    for identity in identities:
        if identity in actions_by_identity:
            return actions_by_identity[identity]
    return None


def _analysis_finding_payload(
    item: AnalysisFinding,
    *,
    run: AnalysisRun,
    page_by_url: dict[str, WebsitePage],
    page_run_by_url: dict[str, PageAnalysisRun],
    actions_by_identity: dict[str, ActionItem],
    related_ids: list[str],
) -> dict[str, Any]:
    source = item.source.value
    action = _action_for(
        actions_by_identity,
        item.finding_code,
        str(item.id),
        f"analysis_finding:{item.id}",
    )
    evidence = item.evidence if isinstance(item.evidence, dict) else {}
    provider_version = (
        run.result.lighthouse_version
        if run.result and source == "lighthouse"
        else "playwright-persisted"
        if source == "playwright"
        else "http-persisted"
    )
    page = page_by_url.get(item.affected_url)
    page_run = page_run_by_url.get(item.affected_url)
    occurrence = _page_detail(
        normalized_url=item.affected_url,
        page=page,
        status_code=(
            page_run.http_status_code
            if page_run
            else run.result.http_status_code
            if run.result and item.affected_url in {run.result.requested_url, run.result.final_url}
            else None
        ),
        page_title=page_run.page_title if page_run else page.page_title if page else None,
        selector=evidence.get("selector"),
        resource_url=evidence.get("resource_url"),
        location=evidence.get("location"),
        observed_value=(
            str(evidence["observed_value"]) if evidence.get("observed_value") is not None else None
        ),
        expected_value=(
            str(evidence["expected_value"]) if evidence.get("expected_value") is not None else None
        ),
        evidence_timestamp=item.created_at,
        provider=source,
        provider_version=provider_version,
        artifact_reference=evidence.get("artifact_reference")
        or evidence.get("screenshot_reference"),
        final_url=page_run.final_url if page_run else page.final_url if page else None,
        collection_status=(
            page_run.status
            if page_run
            else "Evidence recorded; HTTP status was not retained for this occurrence."
        ),
    )
    return {
        "finding_id": str(item.id),
        "finding_code": item.finding_code,
        "finding_type": "page_analysis",
        "issue_title": _friendly_finding_title(item.finding_code, item.title),
        "plain_language_explanation": item.description,
        "technical_explanation": evidence.get("technical_explanation", item.description),
        "category": item.category,
        "severity": item.severity.value,
        "confidence": {
            "classification": (
                "high"
                if item.confidence_percent >= 80
                else "medium"
                if item.confidence_percent >= 50
                else "low"
            ),
            "percent": item.confidence_percent,
        },
        "affected_pages": [occurrence],
        "exact_occurrences": [occurrence],
        "affected_page_count": 1,
        "occurrence_count": 1,
        "evidence_references": [_evidence("analysis_finding", item.id)],
        "evidence_source": {
            "source": source,
            "provider": source,
            "provider_version": provider_version,
        },
        "detecting_agent": "performance_agent",
        "validating_agent": "evidence_validation_agent",
        "likely_cause": evidence.get(
            "likely_cause", "A cause was not established by retained evidence."
        ),
        "technical_impact": evidence.get("technical_impact", item.description),
        "business_impact": (
            action.business_impact
            if action
            else "No quantified business impact is supported by retained evidence."
        ),
        "recommended_remediation": (
            action.exact_correction
            if action
            else "No evidence-grounded remediation record is available for this finding."
        ),
        "responsible_role": action.responsible_role if action else "Unassigned",
        "estimated_effort_band": action.estimated_effort if action else "unestimated",
        "verification_procedure": (
            action.verification_steps
            if action
            else f"Repeat the {source} analysis and compare the same retained evidence."
        ),
        "related_finding_ids": related_ids,
        "evidence_limitations": evidence.get(
            "limitations",
            "The finding is limited to the retained page analysis and provider evidence.",
        ),
        "evidence_state": "available",
        "scope": "page",
    }


def _diagnostic_finding_payload(
    item: SiteDiagnosticFinding,
    *,
    diagnostic: SiteDiagnosticExecution,
    actions_by_identity: dict[str, ActionItem],
    related_ids: list[str],
) -> dict[str, Any]:
    action = _action_for(
        actions_by_identity,
        item.rule_id,
        str(item.id),
        f"site_diagnostic_finding:{item.id}",
    )
    occurrences = [
        _page_detail(
            normalized_url=occurrence.normalized_url
            or (
                occurrence.website_page.normalized_url if occurrence.website_page else "unavailable"
            ),
            page=occurrence.website_page,
            status_code=(
                int(occurrence.context["status_code"])
                if occurrence.context.get("status_code") is not None
                else None
            ),
            page_title=(
                str(occurrence.context["page_title"])
                if occurrence.context.get("page_title")
                else None
            ),
            selector=occurrence.element_selector,
            resource_url=occurrence.resource_url,
            location=occurrence.location,
            observed_value=occurrence.observed_value,
            expected_value=occurrence.expected_value,
            evidence_timestamp=occurrence.created_at,
            provider="site_diagnostics",
            provider_version=diagnostic.diagnostic_engine_version,
            artifact_reference=occurrence.supporting_evidence.get("artifact_reference"),
            scope=item.scope,
            final_url=(
                str(occurrence.context["final_url"])
                if occurrence.context.get("final_url")
                else occurrence.normalized_url
            ),
        )
        for occurrence in item.occurrences
    ]
    affected_pages = list(
        {occurrence["normalized_url"]: occurrence for occurrence in occurrences}.values()
    )
    unavailable = item.category == "evidence_availability"
    rule_signature = next(
        (
            str(reference["source_rule_id"])
            for reference in item.evidence_references
            if isinstance(reference, dict) and reference.get("source_rule_id")
        ),
        next(
            (
                str(occurrence.context["source_rule_id"])
                for occurrence in item.occurrences
                if occurrence.context.get("source_rule_id")
            ),
            next(
                (
                    str(occurrence.context["diagnostic_subtype"])
                    for occurrence in item.occurrences
                    if occurrence.context.get("diagnostic_subtype")
                ),
                item.rule_id,
            ),
        ),
    )
    return {
        "finding_id": str(item.id),
        "finding_code": item.rule_id,
        "rule_signature": rule_signature,
        "finding_type": "site_diagnostic",
        "issue_title": (
            f"{_friendly_finding_title(rule_signature, item.title)} repeated across pages"
            if item.rule_id == "repeated_issue_pattern"
            else item.title
        ),
        "plain_language_explanation": item.description,
        "technical_explanation": item.evidence_summary,
        "category": item.category,
        "severity": item.severity,
        "confidence": {
            "classification": item.confidence,
            "percent": None,
        },
        "affected_pages": affected_pages,
        "exact_occurrences": occurrences,
        "affected_page_count": item.affected_page_count,
        "occurrence_count": item.occurrence_count,
        "evidence_references": item.evidence_references,
        "evidence_source": {
            "source": "site_diagnostics",
            "provider": "deterministic_site_diagnostics",
            "provider_version": diagnostic.diagnostic_engine_version,
            "rule_version": item.rule_version,
        },
        "detecting_agent": "site_diagnostics_agent",
        "validating_agent": "evidence_validation_agent",
        "likely_cause": (
            action.why_this_matters
            if action
            else "A shared implementation cause is not proven by pattern evidence alone."
        ),
        "technical_impact": item.why_it_matters,
        "business_impact": (
            action.business_impact
            if action
            else "No quantified business impact is supported by retained evidence."
        ),
        "recommended_remediation": item.remediation_guidance,
        "responsible_role": item.responsible_role,
        "estimated_effort_band": action.estimated_effort if action else "unestimated",
        "verification_procedure": item.verification_guidance,
        "related_finding_ids": related_ids,
        "evidence_limitations": (
            "This conclusion is bounded by persisted diagnostic coverage and rule evidence."
        ),
        "evidence_state": "unavailable" if unavailable else "available",
        "scope": item.scope,
    }


def _accessibility_finding_payload(
    item: AccessibilityFinding,
    *,
    audit: AccessibilityAudit,
    nodes: list[AccessibilityNode],
    page: WebsitePage | None,
    related_ids: list[str],
) -> dict[str, Any]:
    occurrences = [
        _page_detail(
            normalized_url=audit.normalized_url,
            page=page,
            status_code=None,
            page_title=page.page_title if page else None,
            selector=node.normalized_selector,
            resource_url=None,
            location=node.frame_context or node.shadow_dom_context,
            observed_value=node.failure_summary or node.html_excerpt,
            expected_value=item.help_text,
            evidence_timestamp=node.created_at,
            provider=audit.provider,
            provider_version=audit.provider_version,
            artifact_reference=None,
            final_url=audit.normalized_url,
            collection_status=audit.status,
        )
        for node in nodes
    ]
    if not occurrences:
        occurrences = [
            _page_detail(
                normalized_url=audit.normalized_url,
                page=page,
                status_code=None,
                page_title=page.page_title if page else None,
                selector=None,
                resource_url=None,
                location=None,
                observed_value=item.description,
                expected_value=item.help_text,
                evidence_timestamp=item.created_at,
                provider=audit.provider,
                provider_version=audit.provider_version,
                final_url=audit.normalized_url,
                collection_status=audit.status,
            )
        ]
    return {
        "finding_id": str(item.id),
        "finding_code": item.provider_rule_id,
        "finding_type": "accessibility",
        "issue_title": item.title,
        "plain_language_explanation": item.help_text or item.description or item.title,
        "technical_explanation": item.description or item.help_text or item.title,
        "category": "accessibility",
        "severity": item.impact,
        "confidence": {
            "classification": "medium" if item.manual_verification_required else "high",
            "percent": None,
        },
        "affected_pages": [occurrences[0]],
        "exact_occurrences": occurrences,
        "affected_page_count": 1,
        "occurrence_count": len(occurrences),
        "evidence_references": [_evidence("accessibility_finding", item.id)],
        "evidence_source": {
            "source": "accessibility_audit",
            "provider": audit.provider,
            "provider_version": audit.provider_version,
            "ruleset_version": audit.ruleset_version,
        },
        "detecting_agent": "accessibility_agent",
        "validating_agent": "evidence_validation_agent",
        "likely_cause": "The retained nodes expose the rule condition; root cause requires review.",
        "technical_impact": item.description or item.help_text or item.title,
        "business_impact": (
            "The condition may create a user barrier; prevalence and user impact require "
            "manual validation."
        ),
        "recommended_remediation": (
            item.remediation_summary
            or "Use the provider guidance and validate the affected interaction manually."
        ),
        "responsible_role": "Accessibility and frontend engineering",
        "estimated_effort_band": "unestimated",
        "verification_procedure": (
            "Repeat the automated rule and complete the retained manual verification requirement."
        ),
        "related_finding_ids": related_ids,
        "evidence_limitations": (
            "Automated accessibility evidence cannot establish complete compliance."
        ),
        "evidence_state": "available",
        "scope": "page",
    }


def _browser_finding_payload(
    row: dict[str, Any],
    artifact: AgentArtifact,
) -> dict[str, Any]:
    affected_engines = [
        ENGINE_LABELS[engine]
        for engine, state in row.get("engines", {}).items()
        if state in {"incompatible", "partially_compatible"}
    ]
    working_engines = [
        ENGINE_LABELS[engine]
        for engine, state in row.get("engines", {}).items()
        if state == "compatible"
    ]
    finding_id = uuid.uuid5(
        artifact.artifact_id,
        f"browser-finding:{row['page_url']}",
    )
    occurrence = {
        "normalized_url": row["page_url"],
        "final_url": row.get("final_url") or row["page_url"],
        "status_code": None,
        "collection_status": "Browser navigation evidence recorded",
        "page_title": row.get("page_title"),
        "page_type": "unknown",
        "section": "browser_compatibility",
        "selector": None,
        "resource_url": None,
        "location": "Rendered page and critical content",
        "observed_value": ", ".join(
            f"{ENGINE_LABELS[engine]}: {state.replace('_', ' ')}"
            for engine, state in row.get("engines", {}).items()
        ),
        "expected_value": "The page remains usable in every explicitly tested engine.",
        "evidence_timestamp": artifact.created_at.isoformat(),
        "analysis_provider": "Playwright browser-engine analysis",
        "analysis_provider_version": artifact.artifact_metadata.get("profile_version"),
        "artifact_reference": f"agent_artifact:{artifact.artifact_id}",
        "scope": "page",
        "browser_engines_affected": affected_engines,
        "browser_engines_where_it_works": working_engines,
    }
    return {
        "finding_id": str(finding_id),
        "finding_code": "browser_engine_compatibility",
        "finding_type": "browser_compatibility",
        "issue_title": (
            f"Browser-engine compatibility differs on {row.get('page_title') or row['page_url']}"
        ),
        "plain_language_explanation": (
            "The page did not behave consistently across the explicitly tested "
            "Playwright browser engines."
        ),
        "technical_explanation": occurrence["observed_value"],
        "category": "browser_compatibility",
        "severity": "high" if row.get("result") == "incompatible" else "medium",
        "confidence": {"classification": "high", "percent": None},
        "affected_pages": [occurrence],
        "exact_occurrences": [occurrence],
        "affected_page_count": 1,
        "occurrence_count": 1,
        "evidence_references": artifact.evidence_references,
        "evidence_source": {
            "source": "playwright_browser_engines",
            "provider": "Playwright",
            "provider_version": artifact.artifact_metadata.get("profile_version"),
        },
        "detecting_agent": "performance_agent",
        "validating_agent": "evidence_validation_agent",
        "likely_cause": (
            "The retained engine observations establish a difference; source-code "
            "ownership requires repository evidence."
        ),
        "technical_impact": (
            "A rendered page, critical element, interaction, or layout differs in a tested engine."
        ),
        "business_impact": (
            "Visitors using an affected engine may be unable to complete the intended task."
        ),
        "recommended_remediation": (
            "Review the retained engine observations, correct the affected component, "
            "and retest the same page, engines, and viewports."
        ),
        "responsible_role": "Frontend engineering",
        "estimated_effort_band": "unestimated",
        "verification_procedure": (
            "Repeat the configured Chromium, Firefox, and WebKit engine tests and "
            "confirm the page passes at every retained viewport."
        ),
        "related_finding_ids": [],
        "evidence_limitations": (
            "Results cover only the listed Playwright engines, pages, and viewports; "
            "they do not claim every branded browser version."
        ),
        "evidence_state": "available",
        "scope": "page",
        "affected_browser_engines": affected_engines,
        "working_browser_engines": working_engines,
    }


_TIER0_PROBLEM_DETECTORS: tuple[
    tuple[str, Callable[[dict[str, Any]], bool], Callable[[dict[str, Any]], str]], ...
] = (
    (
        "TIER0_HORIZONTAL_OVERFLOW",
        lambda viewport: bool(viewport.get("horizontal_overflow")),
        lambda viewport: (
            f"Horizontal overflow detected at {viewport['viewport_name']} "
            f"({viewport['viewport_width']}x{viewport['viewport_height']})."
        ),
    ),
    (
        "TIER0_CLIPPED_ELEMENTS",
        lambda viewport: int(viewport.get("critical_elements_outside_viewport") or 0) > 0,
        lambda viewport: (
            f"{viewport['critical_elements_outside_viewport']} critical element(s) extend "
            f"beyond the viewport at {viewport['viewport_name']} "
            f"({viewport['viewport_width']}x{viewport['viewport_height']})."
        ),
    ),
    (
        "TIER0_OVERLAPPING_ELEMENTS",
        lambda viewport: int(viewport.get("overlapping_elements") or 0) > 0,
        lambda viewport: (
            f"{viewport['overlapping_elements']} element(s) overlap unexpectedly at "
            f"{viewport['viewport_name']} "
            f"({viewport['viewport_width']}x{viewport['viewport_height']})."
        ),
    ),
    (
        "TIER0_SMALL_TAP_TARGETS",
        lambda viewport: int(viewport.get("small_tap_targets") or 0) > 0,
        lambda viewport: (
            f"{viewport['small_tap_targets']} interactive element(s) smaller than the "
            f"24x24px minimum tap-target size at {viewport['viewport_name']} "
            f"({viewport['viewport_width']}x{viewport['viewport_height']})."
        ),
    ),
)


def _tier0_finding_payloads(
    structural_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Adapts real M3 structural evidence from
    fetch_latest_tier0_structural_results into the same finding-dict shape
    _browser_finding_payload produces, so it flows through the SAME
    _group_detailed_findings merge/dedup pipeline used by the Complete
    Findings Register and Technical Appendix -- no separate rendering path,
    no fabricated AnalysisFinding rows (Tier 0's execution shape doesn't fit
    that table's per-page-analysis-run contract, see
    docs/DEVICE_OS_BROWSER_QA_PLAN.md's Lane C/M6 entries).

    One finding dict per (page, problem category) actually observed --
    mirrors action_generation.py's _tier0_recommendations dedup exactly, so
    a page failing the same check at two viewports produces one occurrence,
    not two. MERGE_ACROSS_PAGES_FINDING_CODES then collapses occurrences
    for the SAME rule across every affected page into one register entry.
    """
    payloads: list[dict[str, Any]] = []
    for page in structural_results:
        seen_codes: set[str] = set()
        for viewport in page.get("viewport_results", []):
            for finding_code, is_triggered, describe in _TIER0_PROBLEM_DETECTORS:
                if finding_code in seen_codes or not is_triggered(viewport):
                    continue
                seen_codes.add(finding_code)
                mapping = FINDING_TO_ACTION_MAP[finding_code]
                finding_id = uuid.uuid5(
                    uuid.UUID(page["page_result_id"]), f"tier0-finding:{finding_code}"
                )
                occurrence = {
                    "normalized_url": page["url"],
                    "final_url": page["url"],
                    "status_code": None,
                    "collection_status": "Real-device/real-browser evidence recorded",
                    "page_title": None,
                    "page_type": "unknown",
                    "section": "browser_uat_tier0",
                    "selector": None,
                    "resource_url": None,
                    "location": viewport["viewport_name"],
                    "observed_value": describe(viewport),
                    "expected_value": mapping["expected_result"],
                    "evidence_timestamp": None,
                    "analysis_provider": (
                        f"Tier 0 real-browser check ({page['browser_channel']}/{page['platform']})"
                    ),
                    "analysis_provider_version": page.get("browser_version"),
                    "artifact_reference": f"browser_uat_tier0_page_result:{page['page_result_id']}",
                    "scope": "page",
                }
                payloads.append(
                    {
                        "finding_id": str(finding_id),
                        "finding_code": finding_code,
                        "finding_type": "browser_uat_tier0",
                        "issue_title": mapping["issue_title"],
                        "plain_language_explanation": mapping["why_this_matters"],
                        "technical_explanation": occurrence["observed_value"],
                        "category": mapping["category"],
                        "severity": mapping["severity"],
                        "confidence": {"classification": "high", "percent": 100},
                        "affected_pages": [occurrence],
                        "exact_occurrences": [occurrence],
                        "affected_page_count": 1,
                        "occurrence_count": 1,
                        "evidence_references": [
                            _evidence("browser_uat_tier0_page_result", page["page_result_id"])
                        ],
                        "evidence_source": {
                            "source": "browser_uat_tier0",
                            "provider": f"{page['browser_channel']} on {page['platform']}",
                            "provider_version": page.get("browser_version"),
                        },
                        "detecting_agent": "performance_agent",
                        "validating_agent": "evidence_validation_agent",
                        "likely_cause": mapping["exact_correction"],
                        "technical_impact": mapping["why_this_matters"],
                        "business_impact": mapping["why_this_matters"],
                        "recommended_remediation": mapping["exact_correction"],
                        "responsible_role": mapping["responsible_role"],
                        "estimated_effort_band": mapping["estimated_effort"],
                        "verification_procedure": mapping["verification_steps"],
                        "related_finding_ids": [],
                        "evidence_limitations": mapping["limitations"],
                        "evidence_state": "available",
                        "scope": "page",
                    }
                )
    return payloads


def _build_sections(
    db: Session,
    run: AnalysisRun,
    workflow: AgentExecution,
    score: ScoreExecution | None,
) -> list[dict[str, Any]]:
    result_ref = [_evidence("analysis_result", run.result.id)] if run.result else []
    score_ref = [_evidence("score_execution", score.execution_id)] if score else []
    finding_refs = [_evidence("analysis_finding", item.id) for item in run.findings]

    diagnostics = db.scalar(
        select(SiteDiagnosticExecution)
        .where(SiteDiagnosticExecution.analysis_run_id == run.id)
        .order_by(SiteDiagnosticExecution.created_at.desc(), SiteDiagnosticExecution.id.desc())
    )
    diagnostic_findings = (
        list(
            db.scalars(
                select(SiteDiagnosticFinding)
                .options(
                    selectinload(SiteDiagnosticFinding.occurrences).selectinload(
                        SiteDiagnosticOccurrence.website_page
                    )
                )
                .where(SiteDiagnosticFinding.execution_id == diagnostics.id)
                .order_by(
                    SiteDiagnosticFinding.severity,
                    SiteDiagnosticFinding.rule_id,
                    SiteDiagnosticFinding.id,
                )
            )
        )
        if diagnostics
        else []
    )
    diagnostic_refs = (
        [_evidence("site_diagnostic_execution", diagnostics.execution_id)] if diagnostics else []
    )
    accessibility = list(
        db.scalars(
            select(AccessibilityAudit)
            .where(AccessibilityAudit.analysis_run_id == run.id)
            .order_by(AccessibilityAudit.created_at, AccessibilityAudit.id)
        )
    )
    accessibility_refs = [_evidence("accessibility_audit", item.id) for item in accessibility]
    audit_by_id = {item.id: item for item in accessibility}
    accessibility_findings = (
        list(
            db.scalars(
                select(AccessibilityFinding)
                .where(AccessibilityFinding.audit_id.in_(audit_by_id))
                .order_by(AccessibilityFinding.impact, AccessibilityFinding.provider_rule_id)
            )
        )
        if audit_by_id
        else []
    )
    accessibility_nodes = (
        list(
            db.scalars(
                select(AccessibilityNode)
                .where(
                    AccessibilityNode.finding_id.in_([item.id for item in accessibility_findings])
                )
                .order_by(AccessibilityNode.created_at, AccessibilityNode.id)
            )
        )
        if accessibility_findings
        else []
    )
    nodes_by_finding: dict[uuid.UUID, list[AccessibilityNode]] = {}
    for node in accessibility_nodes:
        nodes_by_finding.setdefault(node.finding_id, []).append(node)
    action_generation = db.scalar(
        select(ActionGenerationExecution)
        .where(ActionGenerationExecution.website_id == run.website_id)
        .order_by(
            ActionGenerationExecution.created_at.desc(),
            ActionGenerationExecution.id.desc(),
        )
    )
    actions = (
        list(
            db.scalars(
                select(ActionItem)
                .where(ActionItem.generation_execution_id == action_generation.id)
                .order_by(ActionItem.priority_score.desc(), ActionItem.id)
            )
        )
        if action_generation
        else []
    )
    action_refs = [_evidence("action_item", item.id) for item in actions]
    agent_runs = list(
        db.scalars(
            select(AgentRun)
            .where(AgentRun.execution_id == workflow.id)
            .order_by(AgentRun.created_at, AgentRun.agent_id, AgentRun.attempt)
        )
    )
    browser_artifact = db.scalar(
        select(AgentArtifact).where(
            AgentArtifact.execution_id == workflow.id,
            AgentArtifact.artifact_type == "browser_compatibility_evidence",
        )
    )
    browser_compatibility = browser_artifact.artifact_metadata if browser_artifact else {}
    _browser_unavailable_engines = {
        str(obs.get("engine"))
        for obs in browser_compatibility.get("observations", [])
        if obs.get("state") == "unavailable"
    }
    browser_findings = (
        [
            _browser_finding_payload(row, browser_artifact)
            for row in browser_compatibility.get("matrix", [])
            if row.get("result") in {"incompatible", "partially_compatible"}
            and any(
                engine not in _browser_unavailable_engines
                for engine, state in row.get("engines", {}).items()
                if state in {"incompatible", "partially_compatible"}
            )
        ]
        if browser_artifact
        else []
    )
    browser_refs = browser_artifact.evidence_references if browser_artifact else []
    tier0_structural_results = fetch_latest_tier0_structural_results(db, analysis_run_id=run.id)
    tier0_findings = _tier0_finding_payloads(tier0_structural_results)
    tier0_refs = [
        _evidence("browser_uat_tier0_page_result", page["page_result_id"])
        for page in tier0_structural_results
    ]
    workflow_ref = [_evidence("agent_execution", workflow.execution_id)]
    pages = list(
        db.scalars(
            select(WebsitePage)
            .where(WebsitePage.website_id == run.website_id)
            .order_by(WebsitePage.normalized_url, WebsitePage.id)
        )
    )
    page_by_url = {page.normalized_url: page for page in pages}
    page_execution_id = workflow.structured_input.get("page_analysis_execution_id")
    report_page_runs = (
        list(
            db.scalars(
                select(PageAnalysisRun).where(
                    PageAnalysisRun.page_analysis_execution_id == uuid.UUID(str(page_execution_id)),
                    PageAnalysisRun.analysis_level == 1,
                )
            )
        )
        if page_execution_id
        else []
    )
    page_run_by_url: dict[str, PageAnalysisRun] = {}
    page_url_by_id = {page.id: page.normalized_url for page in pages}
    for page_run in report_page_runs:
        for page_url in (
            page_run.requested_url,
            page_run.final_url,
            page_url_by_id.get(page_run.website_page_id),
        ):
            if page_url:
                page_run_by_url[page_url] = page_run
    actions_by_identity = {item.source_finding_identity: item for item in actions}

    analysis_related = {
        str(item.id): [
            str(other.id)
            for other in run.findings
            if other.id != item.id and other.category == item.category
        ]
        for item in run.findings
    }
    diagnostic_related = {
        str(item.id): [
            str(other.id)
            for other in diagnostic_findings
            if other.id != item.id and other.category == item.category
        ]
        for item in diagnostic_findings
    }
    accessibility_related = {
        str(item.id): [
            str(other.id)
            for other in accessibility_findings
            if other.id != item.id and other.provider_rule_id == item.provider_rule_id
        ]
        for item in accessibility_findings
    }
    detailed_analysis_findings = [
        _analysis_finding_payload(
            item,
            run=run,
            page_by_url=page_by_url,
            page_run_by_url=page_run_by_url,
            actions_by_identity=actions_by_identity,
            related_ids=analysis_related[str(item.id)],
        )
        for item in run.findings
    ]
    detailed_diagnostic_findings = (
        [
            _diagnostic_finding_payload(
                item,
                diagnostic=diagnostics,
                actions_by_identity=actions_by_identity,
                related_ids=diagnostic_related[str(item.id)],
            )
            for item in diagnostic_findings
        ]
        if diagnostics
        else []
    )
    detailed_accessibility_findings = [
        _accessibility_finding_payload(
            item,
            audit=audit_by_id[item.audit_id],
            nodes=nodes_by_finding.get(item.id, []),
            page=page_by_url.get(audit_by_id[item.audit_id].normalized_url),
            related_ids=accessibility_related[str(item.id)],
        )
        for item in accessibility_findings
    ]
    all_detailed_findings = _group_detailed_findings(
        [
            *detailed_analysis_findings,
            *detailed_diagnostic_findings,
            *detailed_accessibility_findings,
            *browser_findings,
            *tier0_findings,
        ]
    )

    technical_findings = [
        item
        for item in detailed_analysis_findings
        if str(item["category"]).casefold()
        in {"security", "best_practices", "best-practices", "technical", "performance"}
    ]
    technical_findings.extend(browser_findings)
    content_findings = [
        item
        for item in detailed_analysis_findings
        if str(item["category"]).casefold() in {"seo", "content", "metadata"}
    ]
    link_findings = [
        item
        for item in detailed_diagnostic_findings
        if item["category"] == "internal_link_graph"
        or item["finding_code"] == "unavailable_link_graph_evidence"
    ]
    canonical_findings = [
        item
        for item in detailed_diagnostic_findings
        if item["category"] == "canonical_indexability"
    ]
    diagnostic_content_findings = [
        item
        for item in detailed_diagnostic_findings
        if item["category"] in {"metadata_content", "near_duplicate"}
    ]
    repeated_findings = [
        item
        for item in detailed_diagnostic_findings
        if item["category"] == "repeated_pattern"
        or item["scope"] in {"section", "template", "site"}
    ]
    overall_score = (
        score.overall_score if score else (run.score.overall_score if run.score else None)
    )
    summary_status = "available" if result_ref or score_ref or finding_refs else "unavailable"
    score_categories = (
        [item for item in score.categories if item.included and item.final_score is not None]
        if score
        else []
    )
    strongest_areas = [
        {"category": item.category_id, "score": item.final_score, "band": item.band}
        for item in sorted(
            score_categories,
            key=lambda item: (-int(item.final_score or 0), item.category_id),
        )[:3]
    ]
    weakest_areas = [
        {"category": item.category_id, "score": item.final_score, "band": item.band}
        for item in sorted(
            score_categories,
            key=lambda item: (int(item.final_score or 0), item.category_id),
        )[:3]
    ]
    serious_findings = [
        item for item in all_detailed_findings if item["severity"] in {"critical", "high"}
    ][:5]
    ranked_actions = []
    seen_action_titles: set[str] = set()
    for _rank, item in enumerate(actions, 1):
        action_title_key = str(item.issue_title or "").strip().casefold()
        if action_title_key in seen_action_titles:
            continue
        seen_action_titles.add(action_title_key)
        related_finding_ids = [
            finding["finding_id"]
            for finding in all_detailed_findings
            if item.source_finding_identity
            in {
                finding["finding_id"],
                finding.get("finding_code"),
                f"{finding['finding_type']}:{finding['finding_id']}",
            }
        ]
        ranked_actions.append(
            {
                "action_id": str(item.id),
                "priority_rank": len(ranked_actions) + 1,
                "title": item.issue_title,
                "severity": item.severity,
                "priority_score": item.priority_score,
                "priority_formula_version": item.priority_formula_version,
                "score_contribution": item.priority_components.get("score_contribution"),
                "impact": item.business_impact,
                "effort": item.estimated_effort,
                "responsible_role": item.responsible_role,
                "affected_scope": {
                    "page_count": 1,
                    "requested_url": item.requested_url,
                    "final_url": item.final_url,
                },
                "dependencies": item.evidence_summary.get("dependencies", []),
                "recommended_sequence": len(ranked_actions) + 1,
                "expected_measurable_outcome": item.expected_result,
                "verification_method": item.verification_steps,
                "evidence_references": [_evidence("action_item", item.id)],
                "related_agents": ["evidence_validation_agent", "remediation_agent"],
                "related_finding_ids": related_finding_ids,
                "status": item.status,
            }
        )
    agent_run_by_id = {item.agent_id: item for item in agent_runs}
    agent_summary = [
        {
            "agent_id": agent_id,
            "agent_name": AGENT_DEFINITION_BY_ID[agent_id].name,
            "agent_version": (
                agent_run_by_id[agent_id].agent_version
                if agent_id in agent_run_by_id
                else AGENT_DEFINITION_BY_ID[agent_id].version
            ),
            "status": (
                "not_applicable"
                if agent_id == "repository_intelligence_agent"
                and not workflow.structured_input.get("repository_connection_id")
                # The report agent produces this frozen snapshot: committing the
                # snapshot IS its completion, so a completed immutable report
                # never claims its own report agent is still running.
                else "completed"
                if agent_id == "report_agent"
                and agent_id in agent_run_by_id
                and agent_run_by_id[agent_id].status in {"running", "pending"}
                else agent_run_by_id[agent_id].status
                if agent_id in agent_run_by_id
                else "execution_status_not_recorded"
            ),
            "status_explanation": (
                "Not applicable — no repository connected"
                if agent_id == "repository_intelligence_agent"
                and not workflow.structured_input.get("repository_connection_id")
                else "Completed by producing this immutable report snapshot"
                if agent_id == "report_agent"
                and agent_id in agent_run_by_id
                and agent_run_by_id[agent_id].status in {"running", "pending"}
                else "Execution status was not recorded for this run"
                if agent_id not in agent_run_by_id
                else None
            ),
            "tools_used": _tool_ids(agent_run_by_id.get(agent_id)),
            "evidence_produced": (
                agent_run_by_id[agent_id].evidence_references if agent_id in agent_run_by_id else []
            ),
            "fallback_behavior": (
                "Persisted evidence or deterministic report fallback is used; missing "
                "evidence remains unavailable."
            ),
        }
        for agent_id in AGENT_IDS
    ]

    def section(
        key: str,
        *,
        status: str,
        content: dict[str, Any],
        evidence: list[dict[str, Any]],
        unavailable_reason: str | None = None,
        fallback_behavior: str = (
            "The deterministic fallback uses only persisted evidence and labels missing "
            "capabilities unavailable."
        ),
    ) -> dict[str, Any]:
        return _section(
            key,
            status=status,
            content=content,
            evidence=evidence,
            attribution=_agent_attribution(
                key,
                agent_runs,
                fallback_behavior=fallback_behavior,
                repository_connected=bool(
                    workflow.structured_input.get("repository_connection_id")
                ),
            ),
            unavailable_reason=unavailable_reason,
        )

    final_actions = ranked_actions
    action_gen_status = action_generation.status if action_generation else "not_analysed"
    if not final_actions and all_detailed_findings:
        final_actions = _deterministic_actions_from_findings(all_detailed_findings)
        action_gen_status = "deterministic_from_findings"
    action_plan_available = bool(final_actions) or bool(action_generation)

    sections = [
        section(
            "executive_summary",
            status=summary_status,
            content={
                "generation_mode": "deterministic_fallback",
                "analysis_status": run.status.value,
                "workflow_status": workflow.status,
                "overall_score": overall_score,
                "overall_health": (
                    f"{overall_score}/100"
                    if overall_score is not None
                    else "Unavailable because no grounded score snapshot exists."
                ),
                "strongest_areas": strongest_areas,
                "most_serious_weaknesses": [
                    {
                        "finding_id": item["finding_id"],
                        "title": item["issue_title"],
                        "severity": item["severity"],
                    }
                    for item in serious_findings
                ],
                "weakest_score_areas": weakest_areas,
                "top_business_risks": [
                    {
                        "finding_id": item["finding_id"],
                        "title": item["issue_title"],
                        "impact": item["business_impact"],
                    }
                    for item in serious_findings
                ],
                "top_technical_risks": [
                    {
                        "finding_id": item["finding_id"],
                        "title": item["issue_title"],
                        "impact": item["technical_impact"],
                    }
                    for item in serious_findings
                ],
                "evidence_coverage": {
                    "score_numerator": score.evidence_coverage_numerator if score else 0,
                    "score_denominator": score.evidence_coverage_denominator if score else 0,
                    "score_percentage": score.evidence_coverage_percentage if score else None,
                },
                "score_confidence_percent": score.confidence_percent if score else None,
                "five_most_important_actions": final_actions[:5],
                "quick_wins": [
                    item
                    for item in final_actions
                    if str(item["effort"]).casefold() in {"low", "small", "quick"}
                ][:5],
                "strategic_fixes": [
                    item
                    for item in final_actions
                    if str(item["effort"]).casefold() not in {"low", "small", "quick"}
                ][:5],
                "unavailable_evidence": (
                    diagnostics.partial_completion_metadata
                    if diagnostics
                    else {"site_diagnostics": "unavailable"}
                ),
                "multi_agent_execution_summary": agent_summary,
                "verified_finding_count": len(all_detailed_findings),
                "statement": (
                    "This summary is derived only from retained evidence and execution records."
                    if summary_status == "available"
                    else "No retained evidence is available for an executive summary."
                ),
            },
            evidence=[*result_ref, *score_ref, *finding_refs, *workflow_ref],
            unavailable_reason=(
                None
                if summary_status == "available"
                else "Analysis evidence and score evidence are unavailable."
            ),
        ),
        section(
            "scores",
            status="available" if score else "unavailable",
            content={
                "overall_score": score.overall_score if score else None,
                "categories": (
                    [
                        {
                            "category_id": item.category_id,
                            "score": item.final_score,
                            "band": item.band,
                            "included": item.included,
                            "exclusion_reason": item.exclusion_reason,
                            "evidence_available": item.included and item.final_score is not None,
                            "dedicated_audit_available": _category_has_dedicated_audit(
                                item.category_id,
                                accessibility_available=bool(accessibility),
                                diagnostics_available=bool(diagnostics),
                                performance_available=bool(run.result),
                            ),
                            "score_limitation": _category_score_limitation(
                                item.category_id,
                                score_value=item.final_score,
                                included=item.included,
                                accessibility_available=bool(accessibility),
                                diagnostics_available=bool(diagnostics),
                                performance_available=bool(run.result),
                            ),
                            "contribution": item.contribution,
                            "related_finding_ids": [
                                finding["finding_id"]
                                for finding in all_detailed_findings
                                if str(finding["category"]).casefold()
                                in {
                                    item.category_id.casefold(),
                                    item.category_id.replace("_", "-").casefold(),
                                }
                            ],
                        }
                        for item in score.categories
                    ]
                    if score
                    else []
                ),
                "formula_id": score.formula_id if score else FORMULA_ID,
                "formula_version": score.formula_version if score else FORMULA_VERSION,
                "metric_contributions": (
                    [
                        {
                            "metric_id": item.metric_id,
                            "normalized_value": item.normalized_value,
                            "contribution": item.contribution,
                            "inclusion_status": item.inclusion_status,
                            "evidence_references": item.evidence_references,
                            "related_finding_ids": [
                                finding["finding_id"]
                                for finding in all_detailed_findings
                                if item.metric_id.startswith(
                                    str(finding["category"]).casefold().replace("-", "_")
                                )
                            ],
                        }
                        for item in score.contributions
                    ]
                    if score
                    else []
                ),
                "unavailable_metrics": score.unavailable_metrics if score else [],
                "calculated_by_llm": False,
            },
            evidence=score_ref,
            unavailable_reason=None if score else "No persisted explainable score snapshot exists.",
        ),
        section(
            "performance",
            status="available" if run.result or browser_artifact else "unavailable",
            content={
                "laboratory_evidence_available": bool(
                    run.result and run.result.raw_lighthouse_data
                ),
                "browser_evidence_available": bool(run.result and run.result.raw_playwright_data),
                "field_and_lab_are_distinct": True,
                "http_status_code": run.result.http_status_code if run.result else None,
                "findings": [
                    item
                    for item in detailed_analysis_findings
                    if str(item["category"]).casefold() == "performance"
                ],
                "browser_compatibility": browser_compatibility,
                "browser_engine_tests": bool(browser_artifact),
            },
            evidence=[*result_ref, *browser_refs],
            unavailable_reason=(
                None if run.result or browser_artifact else "Performance evidence was not analysed."
            ),
        ),
        section(
            "accessibility",
            status="available" if accessibility else "unavailable",
            content={
                "audit_count": len(accessibility),
                "completed_audit_count": sum(item.status == "completed" for item in accessibility),
                "violation_count": sum(item.violation_count or 0 for item in accessibility),
                "incomplete_count": sum(item.incomplete_count or 0 for item in accessibility),
                "pass_count": sum(item.pass_count or 0 for item in accessibility),
                "inapplicable_count": sum(item.inapplicable_count or 0 for item in accessibility),
                "count_unit": (
                    "Automated rule results aggregated across audited pages; violations "
                    "contain separately counted element occurrences."
                ),
                "inapplicable_definition": (
                    "Rules whose target condition was not present on the audited page; "
                    "this is not a page count and does not establish accessibility compliance."
                ),
                "automated_checks_establish_compliance": False,
                "manual_review_required": True,
                "findings": detailed_accessibility_findings,
            },
            evidence=accessibility_refs,
            unavailable_reason=(
                None
                if accessibility
                else (
                    "Automated accessibility auditing (axe-core) did not"
                    " produce results for this analysis run. This may be"
                    " because the accessibility agent was unavailable or"
                    " no eligible pages were audited."
                )
            ),
        ),
        section(
            "site_diagnostics",
            status=(
                "available"
                if diagnostics and diagnostics.status == "completed"
                else "incomplete"
                if diagnostics
                else "unavailable"
            ),
            content={
                "execution_status": diagnostics.status if diagnostics else "not_analysed",
                "finding_count": len(diagnostic_findings),
                "coverage": {
                    "processed_pages": diagnostics.processed_page_count if diagnostics else 0,
                    "total_pages": diagnostics.total_page_count if diagnostics else 0,
                    "failed_pages": diagnostics.failed_page_count if diagnostics else 0,
                },
                "findings": detailed_diagnostic_findings,
            },
            evidence=diagnostic_refs,
            unavailable_reason=(
                None if diagnostics else "Site-wide diagnostics were not analysed."
            ),
        ),
        section(
            "internal_link_graph",
            status=("unavailable" if not diagnostics else "available"),
            content={
                "finding_count": len(link_findings),
                "findings": link_findings,
                "link_evidence_partial": any(
                    item["finding_code"] == "unavailable_link_graph_evidence"
                    for item in link_findings
                ),
                "limitations": (
                    "The graph covers bounded persisted discovery evidence"
                    " only; external, mailto, tel, and javascript links"
                    " are excluded."
                    + (
                        " Some pages lack complete internal-link evidence."
                        if any(
                            item["finding_code"] == "unavailable_link_graph_evidence"
                            for item in link_findings
                        )
                        else ""
                    )
                ),
            },
            evidence=diagnostic_refs,
            unavailable_reason=(
                "Site-wide diagnostics were not analysed." if not diagnostics else None
            ),
        ),
        section(
            "canonical_indexability",
            status="available" if diagnostics else "unavailable",
            content={
                "finding_count": len(canonical_findings),
                "findings": canonical_findings,
                "actual_search_engine_indexing_claimed": False,
                "limitations": (
                    "Canonical and indexability conclusions describe technical signals, "
                    "not actual search-engine index inclusion."
                ),
            },
            evidence=diagnostic_refs,
            unavailable_reason=(
                None if diagnostics else "Canonical and indexability evidence was not analysed."
            ),
        ),
        section(
            "security_technical",
            status="available" if run.result else "unavailable",
            content={
                "finding_count": len(technical_findings),
                "findings": technical_findings,
                "zero_findings_means_clean": False,
            },
            evidence=[
                *result_ref,
                *browser_refs,
                *[
                    reference
                    for item in technical_findings
                    for reference in item["evidence_references"]
                ],
            ],
            unavailable_reason=None if run.result else "Technical evidence was not analysed.",
        ),
        section(
            "content_seo",
            status="available" if run.result or diagnostics else "unavailable",
            content={
                "finding_count": len(content_findings),
                "findings": [*content_findings, *diagnostic_content_findings],
                "site_diagnostic_finding_count": sum(
                    item.category.casefold() in {"content", "metadata", "indexability"}
                    for item in diagnostic_findings
                ),
            },
            evidence=[
                *result_ref,
                *diagnostic_refs,
                *[
                    reference
                    for item in content_findings
                    for reference in item["evidence_references"]
                ],
            ],
            unavailable_reason=(
                None if run.result or diagnostics else "Content and SEO evidence were not analysed."
            ),
        ),
        section(
            "page_level_findings",
            status="available" if all_detailed_findings else "unavailable",
            content={
                "finding_count": len(all_detailed_findings),
                "occurrence_count": sum(
                    int(item["occurrence_count"]) for item in all_detailed_findings
                ),
                "findings": all_detailed_findings,
                "occurrences_are_capped": False,
            },
            evidence=[
                *finding_refs,
                *diagnostic_refs,
                *accessibility_refs,
                *browser_refs,
                *tier0_refs,
            ],
            unavailable_reason=(
                None
                if all_detailed_findings
                else "No page-level findings were retained; this is not evidence of no issues."
            ),
        ),
        section(
            "repeated_template_problems",
            status="available" if diagnostics else "unavailable",
            content={
                "finding_count": len(repeated_findings),
                "findings": repeated_findings,
                "template_certainty_limited": True,
                "statement": (
                    "Template labels identify deterministic repeated structure; they do not "
                    "prove source-template ownership."
                ),
            },
            evidence=diagnostic_refs,
            unavailable_reason=(
                None if diagnostics else "Repeated-pattern evidence was not analysed."
            ),
        ),
    ]

    sections_continued = [
        section(
            "priority_action_plan",
            status="available" if action_plan_available else "unavailable",
            content={
                "generation_status": action_gen_status,
                "action_count": len(final_actions),
                "actions": final_actions,
                "ordering": "priority_score_descending_then_stable_id",
                "priority_formula_version": "1.0.0",
            },
            evidence=action_refs,
            unavailable_reason=(
                None
                if action_plan_available
                else "No persisted action-plan generation exists and no findings are available."
            ),
        ),
        section(
            "remediation",
            status=("available" if actions or final_actions else "unavailable"),
            content={
                "guidance": (
                    [
                        {
                            "action_id": str(item.id),
                            "exact_correction": item.exact_correction,
                            "implementation_steps": item.implementation_steps,
                            "verification_steps": item.verification_steps,
                            "responsible_role": item.responsible_role,
                            "estimated_effort_band": item.estimated_effort,
                            "expected_measurable_outcome": item.expected_result,
                            "evidence_references": [_evidence("action_item", item.id)],
                            "limitations": item.limitations,
                        }
                        for item in actions
                    ]
                    if actions
                    else [
                        {
                            "action_id": act["action_id"],
                            "exact_correction": act.get("expected_measurable_outcome", ""),
                            "implementation_steps": act.get("verification_method", ""),
                            "verification_steps": act.get("verification_method", ""),
                            "responsible_role": act.get("responsible_role", "developer"),
                            "estimated_effort_band": act.get("effort", "medium"),
                            "expected_measurable_outcome": act.get(
                                "expected_measurable_outcome", ""
                            ),
                            "evidence_references": act.get("evidence_references", []),
                            "limitations": (
                                "Generated from verified findings using"
                                " deterministic remediation rules."
                            ),
                        }
                        for act in final_actions[:10]
                    ]
                ),
                "narrative_provider": (
                    "persisted_action_items" if actions else "deterministic_from_findings"
                ),
            },
            evidence=action_refs,
            unavailable_reason=(
                None if actions or final_actions else "No grounded remediation guidance exists."
            ),
        ),
        section(
            "coverage_confidence",
            status="available",
            content={
                "score_evidence_coverage_numerator": (
                    score.evidence_coverage_numerator if score else 0
                ),
                "score_evidence_coverage_denominator": (
                    score.evidence_coverage_denominator if score else 5
                ),
                "score_evidence_coverage_percentage": (
                    score.evidence_coverage_percentage if score else None
                ),
                "diagnostic_evidence_coverage": (
                    {
                        "numerator": diagnostics.evidence_coverage_numerator,
                        "denominator": diagnostics.evidence_coverage_denominator,
                        "ratio": diagnostics.evidence_coverage_ratio,
                    }
                    if diagnostics
                    else {
                        "numerator": 0,
                        "denominator": 0,
                        "ratio": None,
                    }
                ),
                "score_confidence_percent": score.confidence_percent if score else None,
                "unavailable_findings": [
                    item
                    for item in all_detailed_findings
                    if item["evidence_state"] == "unavailable"
                ],
                "limitations": [
                    item.message
                    for item in deduplicate_limitations(
                        [
                            {
                                "message": "Unavailable evidence is not represented as passed.",
                                "source": "coverage",
                            },
                            {
                                "message": "Automated accessibility evidence"
                                " cannot prove complete compliance.",
                                "source": "coverage",
                            },
                            {
                                "message": "Laboratory performance evidence is not field evidence.",
                                "source": "coverage",
                            },
                            {
                                "message": "No competitor or search-engine"
                                " ranking comparison is made.",
                                "source": "coverage",
                            },
                        ]
                    )
                ],
            },
            evidence=[*score_ref, *workflow_ref],
        ),
        section(
            "multi_agent_execution",
            status=(
                "available"
                if workflow.status == "completed"
                else "incomplete"
                if workflow.status == "partial"
                else "failed"
                if workflow.status == "failed"
                else "available"
            ),
            content={
                "execution_id": str(workflow.execution_id),
                "workflow_id": workflow.workflow_id,
                "workflow_version": workflow.workflow_version,
                "status": workflow.status,
                "agent_count": len(AGENT_IDS),
                "expected_agent_ids": list(AGENT_IDS),
                "agents": agent_summary,
                "private_reasoning_included": False,
            },
            evidence=workflow_ref,
        ),
        section(
            "methodology_limitations",
            status="available",
            content={
                "overall_score_formula": {
                    "formula_id": FORMULA_ID,
                    "version": FORMULA_VERSION,
                    "unchanged": True,
                },
                "priority_formula": {"version": "1.0.0", "unchanged": True},
                "report_version": REPORT_VERSION,
                "template_id": TEMPLATE_ID,
                "template_version": TEMPLATE_VERSION,
                "llm_calculates_scores": False,
                "business_impact_policy": (
                    "Business impact is shown only when persisted remediation evidence "
                    "supports it; otherwise the report states that it is unquantified."
                ),
                "presentation_limitations": (
                    "PDF is a deterministic evidence snapshot and is not a substitute for "
                    "interactive source evidence."
                ),
                "private_reasoning_included": False,
            },
            evidence=[*score_ref, *workflow_ref],
        ),
    ]
    all_sections = sections + sections_continued
    coverage_section = next(
        (s for s in all_sections if s.get("section_id") == "coverage_confidence"),
        None,
    )
    if coverage_section and isinstance(coverage_section.get("content"), dict):
        available_count = sum(1 for s in all_sections if s.get("status") == "available")
        unavailable_count = sum(1 for s in all_sections if s.get("status") == "unavailable")
        coverage_section["content"]["report_section_coverage"] = {
            "total": len(SECTION_DEFINITIONS),
            "available": available_count,
            "unavailable": unavailable_count,
        }
    return all_sections


def _json_artifact(snapshot: dict[str, Any]) -> bytes:
    return json.dumps(
        snapshot,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _html_value(value: Any) -> str:
    if value is None:
        return "Unavailable"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (dict, list)):
        return html.escape(json.dumps(value, sort_keys=True, ensure_ascii=False))
    return html.escape(str(value))


def _html_url(value: Any, *, max_display: int = 60) -> str:
    if value is None:
        return "Unavailable"
    raw = str(value)
    safe_href = html.escape(raw, quote=True)
    display = raw
    if len(display) > max_display:
        display = display[: max_display - 1] + "…"
    return f'<a href="{safe_href}" title="{safe_href}">{html.escape(display)}</a>'


def _html_label(value: str) -> str:
    return html.escape(value.replace("_", " ").strip().title())


def _first_present(value: dict[str, Any], *keys: str) -> Any:
    return next((value.get(key) for key in keys if value.get(key)), None)


def _html_occurrence_status(item: dict[str, Any]) -> Any:
    return (
        item.get("status_code")
        if item.get("status_code") is not None
        else item.get("collection_status")
    )


def _html_occurrence_table(items: list[dict[str, Any]]) -> str:
    rows = "".join(
        "<tr>"
        f"<td>{_html_url(item.get('normalized_url'))}</td>"
        f"<td>{_html_url(item.get('final_url') or item.get('normalized_url'))}</td>"
        f"<td>{_html_value(_html_occurrence_status(item))}</td>"
        f"<td>{_html_value(item.get('page_type'))}</td>"
        f"<td>{_html_value(_first_present(item, 'selector', 'resource_url', 'location'))}</td>"
        f"<td>{_html_value(item.get('observed_value'))}</td>"
        f"<td>{_html_value(item.get('expected_value'))}</td>"
        f"<td>{_html_value(item.get('analysis_provider'))} "
        f"{_html_value(item.get('analysis_provider_version'))}</td>"
        "</tr>"
        for item in items
    )
    return (
        '<div class="table-wrap"><table class="occurrences">'
        "<caption>Page-level occurrences</caption><thead><tr>"
        '<th scope="col">Page</th><th scope="col">Final URL</th><th scope="col">Status</th>'
        '<th scope="col">Type</th><th scope="col">Location</th>'
        '<th scope="col">Observed</th><th scope="col">Expected</th>'
        '<th scope="col">Provider</th></tr></thead>'
        f"<tbody>{rows}</tbody></table></div>"
    )


_UUID_TEXT_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _html_structured(value: Any, *, key: str = "", depth: int = 0) -> str:
    if value is None or isinstance(value, (str, int, float, bool)):
        if key.endswith("finding_id") and value:
            safe_id = html.escape(str(value))
            return f'<a href="#finding-{safe_id}">Finding detail</a>'
        if isinstance(value, str) and _UUID_TEXT_PATTERN.match(value):
            # Raw internal identifiers are noise in the customer report; full
            # provenance is retained in the JSON export and Technical Appendix.
            return '<span class="muted">Retained internal reference</span>'
        if key in {"detecting_agent", "validating_agent", "agent_id"} and isinstance(value, str):
            definition = AGENT_DEFINITION_BY_ID.get(value)
            return _html_value(definition.name if definition else value.replace("_", " ").title())
        if key in {"category", "category_id"} and isinstance(value, str):
            return _html_label(value)
        if isinstance(value, str) and (key.endswith("_url") or key == "url"):
            return _html_url(value)
        return _html_value(value)
    if isinstance(value, list):
        if not value:
            return '<span class="muted">None retained</span>'
        if all(isinstance(item, dict) and "normalized_url" in item for item in value):
            return _html_occurrence_table(value)
        return (
            '<ol class="structured-list">'
            + "".join(f"<li>{_html_structured(item, depth=depth + 1)}</li>" for item in value)
            + "</ol>"
        )
    if isinstance(value, dict):
        if "finding_id" in value and "issue_title" in value:
            finding_id = html.escape(str(value["finding_id"]))
            severity = html.escape(str(value.get("severity", "unavailable")))
            occurrences = value.get("exact_occurrences", [])
            return (
                f'<article class="finding-card" id="finding-{finding_id}">'
                f'<header><span class="badge severity-{severity}">{severity}</span>'
                f'<span class="badge">{_html_value(value.get("scope"))}</span>'
                f"<h4>{_html_value(value.get('issue_title'))}</h4></header>"
                f"<p>{_html_value(value.get('plain_language_explanation'))}</p>"
                '<dl class="detail-grid">'
                + "".join(
                    f"<dt>{_html_label(field)}</dt>"
                    f"<dd>{_html_structured(value.get(field), key=field, depth=depth + 1)}</dd>"
                    for field in (
                        "technical_explanation",
                        "category",
                        "confidence",
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
                    )
                )
                + "</dl>"
                + (
                    _html_occurrence_table(occurrences)
                    if isinstance(occurrences, list) and occurrences
                    else '<p class="muted">No occurrence evidence retained.</p>'
                )
                + "</article>"
            )
        return (
            '<dl class="detail-grid">'
            + "".join(
                f"<dt>{_html_label(str(item_key))}</dt>"
                f"<dd>{_html_structured(item_value, key=str(item_key), depth=depth + 1)}</dd>"
                for item_key, item_value in sorted(value.items(), key=lambda item: str(item[0]))
            )
            + "</dl>"
        )
    return _html_value(value)


def _html_artifact(snapshot: dict[str, Any]) -> bytes:
    sections = snapshot["sections"]
    section_map: dict[str, dict[str, Any]] = {s["section_key"]: s for s in sections}
    executive = section_map.get("executive_summary", {}).get("content", {})
    scores_content = section_map.get("scores", {}).get("content", {})
    findings_content = section_map.get("page_level_findings", {}).get("content", {})
    action_content = section_map.get("priority_action_plan", {}).get("content", {})

    page_coverage = snapshot.get("page_coverage", {})
    browser_compat = snapshot.get("browser_compatibility", {})
    overall_score = snapshot.get("overall_score")
    confidence = snapshot.get("confidence_percent")
    evidence_cov = snapshot.get("evidence_coverage", {})
    report_quality = snapshot.get("report_quality", "PARTIAL")
    limitations = _client_limitations(snapshot.get("limitations", []))
    product_name = str(snapshot.get("product_name") or CUSTOMER_PRODUCT_NAME)

    grouped_findings = findings_content.get("findings", [])
    category_scores = scores_content.get("categories", [])
    top_problems = executive.get("top_five_problems", [])
    actions = executive.get("top_five_recommended_actions", [])
    if not actions:
        actions = action_content.get("recommendations", [])
    engines = browser_compat.get("engines", [])
    page_inventory = snapshot.get("page_inventory", [])

    score_display = (
        f'<p class="score">{html.escape(str(overall_score))}<span>/100</span></p>'
        if overall_score is not None
        else '<p class="score unavailable">Score unavailable</p>'
    )

    # ---- TOC ----
    toc_items = [
        ("executive-summary", "Executive Summary"),
        ("coverage", "Coverage and Confidence"),
        ("scores", "Overall and Category Scores"),
        ("findings", "Top Findings"),
        ("action-plan", "Priority Action Plan"),
        ("browser-compat", "Browser Compatibility"),
        ("page-summary", "Page Summary"),
        ("limitations", "Key Limitations"),
        ("methodology", "Methodology"),
    ]
    toc_html = "".join(
        f'<li><a href="#{anchor}">{html.escape(title)}</a></li>' for anchor, title in toc_items
    )

    # ---- Executive Summary ----
    exec_summary = executive.get("executive_summary", "")
    strengths = executive.get("strengths", [])
    weaknesses = executive.get("weaknesses", [])
    strengths_html = (
        "".join(f"<li>{_html_value(s)}</li>" for s in strengths[:5])
        if strengths
        else "<li>Not available</li>"
    )
    weaknesses_html = (
        "".join(f"<li>{_html_value(w)}</li>" for w in weaknesses[:5])
        if weaknesses
        else "<li>Not available</li>"
    )

    executive_section = (
        '<section class="report-section" id="executive-summary">'
        "<h2>Executive Summary</h2>"
        f"<p>{_html_value(exec_summary) if exec_summary else 'Executive summary not available.'}"
        "</p>"
        '<div class="summary-grid">'
        f'<div class="summary-card"><h4>Strengths</h4><ul>{strengths_html}</ul></div>'
        f'<div class="summary-card"><h4>Weaknesses</h4><ul>{weaknesses_html}</ul></div>'
        "</div></section>"
    )

    # ---- Coverage ----
    coverage_lines = _coverage_summary_lines(page_coverage)
    coverage_detail_html = "".join(f"<p>{_html_value(line)}</p>" for line in coverage_lines)
    cov_items = [
        ("Discovered URLs", page_coverage.get("total_urls_discovered")),
        ("Eligible pages", page_coverage.get("eligible_pages")),
        ("Analysed", page_coverage.get("successfully_analysed_pages")),
        ("Failed", page_coverage.get("failed_pages")),
        (
            "Evidence coverage",
            f"{evidence_cov.get('numerator', 0)}/{evidence_cov.get('denominator', 0)}",
        ),
        ("Confidence", f"{confidence}%" if confidence is not None else "N/A"),
    ]
    coverage_metrics = "".join(
        f'<div class="metric"><span class="metric-value">{_html_value(val)}</span>'
        f'<span class="metric-label">{_html_value(label)}</span></div>'
        for label, val in cov_items
    )

    coverage_section = (
        '<section class="report-section" id="coverage">'
        "<h2>Coverage and Confidence</h2>"
        f"{coverage_detail_html}"
        f'<div class="metric-grid">{coverage_metrics}</div>'
        "</section>"
    )

    # ---- Scores ----
    category_rows = "".join(
        "<tr>"
        f"<td>{_html_label(str(cs.get('category_id', '')))}</td>"
        f"<td>{cs['score']}/100</td>"
        f"<td>{_html_value(cs.get('exclusion_reason'))}</td>"
        "</tr>"
        if isinstance(cs.get("score"), (int, float)) and cs.get("evidence_available") is not False
        else "<tr>"
        f"<td>{_html_label(str(cs.get('category_id', '')))}</td>"
        "<td>N/A</td>"
        f"<td>{_html_value(cs.get('exclusion_reason') or 'Evidence unavailable')}</td>"
        "</tr>"
        for cs in category_scores
    )

    scores_section = (
        '<section class="report-section" id="scores">'
        "<h2>Overall and Category Scores</h2>"
        f'<p class="score-display">{_html_value(overall_score)}<span>/100</span></p>'
        '<div class="table-wrap"><table>'
        "<caption>Category scores</caption>"
        '<thead><tr><th scope="col">Category</th><th scope="col">Score</th>'
        '<th scope="col">Notes</th></tr></thead>'
        f"<tbody>{category_rows}</tbody></table></div>"
        "</section>"
    )

    # ---- Findings ----
    finding_cards = []
    display_findings = top_problems[:5] if top_problems else grouped_findings[:5]
    for idx, finding in enumerate(display_findings, 1):
        severity = str(finding.get("severity", "unavailable"))
        title = finding.get("title") or finding.get("issue_title") or "Untitled finding"
        affected = finding.get("affected_page_count", 0)
        occurrences = finding.get("occurrence_count", 0)
        explanation = finding.get("plain_language_explanation", "")
        finding_cards.append(
            f'<article class="finding-card">'
            f'<span class="badge severity-{html.escape(severity)}">{html.escape(severity)}</span>'
            f"<h4>{idx}. {_html_value(title)}</h4>"
            + (f"<p>{_html_value(explanation)}</p>" if explanation else "")
            + f"<p class='muted'>{affected} pages · {occurrences} occurrences</p>"
            "</article>"
        )
    findings_section = (
        '<section class="report-section" id="findings">'
        "<h2>Priority Findings</h2>"
        f"<p>{len(grouped_findings)} unique findings total. "
        'The <a href="#findings-register">complete findings register</a> lists '
        "every unique finding.</p>"
        + ("".join(finding_cards) if finding_cards else "<p>No findings retained.</p>")
        + "</section>"
    )

    # ---- Complete Findings Register (every unique finding, compact rows) ----
    severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    register_rows = "".join(
        "<tr>"
        f'<td><span class="badge severity-{html.escape(str(f.get("severity", "unavailable")))}">'
        f"{html.escape(str(f.get('severity', 'unavailable')))}</span></td>"
        f"<td>{_html_value(f.get('title') or f.get('issue_title') or 'Untitled')}</td>"
        f"<td>{_html_label(str(f.get('category', 'general')))}</td>"
        f"<td>{_html_value(f.get('affected_page_count', 0))}</td>"
        f"<td>{_html_value(f.get('occurrence_count') or len(f.get('exact_occurrences') or []))}"
        "</td>"
        f"<td>{_html_value(f.get('recommended_remediation') or f.get('recommendation') or '')}"
        "</td>"
        "</tr>"
        for f in sorted(
            grouped_findings,
            key=lambda f: (
                severity_rank.get(str(f.get("severity", "")).casefold(), 5),
                str(f.get("category", "")),
                str(f.get("title") or f.get("issue_title") or ""),
            ),
        )
    )
    register_section = (
        '<section class="report-section" id="findings-register">'
        "<h2>Complete Findings Register</h2>"
        f"<p>All {len(grouped_findings)} unique findings. Exact occurrences and "
        "evidence for every finding are in the Technical Appendix.</p>"
        '<div class="table-wrap"><table>'
        '<thead><tr><th scope="col">Severity</th><th scope="col">Finding</th>'
        '<th scope="col">Category</th><th scope="col">Pages</th>'
        '<th scope="col">Occurrences</th><th scope="col">Recommended action</th>'
        "</tr></thead>"
        f"<tbody>{register_rows}</tbody></table></div>"
        "</section>"
    )

    # ---- Action Plan ----
    action_items = []
    for idx, action in enumerate(actions[:5], 1):
        action_title = action.get("title") or action.get("recommendation") or "Recommended action"
        impact = action.get("impact") or action.get("business_impact") or ""
        owner = action.get("responsible_role") or "Unassigned"
        effort = action.get("effort") or action.get("estimated_effort") or "Unestimated"
        action_items.append(
            f'<div class="action-item">'
            f"<strong>{idx}. {_html_value(action_title)}</strong>"
            + (f"<p>{_html_value(impact)}</p>" if impact else "")
            + f'<p class="muted">Owner: {_html_value(owner)} · Effort: {_html_value(effort)}</p>'
            "</div>"
        )
    action_section = (
        '<section class="report-section" id="action-plan">'
        "<h2>Priority Action Plan</h2>"
        + ("".join(action_items) if action_items else "<p>No actions available.</p>")
        + "</section>"
    )

    # ---- Browser Compatibility ----
    engine_rows = "".join(
        "<tr>"
        f"<td>{_html_label(str(e.get('engine', '')))}</td>"
        + (
            "<td>Unavailable</td><td colspan='2'>Not represented as passed or failed</td>"
            if e.get("availability_status") == "unavailable"
            else f"<td>{_html_value(e.get('tested_pages'))}"
            f"/{_html_value(e.get('eligible_pages'))}</td>"
            f"<td>{_html_value(e.get('passed_pages', 'N/A'))}</td>"
            f"<td>{_html_value(e.get('failed_pages', 'N/A'))}</td>"
        )
        + "</tr>"
        for e in engines
    )
    browser_uat = browser_compat.get("browser_uat") or {}
    uat_matrix = browser_uat.get("matrix") or browser_compat.get("browser_uat_matrix") or []

    def _uat_row(entry: dict[str, Any]) -> str:
        policy = entry.get("required_version_policy") or entry.get("required_scope")
        platforms = ", ".join(entry.get("required_platforms") or []) or entry.get("platforms")
        state = entry.get("verification_state_label") or entry.get("verification_state")
        return (
            "<tr>"
            f"<td>{_html_value(entry.get('browser'))}</td>"
            f"<td>{_html_value(policy)}</td>"
            f"<td>{_html_value(platforms)}</td>"
            f"<td>{_html_value(state)}</td>"
            "</tr>"
        )

    uat_rows = "".join(_uat_row(entry) for entry in uat_matrix)
    uat_statement = (browser_uat.get("completion") or {}).get("statement") or ""
    uat_block = (
        (
            "<h3>Browser UAT — Required Scope</h3>"
            + (
                f"<p>UAT date: {_html_value(browser_uat.get('uat_date'))}</p>"
                if browser_uat.get("uat_date")
                else ""
            )
            + '<div class="table-wrap"><table>'
            '<thead><tr><th scope="col">Browser</th><th scope="col">Required versions</th>'
            '<th scope="col">Required platforms</th><th scope="col">Verification</th>'
            "</tr></thead>"
            f"<tbody>{uat_rows}</tbody></table></div>"
            + (f"<p>{_html_value(uat_statement)}</p>" if uat_statement else "")
        )
        if uat_matrix
        else ""
    )
    browser_section = (
        '<section class="report-section" id="browser-compat">'
        "<h2>Browser UAT and Engine Diagnostics</h2>"
        + uat_block
        + "<h3>Engine diagnostics (engineering signal only)</h3>"
        "<p>Engine-level evidence from automated tests. "
        "These results reflect browser engine behaviour and are not "
        "equivalent to branded browser (Chrome, Edge, Safari) "
        "verification.</p>"
        "<p>Unavailable engines are not represented as "
        "passed or failed.</p>"
        '<div class="table-wrap"><table>'
        "<caption>Browser engine evidence</caption>"
        '<thead><tr><th scope="col">Engine</th>'
        '<th scope="col">Tested</th>'
        '<th scope="col">Passed</th>'
        '<th scope="col">Failed</th></tr></thead>'
        "<tbody>"
        f"{engine_rows or '<tr><td colspan=4>No browser data</td></tr>'}"
        "</tbody></table></div></section>"
    )

    # ---- Page Summary ----
    eligible_pages = [
        p for p in page_inventory if p.get("resource_classification") == "eligible_html_page"
    ]
    sample_pages = eligible_pages[:20]
    page_rows = "".join(
        "<tr>"
        f"<td>{_html_url(p.get('url'))}</td>"
        f"<td>{_html_value(p.get('analysed'))}</td>"
        f"<td>{_html_value(', '.join(str(e) for e in p.get('browser_engines_tested', [])) or 'None')}</td>"  # noqa: E501
        f"<td>{_html_value(p.get('failure_reason') or p.get('exclusion_reason') or 'None')}</td>"  # noqa: E501
        "</tr>"
        for p in sample_pages
    )
    page_section = (
        '<section class="report-section" id="page-summary">'
        "<h2>Page Summary</h2>"
        f"<p>{len(eligible_pages)} eligible HTML pages. "
        + (f"Showing first {len(sample_pages)}." if len(eligible_pages) > len(sample_pages) else "")
        + "</p>"
        '<div class="table-wrap"><table>'
        "<caption>Eligible page summary</caption>"
        '<thead><tr><th scope="col">URL</th><th scope="col">Analysed</th>'
        '<th scope="col">Browsers</th><th scope="col">Notes</th></tr></thead>'
        f"<tbody>{page_rows or '<tr><td colspan=4>No pages</td></tr>'}</tbody>"
        "</table></div></section>"
    )

    # ---- Limitations ----
    limitation_items = "".join(f"<li>{_html_value(item)}</li>" for item in limitations)
    limitation_section = (
        '<section class="report-section" id="limitations">'
        "<h2>Key Limitations</h2>"
        f"<ul>{limitation_items or '<li>No specific limitations recorded.</li>'}</ul>"
        "</section>"
    )

    # ---- Methodology ----
    methodology_section = (
        '<section class="report-section" id="methodology">'
        "<h2>Methodology</h2>"
        '<dl class="detail-grid">'
        f"<dt>Report quality</dt><dd>{_html_value(report_quality)}</dd>"
        "<dt>Evidence coverage</dt>"
        f"<dd>{evidence_cov.get('numerator', 0)}/{evidence_cov.get('denominator', 0)}</dd>"
        "<dt>Generated</dt>"
        f"<dd>{html.escape(_human_timestamp(snapshot['generated_at']))}</dd>"
        "<dt>Report version</dt>"
        f"<dd>{html.escape(snapshot.get('schema_version', 'Unavailable'))}</dd>"
        "</dl>"
        "<p>Unavailable evidence is identified explicitly. "
        "Automated checks do not establish complete compliance.</p>"
        "</section>"
    )

    # ---- Full sections appendix (for completeness) ----
    appendix_parts = []
    for item in sections:
        if item["section_key"] in {
            "executive_summary",
            "scores",
            "page_level_findings",
            "priority_action_plan",
            "coverage_confidence",
        }:
            continue
        content_rows = "".join(
            "<tr>"
            f'<th scope="row">{_html_label(str(key))}</th>'
            f"<td>{_html_structured(value, key=str(key))}</td>"
            "</tr>"
            for key, value in sorted(item["content"].items())
        )
        appendix_parts.append(
            f'<section class="report-section" id="{html.escape(item["section_key"])}">'
            f"<h2>{html.escape(item['title'])}</h2>"
            f'<p><span class="badge">{html.escape(item["status"])}</span></p>'
            + (
                f'<p role="note">{html.escape(item["unavailable_reason"])}</p>'
                if item["unavailable_reason"]
                else ""
            )
            + f'<div class="table-wrap"><table>'
            f"<tbody>{content_rows}</tbody></table></div>"
            "</section>"
        )

    document = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{html.escape(snapshot['title'])}</title>"
        "<style>"
        ":root{color-scheme:light;--ink:#172033;--brand:#0f172a;--accent:#c94f1d;"
        "--line:#e2e8f0;--soft:#f8fafc;--muted:#64748b}"
        "*{box-sizing:border-box;margin:0;padding:0}"
        "body{font-family:system-ui,-apple-system,Arial,sans-serif;max-width:64rem;"
        "margin:auto;padding:0;line-height:1.6;color:var(--ink);background:#fff}"
        "a{color:#1d4ed8;text-decoration:none}a:hover{text-decoration:underline}"
        "a:focus{outline:3px solid var(--accent);outline-offset:2px}"
        ".cover{min-height:32rem;display:grid;align-content:center;padding:3rem 2.5rem;"
        "color:#fff;background:var(--brand)}"
        ".brand{font-size:.85rem;font-weight:700;letter-spacing:.18em;text-transform:uppercase;"
        "color:#f97316;margin-bottom:1.5rem}"
        ".cover h1{font-size:2.25rem;line-height:1.15;font-weight:800;max-width:28ch;"
        "margin-bottom:1rem}"
        ".score{font-size:3.5rem;font-weight:800;margin:.75rem 0 0}.score span{font-size:1.2rem;"
        "color:#94a3b8}.score.unavailable{font-size:1.5rem;color:#94a3b8}"
        ".meta{display:grid;grid-template-columns:repeat(2,1fr);gap:.75rem 2rem;"
        "margin-top:1.5rem;font-size:.9rem;color:#cbd5e1}"
        ".meta strong{display:block;color:#f8fafc;margin-bottom:.15rem}"
        "main{padding:0 2.5rem 3rem}"
        "nav{padding:2rem 2.5rem;border-bottom:1px solid var(--line)}"
        "nav h2{font-size:1.1rem;margin-bottom:.75rem}nav ol{padding-left:1.5rem}"
        "nav li{margin:.35rem 0;font-size:.9rem}"
        ".report-section{margin:2.5rem 0;padding:2rem 0;border-top:1px solid var(--line)}"
        ".report-section:first-child{margin-top:1.5rem;border-top:none}"
        ".report-section>h2{font-size:1.35rem;font-weight:700;color:var(--brand);"
        "margin-bottom:1rem}"
        ".badge{display:inline-block;border:1px solid currentColor;border-radius:999px;"
        "padding:.15rem .6rem;font-size:.72rem;font-weight:700;text-transform:uppercase}"
        ".severity-critical,.severity-high{color:#dc2626}"
        ".severity-medium{color:#d97706}"
        ".severity-low,.severity-info,.severity-informational{color:#16a34a}"
        ".metric-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(10rem,1fr));"
        "gap:.75rem;margin:1rem 0}"
        ".metric{background:var(--soft);border:1px solid var(--line);border-radius:.5rem;"
        "padding:.75rem 1rem}"
        ".metric-value{display:block;font-size:1.5rem;font-weight:700}"
        ".metric-label{display:block;font-size:.78rem;color:var(--muted);margin-top:.15rem}"
        ".summary-grid{display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin:1rem 0}"
        ".summary-card{background:var(--soft);border:1px solid var(--line);border-radius:.5rem;"
        "padding:1rem}.summary-card h4{font-size:.85rem;text-transform:uppercase;"
        "color:var(--muted);margin-bottom:.5rem}"
        ".summary-card ul{padding-left:1.25rem;font-size:.9rem}"
        ".score-display{font-size:2.5rem;font-weight:800;margin:.5rem 0}"
        ".score-display span{font-size:1rem;color:var(--muted)}"
        ".table-wrap{max-width:100%;overflow-x:auto;margin:.75rem 0}"
        "table{border-collapse:collapse;width:100%}"
        "th,td{padding:.55rem .75rem;border:1px solid var(--line);text-align:left;"
        "vertical-align:top;overflow-wrap:anywhere;word-break:break-word;font-size:.88rem}"
        "th{background:var(--soft);font-weight:600;font-size:.78rem;text-transform:uppercase;"
        "color:var(--muted)}"
        ".detail-grid{display:grid;grid-template-columns:minmax(10rem,14rem) 1fr;margin:.5rem 0}"
        ".detail-grid>dt,.detail-grid>dd{padding:.4rem;margin:0;border-bottom:1px solid #e2e8f0}"
        ".detail-grid>dt{font-weight:600;font-size:.85rem;color:var(--muted)}"
        ".structured-list{padding-left:1.35rem}"
        ".finding-card{margin:1rem 0;padding:1rem 1.25rem;border-left:4px solid var(--accent);"
        "background:var(--soft);border-radius:0 .5rem .5rem 0;break-inside:avoid}"
        ".finding-card h4{margin:.35rem 0 .25rem;font-size:1rem}"
        ".action-item{margin:.75rem 0;padding:1rem;border:1px solid var(--line);"
        "border-radius:.5rem;break-inside:avoid}"
        ".muted{color:var(--muted);font-size:.85rem}"
        "footer{padding:2rem 2.5rem;border-top:1px solid var(--line);"
        "color:var(--muted);font-size:.8rem}"
        ".occurrences{font-size:.82rem}"
        "@media print{@page{size:A4;margin:18mm 14mm}"
        ".cover{break-after:page;border-radius:0;min-height:245mm}"
        ".report-section{break-before:auto;border-top:none;padding-top:1rem}"
        ".finding-card,tr,.action-item{break-inside:avoid}"
        "nav{break-after:page}"
        "body{max-width:none;padding:0}"
        "main{padding:0}.table-wrap{overflow:visible}"
        "th,td{padding:.3rem .5rem;font-size:.75rem}}"
        "@media(max-width:48rem){.meta,.summary-grid{grid-template-columns:1fr}"
        ".metric-grid{grid-template-columns:repeat(2,1fr)}"
        "body{padding:0}main{padding:0 1rem 2rem}nav{padding:1.5rem 1rem}"
        ".cover{padding:2rem 1.5rem}.cover h1{font-size:1.75rem}}"
        "</style></head><body>"
        f'<header class="cover"><p class="brand">{html.escape(product_name)}</p>'
        f"<h1>{html.escape(snapshot['title'])}</h1>"
        f"{score_display}"
        f'<p><span class="badge">{html.escape(report_quality)}</span></p>'
        '<div class="meta">'
        f"<p><strong>Website</strong>{html.escape(snapshot.get('website_name', 'Website'))}"
        f"<br>{html.escape(snapshot.get('website_url', 'Unavailable'))}</p>"
        f"<p><strong>Project</strong>{html.escape(snapshot.get('project_name', 'Unavailable'))}</p>"
        f"<p><strong>Generated</strong>{html.escape(_human_timestamp(snapshot['generated_at']))}</p>"
        f"<p><strong>Quality</strong>{html.escape(report_quality)}</p>"
        "</div></header>"
        f'<nav aria-label="Report sections"><h2>Contents</h2><ol>{toc_html}</ol></nav>'
        f"<main>"
        f"{executive_section}"
        f"{coverage_section}"
        f"{scores_section}"
        f"{findings_section}"
        f"{register_section}"
        f"{action_section}"
        f"{browser_section}"
        f"{page_section}"
        f"{limitation_section}"
        f"{methodology_section}" + ("".join(appendix_parts) if appendix_parts else "") + "</main>"
        "<footer><p><strong>ZuiGO</strong> evidence-grounded report. Unavailable evidence is "
        "identified explicitly. Automated checks do not establish complete compliance.</p>"
        "</footer></body></html>"
    )
    return document.encode("utf-8")


def _pdf_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _pdf_structured_lines(value: Any, *, label: str = "", indent: int = 0) -> list[str]:
    prefix = "  " * indent
    heading = f"{label.replace('_', ' ').title()}: " if label else ""
    if value is None or isinstance(value, (str, int, float, bool)):
        if label in {"detecting_agent", "validating_agent", "agent_id"} and isinstance(value, str):
            definition = AGENT_DEFINITION_BY_ID.get(value)
            value = definition.name if definition else value.replace("_", " ").title()
        elif label in {"category", "category_id"} and isinstance(value, str):
            value = value.replace("_", " ").title()
        rendered = "Unavailable" if value is None else str(value)
        return textwrap.wrap(f"{prefix}{heading}{rendered}", width=88) or [prefix]
    if isinstance(value, list):
        lines = [f"{prefix}{heading}{len(value)} item(s)"]
        for position, item in enumerate(value, 1):
            if isinstance(item, dict) and "issue_title" in item:
                lines.append(
                    f"{prefix}{position}. [{item.get('severity', 'unavailable')}] "
                    f"{item.get('issue_title', 'Untitled finding')}"
                )
                for field in (
                    "finding_id",
                    "category",
                    "scope",
                    "plain_language_explanation",
                    "technical_impact",
                    "business_impact",
                    "recommended_remediation",
                    "responsible_role",
                    "estimated_effort_band",
                    "verification_procedure",
                    "detecting_agent",
                    "validating_agent",
                    "evidence_limitations",
                ):
                    lines.extend(
                        _pdf_structured_lines(
                            item.get(field),
                            label=field,
                            indent=indent + 1,
                        )
                    )
                for occurrence_position, occurrence in enumerate(
                    item.get("exact_occurrences", []), 1
                ):
                    occurrence_location = (
                        _first_present(occurrence, "location", "selector") or "No location"
                    )
                    lines.extend(
                        textwrap.wrap(
                            f"{prefix}  Occurrence {occurrence_position}: "
                            f"{occurrence.get('normalized_url', 'Unavailable')} | "
                            f"{occurrence_location} "
                            f"| observed={occurrence.get('observed_value')} "
                            f"| expected={occurrence.get('expected_value')}",
                            width=88,
                        )
                    )
            else:
                lines.extend(
                    _pdf_structured_lines(
                        item,
                        label=f"item {position}",
                        indent=indent + 1,
                    )
                )
        return lines
    if isinstance(value, dict):
        lines = [f"{prefix}{heading}".rstrip()] if heading else []
        for item_key, item_value in sorted(value.items(), key=lambda item: str(item[0])):
            lines.extend(
                _pdf_structured_lines(
                    item_value,
                    label=str(item_key),
                    indent=indent + (1 if heading else 0),
                )
            )
        return lines
    return textwrap.wrap(f"{prefix}{heading}{value}", width=88) or [prefix]


def _pdf_render_pages(page_text: list[list[str]], snapshot: dict[str, Any]) -> bytes:
    """Render a list of page-line-lists into a raw PDF-1.4 document."""
    page_count = len(page_text)
    font_object_id = 3 + page_count * 2
    bold_font_id = font_object_id + 1
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        font_object_id: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        bold_font_id: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
    }
    page_ids: list[int] = []
    for index, lines in enumerate(page_text):
        page_object_id = 3 + index * 2
        stream_object_id = page_object_id + 1
        page_ids.append(page_object_id)
        header_brand = _pdf_escape(str(snapshot.get("product_name") or CUSTOMER_PRODUCT_NAME))
        commands = [
            "BT",
            "/F1 8 Tf",
            "54 806 Td",
            f"({header_brand}) Tj",
            "ET",
            "BT",
            "/F1 10 Tf",
            "54 780 Td",
            "14 TL",
        ]
        for line in lines:
            safe_line = _pdf_escape(line.encode("latin-1", "replace").decode("latin-1"))
            commands.append(f"({safe_line}) Tj")
            commands.append("T*")
        commands.extend(
            [
                "ET",
                "BT",
                "/F1 8 Tf",
                "54 28 Td",
                f"(Page {index + 1} of {page_count}  |  "
                f"{_pdf_escape(_human_timestamp(snapshot['generated_at']))}) Tj",
                "ET",
            ]
        )
        stream = "\n".join(commands).encode("latin-1")
        objects[page_object_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] "
            f"/Resources << /Font << /F1 {font_object_id} 0 R "
            f"/F2 {bold_font_id} 0 R >> >> "
            f"/Contents {stream_object_id} 0 R >>"
        ).encode()
        objects[stream_object_id] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream"
        )
    objects[2] = (
        f"<< /Type /Pages /Kids [{' '.join(f'{item} 0 R' for item in page_ids)}] "
        f"/Count {page_count} >>"
    ).encode()

    info_object_id = bold_font_id + 1
    objects[info_object_id] = (
        "<< /Title "
        f"({_pdf_escape(snapshot['title'])}) "
        f"/Author ({_pdf_escape(str(snapshot.get('product_name') or CUSTOMER_PRODUCT_NAME))}) "
        "/Subject (Evidence-grounded website analysis report) "
        # Stamp the template version recorded in the immutable snapshot (not the
        # live module constant) so a historical report renders the same bytes
        # even after the code's TEMPLATE_VERSION advances.
        f"/Creator (ZuiGO report template "
        f"{_pdf_escape(str(snapshot.get('template_version', TEMPLATE_VERSION)))}) >>"
    ).encode("latin-1", "replace")
    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for object_id in range(1, info_object_id + 1):
        offsets.append(len(output))
        output.extend(f"{object_id} 0 obj\n".encode())
        output.extend(objects[object_id])
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {info_object_id + 1}\n".encode())
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        (
            f"trailer\n<< /Size {info_object_id + 1} /Root 1 0 R "
            f"/Info {info_object_id} 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode()
    )
    return bytes(output)


def _pdf_paginate(lines: list[str], *, lines_per_page: int = 46) -> list[list[str]]:
    """Split a flat line list into pages."""
    pages: list[list[str]] = []
    for start in range(0, max(len(lines), 1), lines_per_page):
        pages.append(lines[start : start + lines_per_page])
    return pages


_SANITIZER_PLACEHOLDERS = (
    "[PRIVATE REASONING OMITTED]",
    "[REDACTED]",
    "[INTERNAL PATH OMITTED]",
)


def _client_limitations(limitations: list[Any]) -> list[str]:
    """Customer-facing limitation lines: sanitizer placeholders carry no
    customer meaning and are dropped rather than displayed."""
    result = []
    for item in limitations:
        text = str(item)
        if any(marker in text for marker in _SANITIZER_PLACEHOLDERS):
            continue
        result.append(text)
    return result


def _pdf_artifact(snapshot: dict[str, Any]) -> bytes:
    section_map: dict[str, dict[str, Any]] = {s["section_key"]: s for s in snapshot["sections"]}
    executive = section_map.get("executive_summary", {}).get("content", {})
    scores_content = section_map.get("scores", {}).get("content", {})
    findings_content = section_map.get("page_level_findings", {}).get("content", {})

    page_coverage = snapshot.get("page_coverage", {})
    browser_compat = snapshot.get("browser_compatibility", {})
    overall_score = snapshot.get("overall_score")
    evidence_cov = snapshot.get("evidence_coverage", {})
    confidence = snapshot.get("confidence_percent")
    report_quality = snapshot.get("report_quality", "PARTIAL")
    limitations = _client_limitations(snapshot.get("limitations", []))
    product_name = str(snapshot.get("product_name") or CUSTOMER_PRODUCT_NAME)
    finding_totals = snapshot.get("finding_totals") or {}
    completion = snapshot.get("completion") or {}

    grouped_findings = findings_content.get("findings", [])
    category_scores = scores_content.get("categories", [])
    top_problems = executive.get("top_five_problems", [])
    actions = executive.get("top_five_recommended_actions", [])
    if not actions:
        action_section = section_map.get("priority_action_plan", {}).get("content", {})
        actions = action_section.get("recommendations", [])
    engines = browser_compat.get("engines", [])
    total_unique = int(finding_totals.get("total_unique_findings") or len(grouped_findings))
    occurrence_total = int(
        finding_totals.get("occurrence_count")
        or sum(len(item.get("exact_occurrences") or []) for item in grouped_findings)
    )

    # ---- Cover page ----
    cover: list[str] = [
        product_name.upper(),
        "",
        snapshot["title"],
        "",
        f"Website: {snapshot.get('website_name', 'Website')}",
        f"URL: {snapshot.get('website_url', 'Unavailable')}",
        "",
        (
            f"Overall Score: {overall_score}/100"
            if overall_score is not None
            else "Overall Score: Unavailable"
        ),
        f"Report Quality: {report_quality}",
        f"Confidence: {confidence}%" if confidence is not None else "Confidence: N/A",
        f"Evidence Coverage: {evidence_cov.get('numerator', 0)}"
        f"/{evidence_cov.get('denominator', 0)}",
        "",
        f"Generated: {_human_timestamp(snapshot['generated_at'])}",
        "",
        "",
        "CONTENTS",
        "",
        "1. Executive Summary",
        "2. Coverage and Confidence",
        "3. Category Scores",
        "4. Priority Findings",
        "5. Complete Findings Register",
        "6. Priority Action Plan",
        "7. Browser UAT - Required Scope",
        "8. Limitations and Completion",
    ]

    # ---- Executive Summary ----
    exec_lines: list[str] = [
        "1. EXECUTIVE SUMMARY",
        "",
    ]
    exec_summary = executive.get("executive_summary", "")
    if exec_summary:
        exec_lines.extend(textwrap.wrap(str(exec_summary), width=86))
    exec_lines.append("")
    strengths = executive.get("strengths", [])
    if strengths:
        exec_lines.append("Strengths:")
        for s in strengths[:5]:
            exec_lines.extend(textwrap.wrap(f"  + {s}", width=86))
    weaknesses = executive.get("weaknesses", [])
    if weaknesses:
        exec_lines.append("Weaknesses:")
        for w in weaknesses[:5]:
            exec_lines.extend(textwrap.wrap(f"  - {w}", width=86))

    # ---- Coverage ----
    cov_lines: list[str] = [
        "2. COVERAGE AND CONFIDENCE",
        "",
    ]
    cov_lines.extend(_coverage_summary_lines(page_coverage))
    cov_lines.append("")
    for label, value in [
        ("Discovered URLs", page_coverage.get("total_urls_discovered")),
        ("Eligible pages", page_coverage.get("eligible_pages")),
        ("Analysed", page_coverage.get("successfully_analysed_pages")),
        ("Failed", page_coverage.get("failed_pages")),
        (
            "Evidence coverage",
            f"{evidence_cov.get('numerator', 0)}/{evidence_cov.get('denominator', 0)}",
        ),
        ("Confidence", f"{confidence}%" if confidence is not None else "N/A"),
    ]:
        cov_lines.append(f"  {label}: {value if value is not None else 'N/A'}")

    # ---- Scores ----
    score_lines: list[str] = [
        "3. CATEGORY SCORES",
        "",
        (
            f"Overall Score: {overall_score}/100"
            if overall_score is not None
            else "Overall Score: Unavailable"
        ),
        "",
    ]
    for cs in category_scores:
        cat_name = str(cs.get("category_id", "")).replace("_", " ").title()
        if cs.get("evidence_available") is False:
            score_lines.append(f"  {cat_name}: N/A (evidence unavailable)")
        elif isinstance(cs.get("score"), (int, float)):
            score_lines.append(f"  {cat_name}: {cs['score']}/100")
        else:
            score_lines.append(f"  {cat_name}: Unavailable")

    # ---- Priority Findings (prioritized subset with context) ----
    finding_lines: list[str] = [
        "4. PRIORITY FINDINGS",
        "",
        f"Prioritized subset of {total_unique} unique findings "
        f"({occurrence_total} retained occurrences).",
        "The complete findings register follows in section 5.",
        "",
    ]
    display_findings = top_problems[:5] if top_problems else grouped_findings[:5]
    for idx, finding in enumerate(display_findings, 1):
        severity = str(finding.get("severity", "unavailable"))
        title = finding.get("title") or finding.get("issue_title") or "Untitled"
        affected = finding.get("affected_page_count", 0)
        occ_count = finding.get("occurrence_count", 0)
        finding_lines.append(f"{idx}. [{severity.upper()}] {title}")
        finding_lines.append(f"   Pages: {affected}  |  Occurrences: {occ_count}")
        explanation = finding.get("plain_language_explanation", "")
        if explanation:
            finding_lines.extend(textwrap.wrap(f"   {explanation}", width=84))
        occurrences = finding.get("exact_occurrences", [])
        if isinstance(occurrences, list) and occurrences:
            for occ in occurrences[:5]:
                url = occ.get("normalized_url", "N/A")
                if len(str(url)) > 60:
                    url = str(url)[:59] + "..."
                finding_lines.append(f"     - {url}")
            if len(occurrences) > 5:
                finding_lines.append(f"     ... and {len(occurrences) - 5} more")
        finding_lines.append("")

    # ---- Complete Findings Register (every unique finding, compact rows) ----
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    register_findings = sorted(
        grouped_findings,
        key=lambda item: (
            severity_order.get(str(item.get("severity", "")).casefold(), 5),
            str(item.get("category", "")),
            str(item.get("title") or item.get("issue_title") or ""),
        ),
    )
    severity_totals = finding_totals.get("severity_totals") or {}
    register_lines: list[str] = [
        "5. COMPLETE FINDINGS REGISTER",
        "",
        f"All {total_unique} unique findings are listed below. Exact occurrences, "
        "selectors, and measurements for every finding are in the Technical Appendix.",
        "Severity totals: "
        + (
            ", ".join(f"{name} {count}" for name, count in sorted(severity_totals.items()))
            or "unavailable"
        ),
        "",
    ]
    for idx, finding in enumerate(register_findings, 1):
        severity = str(finding.get("severity", "unavailable")).upper()
        title = str(finding.get("title") or finding.get("issue_title") or "Untitled")
        category = str(finding.get("category", "general")).replace("_", " ")
        affected = finding.get("affected_page_count", 0)
        occ_count = finding.get("occurrence_count") or len(finding.get("exact_occurrences") or [])
        register_lines.extend(textwrap.wrap(f"{idx}. [{severity}] {title}", width=86))
        register_lines.append(f"    {category}  |  pages {affected}  |  occurrences {occ_count}")
        remediation = (
            finding.get("recommended_remediation")
            or finding.get("recommendation")
            or finding.get("recommended_next_action")
            or ""
        )
        if remediation:
            wrapped = textwrap.wrap(f"    Action: {remediation}", width=84)
            register_lines.extend(wrapped[:2])
        register_lines.append("")

    # ---- Action Plan (max 5) ----
    action_lines: list[str] = [
        "6. PRIORITY ACTION PLAN",
        "",
    ]
    for idx, action in enumerate(actions[:5], 1):
        action_title = action.get("title") or action.get("recommendation") or "Recommended action"
        owner = action.get("responsible_role") or "Unassigned"
        effort = action.get("effort") or action.get("estimated_effort") or "Unestimated"
        action_lines.extend(textwrap.wrap(f"{idx}. {action_title}", width=86))
        impact = action.get("impact") or action.get("business_impact") or ""
        if impact:
            action_lines.extend(textwrap.wrap(f"   Impact: {impact}", width=84))
        action_lines.append(f"   Owner: {owner}  |  Effort: {effort}")
        action_lines.append("")

    # ---- Browser UAT (locked branded scope) ----
    browser_uat = browser_compat.get("browser_uat") or {}
    uat_matrix = browser_uat.get("matrix") or browser_compat.get("browser_uat_matrix") or []
    uat_completion = browser_uat.get("completion") or {}
    browser_lines: list[str] = [
        "7. BROWSER UAT - REQUIRED SCOPE",
        "",
    ]
    if uat_matrix:
        if browser_uat.get("uat_date"):
            browser_lines.append(f"UAT date: {browser_uat['uat_date']}")
        browser_lines.extend(
            textwrap.wrap(
                "Required scope vs actually verified scope is shown per browser. "
                "Unverified mandatory environments are never counted as passed.",
                width=86,
            )
        )
        browser_lines.append("")
        for entry in uat_matrix:
            browser_lines.append(f"  {entry.get('browser', 'Browser')}")
            required_policy = entry.get("required_version_policy") or entry.get(
                "required_scope", "N/A"
            )
            browser_lines.append(f"    Required: {required_policy}")
            platforms = entry.get("required_platforms") or []
            platform_text = (
                ", ".join(str(item) for item in platforms)
                if isinstance(platforms, list) and platforms
                else str(entry.get("platforms", "N/A"))
            )
            browser_lines.append(f"    Platforms: {platform_text}")
            state_label = (
                entry.get("verification_state_label")
                or entry.get("verification_state")
                or "Not verified"
            )
            browser_lines.append(f"    Verification: {state_label}")
        browser_lines.append("")
        statement = uat_completion.get("statement")
        if statement:
            browser_lines.extend(textwrap.wrap(f"  {statement}", width=84))
    else:
        # Historical snapshots without the branded matrix keep their recorded
        # engine evidence, framed truthfully as engineering signals.
        browser_lines.append("Engine-level evidence (engineering signal only):")
        for engine in engines:
            name = str(engine.get("engine", "unknown")).replace("_", " ").title()
            if engine.get("availability_status") == "unavailable":
                browser_lines.append(f"  {name} engine: Unavailable in this environment")
            else:
                tested = int(engine.get("tested_pages") or 0)
                eligible = int(engine.get("eligible_pages") or 0)
                browser_lines.append(f"  {name} engine: {tested}/{eligible} tested")
        if not engines:
            browser_lines.append("  No browser compatibility data available.")

    # ---- Limitations and Completion ----
    limit_lines: list[str] = [
        "8. LIMITATIONS AND COMPLETION",
        "",
    ]
    completion_statement = completion.get("statement")
    if completion_statement:
        limit_lines.extend(textwrap.wrap(str(completion_statement), width=86))
        limit_lines.append("")
    for item in completion.get("limitation_reasons", []):
        if isinstance(item, dict) and item.get("message"):
            limit_lines.extend(textwrap.wrap(f"  - {item['message']}", width=84))
    if limitations:
        for limitation in limitations:
            limit_lines.extend(textwrap.wrap(f"  - {limitation}", width=84))
    if len(limit_lines) == 2:
        limit_lines.append("  No specific limitations recorded.")

    # ---- Assemble pages ----
    page_text: list[list[str]] = [cover]
    for section_lines in [
        exec_lines,
        cov_lines,
        score_lines,
        finding_lines,
        register_lines,
        action_lines,
        browser_lines,
        limit_lines,
    ]:
        page_text.extend(_pdf_paginate(section_lines))

    return _pdf_render_pages(page_text, snapshot)


def _technical_appendix_pdf(snapshot: dict[str, Any]) -> bytes:
    """Generate the Technical Appendix PDF with all findings, page inventory,
    browser matrices, agent execution, diagnostics, and methodology."""
    sections = snapshot.get("sections", [])
    section_map: dict[str, dict[str, Any]] = {s["section_key"]: s for s in sections}
    findings_content = section_map.get("page_level_findings", {}).get("content", {})
    grouped_findings = findings_content.get("findings", [])
    browser_compat = snapshot.get("browser_compatibility", {})
    page_inventory = snapshot.get("page_inventory", [])
    evidence_cov = snapshot.get("evidence_coverage", {})
    limitations = snapshot.get("limitations", [])
    engines = browser_compat.get("engines", [])

    # ---- Cover ----
    cover: list[str] = [
        str(snapshot.get("product_name") or CUSTOMER_PRODUCT_NAME).upper(),
        "TECHNICAL APPENDIX",
        "",
        snapshot["title"],
        "",
        f"Website: {snapshot.get('website_name', 'Website')}",
        f"Generated: {_human_timestamp(snapshot['generated_at'])}",
        f"Report ID: {snapshot['report_id']}",
        f"Report Version: {snapshot.get('schema_version', 'Unavailable')}",
        "",
        "This appendix contains complete technical details, all findings,",
        "exact URLs and occurrences, page inventory, browser matrices,",
        "agent execution logs, and methodology information.",
    ]

    # ---- All Findings (complete) ----
    finding_lines: list[str] = [
        "ALL FINDINGS",
        f"{len(grouped_findings)} unique findings",
        "",
    ]
    for idx, finding in enumerate(grouped_findings, 1):
        finding_lines.append(
            f"{idx}. [{str(finding.get('severity', 'unavailable')).upper()}] "
            f"{finding.get('issue_title', 'Untitled')}"
        )
        for field in (
            "finding_id",
            "category",
            "scope",
            "plain_language_explanation",
            "technical_impact",
            "business_impact",
            "recommended_remediation",
            "responsible_role",
            "estimated_effort_band",
            "verification_procedure",
            "detecting_agent",
            "validating_agent",
            "evidence_limitations",
        ):
            finding_lines.extend(_pdf_structured_lines(finding.get(field), label=field, indent=1))
        occurrences = finding.get("exact_occurrences", [])
        if isinstance(occurrences, list) and occurrences:
            finding_lines.append(f"  Occurrences ({len(occurrences)}):")
            for occ_idx, occ in enumerate(occurrences, 1):
                url = occ.get("normalized_url", "N/A")
                location = _first_present(occ, "location", "selector") or "No location"
                finding_lines.extend(
                    textwrap.wrap(
                        f"    {occ_idx}. {url} | {location} "
                        f"| observed={occ.get('observed_value')} "
                        f"| expected={occ.get('expected_value')}",
                        width=86,
                    )
                )
        finding_lines.append("")

    # ---- Page Inventory ----
    eligible = [
        p for p in page_inventory if p.get("resource_classification") == "eligible_html_page"
    ]
    inventory_lines: list[str] = [
        "PAGE INVENTORY",
        f"{len(eligible)} eligible HTML pages, {len(page_inventory)} total URLs",
        "",
    ]
    for p in eligible:
        url = str(p.get("url", ""))
        if len(url) > 70:
            url = url[:69] + "..."
        analysed = "Yes" if p.get("analysed") else "No"
        result = str(p.get("result", "unknown"))
        browsers = ", ".join(str(e) for e in p.get("browser_engines_tested", [])) or "None"
        inventory_lines.append(f"  {url}")
        inventory_lines.append(
            f"    Analysed: {analysed}  |  Result: {result}  |  Browsers: {browsers}"
        )
        reason = p.get("failure_reason") or p.get("exclusion_reason")
        if reason:
            inventory_lines.extend(textwrap.wrap(f"    Reason: {reason}", width=84))

    # ---- Browser Matrix ----
    browser_lines: list[str] = [
        "BROWSER ENGINE EVIDENCE MATRIX",
        "(Engine-level evidence — not branded browser verification)",
        "",
    ]
    for engine in engines:
        name = str(engine.get("engine", "")).replace("_", " ").title()
        label = f"{name} engine"
        if engine.get("availability_status") == "unavailable":
            browser_lines.append(f"  {label}: UNAVAILABLE")
        else:
            tested = int(engine.get("tested_pages") or 0)
            elig = int(engine.get("eligible_pages") or 0)
            passed = int(engine.get("passed_pages") or 0)
            partial = int(engine.get("partial_pages") or 0)
            failed = int(engine.get("failed_pages") or 0)
            browser_lines.append(
                f"  {label}: {tested}/{elig} tested | "
                f"Passed: {passed} | Partial: {partial} | Failed: {failed}"
            )
    matrix = browser_compat.get("matrix", [])
    if matrix:
        browser_lines.append("")
        browser_lines.append("  Page-level browser matrix:")
        for entry in matrix[:50]:
            page_url = entry.get("page_url", "")
            if len(str(page_url)) > 50:
                page_url = str(page_url)[:49] + "..."
            result = entry.get("result", "not_tested")
            issues = entry.get("issue_count", 0)
            browser_lines.append(f"    {page_url} | {result} | {issues} issues")

    # ---- Agent Execution ----
    agent_content = section_map.get("multi_agent_execution", {}).get("content", {})
    agents = agent_content.get("agents", [])
    agent_lines: list[str] = [
        "AGENT EXECUTION",
        "",
    ]
    for ag in agents:
        agent_id = str(ag.get("agent_id", ""))
        definition = AGENT_DEFINITION_BY_ID.get(agent_id)
        name = definition.name if definition else agent_id.replace("_", " ").title()
        status = ag.get("status", "not recorded")
        evidence_count = len(ag.get("evidence_produced", []))
        agent_lines.append(f"  {name}")
        agent_lines.append(f"    Status: {status} | Evidence: {evidence_count} references")
        explanation = ag.get("status_explanation")
        if explanation:
            agent_lines.extend(textwrap.wrap(f"    {explanation}", width=84))
    unavailable_tools = agent_content.get("unavailable_capabilities", [])
    if unavailable_tools:
        agent_lines.append(f"  Unavailable tools: {', '.join(str(t) for t in unavailable_tools)}")

    # ---- Diagnostics (remaining sections) ----
    diag_lines: list[str] = ["ADDITIONAL SECTION DETAILS", ""]
    for item in sections:
        if item["section_key"] in {
            "executive_summary",
            "scores",
            "page_level_findings",
            "priority_action_plan",
            "coverage_confidence",
            "multi_agent_execution",
        }:
            continue
        diag_lines.append(f"--- {item['title']} ---")
        diag_lines.append(f"Status: {item['status']}")
        if item["unavailable_reason"]:
            diag_lines.extend(textwrap.wrap(item["unavailable_reason"], width=86))
        for key, value in sorted(item["content"].items()):
            diag_lines.extend(_pdf_structured_lines(value, label=key))
        diag_lines.append("")

    # ---- Methodology ----
    method_lines: list[str] = [
        "METHODOLOGY AND VERSIONS",
        "",
        f"Report ID: {snapshot['report_id']}",
        f"Report Version: {snapshot.get('schema_version', 'Unavailable')}",
        f"Template Version: {snapshot.get('template_version', 'Unavailable')}",
        f"Quality: {snapshot.get('report_quality', 'PARTIAL')}",
        "Evidence Coverage: "
        f"{evidence_cov.get('numerator', 0)}/{evidence_cov.get('denominator', 0)}",
        "",
    ]
    if limitations:
        method_lines.append("All Limitations:")
        for lim in limitations:
            method_lines.extend(textwrap.wrap(f"  - {lim}", width=84))

    # ---- Section evidence references ----
    ref_lines: list[str] = ["EVIDENCE REFERENCES", ""]
    for item in sections:
        if item["evidence_references"]:
            ref_lines.append(f"{item['title']}:")
            for ref in item["evidence_references"]:
                ref_lines.append(f"  - {ref['evidence_type']}:{ref['evidence_id']}")
            ref_lines.append("")

    # ---- Assemble ----
    page_text: list[list[str]] = [cover]
    for section_lines in [
        finding_lines,
        inventory_lines,
        browser_lines,
        agent_lines,
        diag_lines,
        method_lines,
        ref_lines,
    ]:
        page_text.extend(_pdf_paginate(section_lines))

    return _pdf_render_pages(page_text, snapshot)


REAL_PRESENTATION_TITLES = (
    "Cover",
    "Executive Summary",
    "Website Scan Coverage",
    "Browser Compatibility",
    "Overall and Category Scores",
    "Top 10 Priority Findings",
    "Performance Summary",
    "Accessibility Summary",
    "SEO and Content Summary",
    "Technical and Security Summary",
    "Page-Level Problem Summary",
    "Priority Action Plan",
    "Evidence Coverage and Limitations",
    "Compact Multi-Agent Summary",
    "Conclusion",
)


def _section_content(
    snapshot: dict[str, Any],
    section_key: str,
) -> dict[str, Any]:
    section = next(
        (item for item in snapshot.get("sections", []) if item.get("section_key") == section_key),
        None,
    )
    return section.get("content", {}) if section else {}


def _coverage_summary_lines(coverage: dict[str, Any]) -> list[str]:
    completeness = coverage.get("discovery_completeness")
    stage = coverage.get("discovery_stage_status")
    _PENDING_STAGES = {"queued", "pending", "initializing", "not_started"}
    if completeness:
        completeness_label = str(completeness).replace("_", " ").title()
    elif stage == "running":
        completeness_label = "In Progress"
    elif stage in _PENDING_STAGES:
        completeness_label = "Pending"
    else:
        completeness_label = "Not Available"
    numerator = int(coverage.get("coverage_numerator") or 0)
    denominator = int(coverage.get("coverage_denominator") or 0)
    percentage = coverage.get("analysed_page_coverage_percentage")
    percentage_str = f"{percentage}%" if percentage is not None else "N/A"
    lines = [
        f"Discovery completeness: {completeness_label}",
        (
            f"Analysed-page coverage: {numerator}/{denominator} discovered eligible "
            f"page(s) ({percentage_str})."
        ),
    ]
    if completeness == "complete":
        lines.append(f"Full-site coverage: {percentage_str} of eligible HTML pages.")
    elif completeness is None:
        lines.append(
            coverage.get("discovery_completeness_message")
            or "Full-site coverage will be evaluated after discovery completes."
        )
    else:
        lines.append(
            coverage.get("discovery_completeness_message")
            or "Full-site coverage: Not established because website discovery was incomplete."
        )
        if coverage.get("discovery_failure_message"):
            lines.append(f"Discovery limitation: {coverage['discovery_failure_message']}")
    return lines


def _presentation_lines(
    snapshot: dict[str, Any],
    title: str,
) -> list[str]:
    coverage = snapshot.get("page_coverage", {})
    browser = snapshot.get("browser_compatibility", {})
    findings = _section_content(snapshot, "page_level_findings").get("findings", [])
    actions = _section_content(snapshot, "priority_action_plan").get("actions", [])
    if title == "Executive Summary":
        return [
            f"Website: {snapshot.get('website_name')} - {snapshot.get('normalized_url')}",
            f"Overall score: {snapshot.get('overall_score')}/100"
            if snapshot.get("overall_score") is not None
            else "Overall score: unavailable because grounded score evidence is incomplete.",
            *_coverage_summary_lines(coverage),
            "Browser engines tested: "
            + ", ".join(
                item.get("label", item.get("engine", "Unknown engine"))
                for item in browser.get("engines", [])
            ),
            *[
                f"Priority problem: {item.get('issue_title')} - {item.get('business_impact')}"
                for item in findings[:5]
            ],
            *[
                f"Priority action {item.get('priority_rank')}: {item.get('title')}"
                for item in actions[:5]
            ],
            "Unavailable evidence is explicitly identified and is never treated as passed.",
        ]
    if title == "Website Scan Coverage":
        labels = (
            ("Discovered", "total_urls_discovered"),
            ("Scheduled", "total_pages_scheduled"),
            ("Visited", "total_pages_visited"),
            ("Analysed", "analysed_pages"),
            ("Successfully analysed", "successfully_analysed_pages"),
            ("Failed", "failed_pages"),
            ("Skipped", "skipped_pages"),
            ("Excluded", "excluded_pages"),
            ("Redirected", "redirected_pages"),
            ("Duplicate-normalised", "duplicate_normalized_pages"),
            ("Incomplete evidence", "pages_with_incomplete_evidence"),
        )
        return [
            *[f"{label}: {coverage.get(key, 0)}" for label, key in labels],
            *_coverage_summary_lines(coverage),
            f"Started: {coverage.get('started_at') or 'Unavailable'}",
            f"Completed: {coverage.get('completed_at') or 'Unavailable'}",
            f"Duration: {coverage.get('duration_seconds') or 'Unavailable'} seconds",
        ]
    if title == "Browser Compatibility":
        uat = browser.get("browser_uat") or {}
        uat_matrix = uat.get("matrix") or browser.get("browser_uat_matrix") or []
        if uat_matrix:
            lines = ["Browser UAT required scope vs actually verified scope:"]
            for item in uat_matrix:
                state = (
                    item.get("verification_state_label")
                    or item.get("verification_state")
                    or "Not verified"
                )
                lines.append(
                    f"{item.get('browser')}: "
                    f"{item.get('required_version_policy') or item.get('required_scope')} - {state}"
                )
            statement = (uat.get("completion") or {}).get("statement")
            if statement:
                lines.append(statement)
            lines.append(
                "Engine-level execution is retained as an engineering signal in "
                "the Technical Appendix."
            )
            return lines
        lines = [
            "These are Playwright browser-engine tests, not claims about every branded version.",
            f"Status: {browser.get('status', 'unavailable')}",
        ]
        lines.extend(
            (
                f"{item.get('engine')}: {item.get('tested_pages', 0)}/"
                f"{item.get('eligible_pages', 0)} pages "
                + (
                    f"({item.get('percentage')}%)"
                    if item.get("percentage") is not None
                    else "(coverage unavailable)"
                )
            )
            for item in browser.get("engine_coverage", [])
        )
        lines.extend(
            (
                f"{item.get('page_title') or item.get('page_url')}: "
                f"{str(item.get('result', 'not_tested')).replace('_', ' ')}; "
                f"{item.get('issue_count', 0)} issue(s)"
            )
            for item in browser.get("matrix", [])[:10]
        )
        return lines or ["Browser-engine evidence is unavailable."]
    if title == "Overall and Category Scores":
        scores = _section_content(snapshot, "scores")
        return [
            f"Overall score: {scores.get('overall_score')}/100"
            if scores.get("overall_score") is not None
            else "Overall score: unavailable",
            *[
                f"{item.get('category_id')}: {item.get('score')}/100"
                for item in scores.get("categories", [])
                if item.get("score") is not None
            ],
            f"Formula version: {scores.get('formula_version', FORMULA_VERSION)} (unchanged)",
        ]
    if title == "Top 10 Priority Findings":
        return [
            f"{index}. [{str(item.get('severity', '')).upper()}] "
            f"{item.get('issue_title')} - {item.get('affected_page_count')} page(s). "
            f"{item.get('recommended_remediation')}"
            for index, item in enumerate(findings[:10], 1)
        ] or ["No retained finding evidence is available."]
    section_map = {
        "Performance Summary": "performance",
        "Accessibility Summary": "accessibility",
        "SEO and Content Summary": "content_seo",
        "Technical and Security Summary": "security_technical",
    }
    if title in section_map:
        content = _section_content(snapshot, section_map[title])
        values = content.get("findings", [])
        return [
            f"[{str(item.get('severity', '')).upper()}] {item.get('issue_title')}: "
            f"{item.get('why_it_matters') or item.get('technical_impact')}"
            for item in values[:8]
        ] or ["Evidence was unavailable or no finding record was retained."]
    if title == "Page-Level Problem Summary":
        return [
            f"{item.get('issue_title')}: {item.get('affected_page_count')} page(s), "
            f"{item.get('occurrence_count')} occurrence(s); "
            + ", ".join(
                occurrence.get("normalized_url", "")
                for occurrence in item.get("exact_occurrences", [])[:3]
            )
            for item in findings[:10]
        ] or ["No page-level finding record was retained."]
    if title == "Priority Action Plan":
        return [
            f"{item.get('priority_rank')}. {item.get('title')} - "
            f"owner: {item.get('responsible_role')}; "
            f"verify: {item.get('verification_method')}"
            for item in actions[:10]
        ] or ["No evidence-grounded action plan is available."]
    if title == "Evidence Coverage and Limitations":
        return [
            *_coverage_summary_lines(coverage),
            *snapshot.get("limitations", []),
            *browser.get("limitations", []),
        ]
    if title == "Compact Multi-Agent Summary":
        agents = _section_content(snapshot, "multi_agent_execution").get("agents", [])
        return [
            f"{str(item.get('agent_id', '')).replace('_', ' ').title()}: "
            f"{item.get('status')}; evidence records "
            f"{len(item.get('evidence_produced', []))}"
            for item in agents
        ]
    if title == "Conclusion":
        return [
            (
                f"The analysis retained {len(findings)} finding(s) from "
                f"{coverage.get('coverage_numerator', 0)}/"
                f"{coverage.get('coverage_denominator', 0)} successfully analysed "
                "discovered eligible pages."
            ),
            "Complete the highest-priority actions, then create an independent reanalysis.",
            "No prepared-demo evidence is included in this report.",
        ]
    return []


def _real_presentation_pdf(snapshot: dict[str, Any]) -> bytes:
    from reportlab.lib.colors import HexColor
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen.canvas import Canvas

    output = BytesIO()
    pdf = Canvas(output, pagesize=A4, pageCompression=1, invariant=1)
    width, height = A4
    for page_number, title in enumerate(REAL_PRESENTATION_TITLES, 1):
        if page_number == 1:
            pdf.setFillColor(HexColor("#123A63"))
            pdf.rect(0, 0, width, height, fill=1, stroke=0)
            pdf.setFillColor(HexColor("#FFFFFF"))
            pdf.setFont("Helvetica-Bold", 25)
            pdf.drawString(50, height - 120, "Website Analysis")
            pdf.drawString(50, height - 154, "Presentation Report")
            pdf.setFont("Helvetica", 12)
            pdf.drawString(
                50,
                height - 205,
                str(snapshot.get("website_name") or "Website")[:75],
            )
            pdf.drawString(
                50,
                height - 225,
                str(snapshot.get("normalized_url") or snapshot.get("website_url"))[:85],
            )
        else:
            pdf.setFillColor(HexColor("#123A63"))
            pdf.rect(0, height - 48, width, 48, fill=1, stroke=0)
            pdf.setFillColor(HexColor("#172033"))
            pdf.setFont("Helvetica-Bold", 18)
            pdf.drawString(48, height - 82, title)
            pdf.setStrokeColor(HexColor("#C94F1D"))
            pdf.setLineWidth(2)
            pdf.line(48, height - 92, width - 48, height - 92)
            y = height - 116
            pdf.setFont("Helvetica", 9)
            for raw_line in _presentation_lines(snapshot, title):
                for line in textwrap.wrap(str(raw_line), width=100) or [""]:
                    if y < 55:
                        break
                    pdf.drawString(48, y, line)
                    y -= 13
                y -= 3
        pdf.setFont("Helvetica", 8)
        pdf.drawRightString(
            width - 45,
            24,
            f"Page {page_number} of {len(REAL_PRESENTATION_TITLES)}",
        )
        pdf.showPage()
    pdf.setTitle(f"{snapshot.get('website_name') or 'Website'} analysis presentation")
    pdf.setAuthor(str(snapshot.get("product_name") or CUSTOMER_PRODUCT_NAME))
    pdf.setSubject("Evidence-grounded real website analysis")
    pdf.save()
    content = output.getvalue()
    output.close()
    return content


def render_additional_report_artifact(
    artifact_format: str,
    snapshot: dict[str, Any],
) -> tuple[bytes, str, str]:
    safe_snapshot = sanitize_persisted_value(snapshot)
    report_id = uuid.UUID(str(safe_snapshot["report_id"]))
    website_name = str(safe_snapshot.get("website_name") or "website-report")
    if artifact_format == "pdf":
        return (
            _pdf_artifact(safe_snapshot),
            "application/pdf",
            _safe_filename(website_name, report_id, "report.pdf"),
        )
    if artifact_format == "presentation_pdf":
        return (
            _real_presentation_pdf(safe_snapshot),
            "application/pdf",
            _safe_filename(website_name, report_id, "presentation.pdf"),
        )
    if artifact_format == "technical_appendix":
        return (
            _technical_appendix_pdf(safe_snapshot),
            "application/pdf",
            _safe_filename(website_name, report_id, "technical-appendix.pdf"),
        )
    if artifact_format == "page_inventory":
        return (
            json.dumps(
                safe_snapshot.get("page_inventory", []),
                sort_keys=True,
                separators=(",", ":"),
            ).encode(),
            "application/json",
            _safe_filename(website_name, report_id, "page-inventory.json"),
        )
    raise ValueError("Unsupported additional report format.")


def render_report_artifact(artifact_format: str, snapshot: dict[str, Any]) -> bytes:
    safe_snapshot = sanitize_persisted_value(snapshot)
    if artifact_format == "json":
        return _json_artifact(safe_snapshot)
    if artifact_format == "html":
        return _html_artifact(safe_snapshot)
    if artifact_format == "pdf":
        return _pdf_artifact(safe_snapshot)
    raise ValueError(f"Unsupported report format: {artifact_format}")


def generate_report(
    db: Session,
    run_id: uuid.UUID,
    *,
    idempotency_key: str,
    workflow_execution_id: uuid.UUID | None = None,
    report_type: str = "full_analysis",
    allow_active_workflow: bool = False,
) -> tuple[ReportExecution, bool]:
    normalized_key = idempotency_key.strip()
    if not normalized_key:
        raise ReportDeliveryError(
            "INVALID_IDEMPOTENCY_KEY", "Idempotency key cannot be empty.", 422
        )
    run = _loaded_run(db, run_id)
    workflow = _workflow_or_raise(
        db,
        run,
        workflow_execution_id,
        allow_active_workflow=allow_active_workflow,
    )
    score = _latest_score(db, run.id)
    sections = _build_sections(db, run, workflow, score)
    real_evidence = _real_evidence_summary(db, run, workflow, sections)
    section_by_key = {section["section_key"]: section for section in sections}
    page_coverage = real_evidence["page_coverage"]
    browser_compatibility = real_evidence["browser_compatibility"]
    finding_content = section_by_key["page_level_findings"]["content"]
    grouped_findings = finding_content.get("findings", [])
    eligible_urls = {
        str(item["url"])
        for item in real_evidence["page_inventory"]
        if item.get("resource_classification") == "eligible_html_page"
    }
    all_affected_urls = {
        str(occurrence.get("normalized_url"))
        for finding in grouped_findings
        for occurrence in finding.get("exact_occurrences", [])
        if occurrence.get("normalized_url")
    }
    affected_eligible_count = reconcile_affected_pages(grouped_findings, eligible_urls)
    finding_content.update(
        {
            "unique_finding_count": len(grouped_findings),
            "total_occurrence_count": sum(
                int(item.get("occurrence_count") or 0) for item in grouped_findings
            ),
            "affected_page_count": affected_eligible_count,
            "affected_total_count": len(all_affected_urls),
            "page_inventory": real_evidence["page_inventory"],
        }
    )
    executive = section_by_key["executive_summary"]["content"]
    score_content = section_by_key["scores"]["content"]
    executive.update(
        {
            "website_analysed": real_evidence["normalized_url"],
            "analysis_date": (
                workflow.completed_at.isoformat()
                if workflow.completed_at
                else run.completed_at.isoformat()
                if run.completed_at
                else run.updated_at.isoformat()
            ),
            "page_coverage": page_coverage,
            "browser_coverage": [
                {
                    "engine": item.get("engine"),
                    "tested_pages": int(item.get("tested_pages") or 0),
                    "eligible_pages": int(item.get("eligible_pages") or 0),
                    "availability_status": item.get("availability_status", "available"),
                }
                for item in browser_compatibility.get("engines", [])
            ],
            "category_scores": score_content.get("categories", []),
            "top_five_problems": [
                {
                    "title": item["issue_title"],
                    "severity": item["severity"],
                    "affected_page_count": item["affected_page_count"],
                    "occurrence_count": item["occurrence_count"],
                }
                for item in grouped_findings
                if item["severity"] in {"critical", "high"}
            ][:5],
            "top_five_recommended_actions": executive.get("five_most_important_actions", [])[:5],
            "important_limitations": [
                item.message
                for item in deduplicate_limitations(
                    [
                        *(
                            [
                                {
                                    "message": (
                                        "Website discovery was incomplete, so full-site "
                                        "coverage is not established. "
                                        f"{page_coverage.get('discovery_failure_message') or ''}"
                                    ).strip(),
                                    "source": "discovery",
                                }
                            ]
                            if page_coverage["discovery_completeness"] != "complete"
                            else []
                        ),
                        *(
                            [
                                {
                                    "message": (
                                        f"{page_coverage['not_scheduled_pages']} eligible "
                                        "pages were not scheduled for analysis."
                                    ),
                                    "source": "page_coverage",
                                }
                            ]
                            if page_coverage["not_scheduled_pages"]
                            else []
                        ),
                        *(
                            [
                                {
                                    "message": (
                                        "Some advanced data sources were unavailable. "
                                        "Core page analysis completed."
                                    ),
                                    "source": "evidence",
                                }
                            ]
                            if any(
                                section["status"] == "unavailable"
                                for section in sections
                                if section["section_key"]
                                not in {"executive_summary", "page_level_findings"}
                            )
                            else []
                        ),
                        {
                            "message": (
                                "Evidence completeness and website page coverage "
                                "are separate measures."
                            ),
                            "source": "methodology",
                        },
                    ]
                )
            ],
        }
    )
    section_by_key["coverage_confidence"]["content"].update(
        {
            "website_page_coverage": page_coverage,
            "evidence_completeness_definition": (
                "Required evidence groups available; this is not website page coverage."
            ),
        }
    )
    coverage_limitation_ids = {
        _assign_limitation_id(msg)
        for msg in section_by_key["coverage_confidence"]["content"].get("limitations", [])
    }
    executive["important_limitations"] = [
        msg
        for msg in executive.get("important_limitations", [])
        if _assign_limitation_id(msg) not in coverage_limitation_ids
    ]
    evidence_references = sorted(
        {
            canonical_json(reference): reference
            for section in sections
            for reference in section["evidence_references"]
        }.values(),
        key=canonical_json,
    )
    evidence_input = {
        "analysis_run_id": str(run.id),
        "analysis_updated_at": run.updated_at.isoformat(),
        "workflow_execution_id": str(workflow.execution_id),
        "workflow_status": workflow.status,
        "score_execution_id": str(score.execution_id) if score else None,
        "report_type": report_type,
        "report_version": REPORT_VERSION,
        "template_id": TEMPLATE_ID,
        "template_version": TEMPLATE_VERSION,
        "sections": sections,
        "real_evidence": real_evidence,
        "evidence_references": evidence_references,
    }
    input_fingerprint = fingerprint(evidence_input)
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
            ReportExecution.idempotency_key == normalized_key,
        )
    )
    if existing is not None:
        if existing.input_fingerprint != input_fingerprint:
            raise ReportDeliveryError(
                "REPORT_IDEMPOTENCY_CONFLICT",
                "The idempotency key is already associated with different report evidence.",
                409,
            )
        return existing, False

    report_id = uuid.uuid4()
    generated_at = datetime.now(UTC)
    unavailable = [
        section["section_key"]
        for section in sections
        if section["status"] in {"unavailable", "excluded"}
    ]
    numerator = len(sections) - len(unavailable)
    denominator = len(sections)
    coverage = round(numerator / denominator * 100, 2) if denominator else None
    formula_confidence = (
        score.confidence_percent if score else run.score.confidence_percent if run.score else None
    )
    page_confidence = page_coverage.get("coverage_percentage")
    _discovery_completeness = page_coverage.get("discovery_completeness")
    discovery_confidence = (
        {
            "complete": 100,
            "partial": 50,
            "failed": 0,
            "inconclusive": 0,
        }.get(str(_discovery_completeness))
        if _discovery_completeness is not None
        else None
    )
    available_engines = [
        item
        for item in browser_compatibility.get("engines", [])
        if item.get("availability_status") != "unavailable"
    ]
    browser_eligible_pages = int(browser_compatibility.get("eligible_page_count") or 0)
    browser_expected_attempts = browser_eligible_pages * len(available_engines)
    browser_tested_attempts = sum(int(item.get("tested_pages") or 0) for item in available_engines)
    browser_confidence = (
        round(browser_tested_attempts / browser_expected_attempts * 100, 2)
        if browser_expected_attempts
        else None
    )
    confidence_components = {
        "formula_determinism_percent": formula_confidence,
        "evidence_completeness_percent": coverage,
        "analysed_page_coverage_percent": page_confidence,
        "full_site_coverage_confidence_percent": discovery_confidence,
        "browser_coverage_percent": browser_confidence,
    }
    confidence_values = [
        float(value) for value in confidence_components.values() if value is not None
    ]
    report_confidence = int(min(confidence_values)) if confidence_values else None
    confidence_explanation = (
        "The score formula is deterministic, while report confidence is limited by the "
        "least complete of discovery completeness, retained evidence, eligible-page "
        "analysis, and requested browser-engine coverage."
    )
    executive.update(
        {
            "confidence_components": confidence_components,
            "confidence_explanation": confidence_explanation,
        }
    )
    score_content.update(
        {
            "formula_determinism_confidence_percent": formula_confidence,
            "report_evidence_confidence_percent": report_confidence,
        }
    )
    section_by_key["coverage_confidence"]["content"].update(
        {
            "confidence_components": confidence_components,
            "confidence_explanation": confidence_explanation,
        }
    )
    full_page_coverage = bool(
        page_coverage["discovery_completeness"] == "complete"
        and page_coverage["coverage_denominator"]
        and page_coverage["coverage_numerator"] == page_coverage["coverage_denominator"]
    )
    report = ReportExecution(
        report_id=report_id,
        project_id=run.website.project_id,
        website_id=run.website_id,
        analysis_run_id=run.id,
        workflow_execution_id=workflow.id,
        score_execution_id=score.id if score else None,
        report_type=report_type,
        report_version=REPORT_VERSION,
        template_id=TEMPLATE_ID,
        template_version=TEMPLATE_VERSION,
        input_fingerprint=input_fingerprint,
        idempotency_key=normalized_key,
        status="completed" if full_page_coverage and not unavailable else "partial",
        evidence_coverage_numerator=numerator,
        evidence_coverage_denominator=denominator,
        evidence_coverage_percentage=coverage,
        confidence_percent=report_confidence,
        unavailable_sections=unavailable,
        provider_version_metadata={
            "generation_mode": "deterministic_fallback",
            "llm_provider": "unavailable",
            "report_agent_id": "report_agent",
            "report_agent_version": "1.0.0",
            "report_generation_tool_version": "1.0.0",
        },
        failure_details={},
        partial_completion_details=(
            {
                "unavailable_sections": unavailable,
                "page_coverage": page_coverage,
            }
            if unavailable or not full_page_coverage
            else {}
        ),
        started_at=generated_at,
        completed_at=generated_at,
    )
    db.add(report)
    db.flush()
    persisted_sections = [
        ReportSection(
            section_id=uuid.uuid5(report_id, f"section:{section['section_key']}"),
            report_execution_id=report.id,
            section_key=section["section_key"],
            position=position,
            title=section["title"],
            status=section["status"],
            content=section["content"],
            evidence_references=section["evidence_references"],
            unavailable_reason=section["unavailable_reason"],
        )
        for position, section in enumerate(sections, 1)
    ]
    db.add_all(persisted_sections)
    report_quality = _compute_report_quality(
        numerator=numerator,
        denominator=denominator,
        overall_score=score.overall_score if score else None,
        confidence=report_confidence,
        discovery_completeness=page_coverage.get("discovery_completeness"),
    )
    executive_content = _section_content_by_key(sections, "executive_summary")
    finding_totals = _finding_totals(sections)
    completion = _completion_semantics(
        report_quality=report_quality,
        confidence_components=confidence_components,
        discovery_completeness=str(_discovery_completeness)
        if _discovery_completeness is not None
        else None,
        unavailable_sections=unavailable,
        browser_compatibility=real_evidence["browser_compatibility"],
        generation_mode=executive_content.get("generation_mode"),
        repository_applicable=bool(workflow.structured_input.get("repository_connection_id")),
    )
    snapshot_payload = {
        "schema_version": REPORT_VERSION,
        "report_id": str(report_id),
        "report_quality": report_quality,
        "product_name": CUSTOMER_PRODUCT_NAME,
        "finding_totals": finding_totals,
        "completion": completion,
        "title": f"{run.website.name or 'Website'} analysis report",
        "generated_at": generated_at.isoformat(),
        "report_version": REPORT_VERSION,
        "template_version": TEMPLATE_VERSION,
        "project_id": str(run.website.project_id),
        "project_name": run.website.project.name,
        "website_id": str(run.website_id),
        "website_name": run.website.name or "Website",
        "website_url": run.website.url,
        "analysis_run_id": str(run.id),
        "workflow_execution_id": str(workflow.execution_id),
        "score_execution_id": str(score.execution_id) if score else None,
        "status": report.status,
        "evidence_coverage": {
            "numerator": numerator,
            "denominator": denominator,
            "percentage": coverage,
        },
        "confidence_percent": report.confidence_percent,
        "overall_score": score.overall_score if score else None,
        "submitted_url": real_evidence["submitted_url"],
        "normalized_url": real_evidence["normalized_url"],
        "page_coverage": real_evidence["page_coverage"],
        "page_inventory": real_evidence["page_inventory"],
        "browser_compatibility": real_evidence["browser_compatibility"],
        "sections": [
            {
                **section,
                "position": position,
                "section_id": str(persisted_sections[position - 1].section_id),
            }
            for position, section in enumerate(sections, 1)
        ],
        "limitations": [
            item.message
            for item in deduplicate_limitations(
                [
                    {
                        "message": "Unavailable evidence is not represented as passed.",
                        "source": "report",
                    },
                    {
                        "message": "Narrative generation used the deterministic fallback.",
                        "source": "report",
                    },
                    {
                        # Wording deliberately avoids the sanitizer's internal
                        # trigger phrases so the customer-facing statement is
                        # never replaced with a redaction placeholder.
                        "message": "Internal system notes, credentials, and"
                        " server file paths are excluded from this report.",
                        "source": "report",
                    },
                ]
            )
        ],
        "canonical_metrics": {
            "report_section_coverage": {
                "numerator": numerator,
                "denominator": denominator,
                "percentage": coverage,
                "label": "report sections with available evidence",
            },
            "score_category_coverage": {
                "numerator": score.evidence_coverage_numerator if score else 0,
                "denominator": score.evidence_coverage_denominator if score else 5,
                "percentage": score.evidence_coverage_percentage if score else None,
                "label": "scoring categories with available evidence",
            },
            "affected_eligible_page_count": affected_eligible_count,
            "affected_total_count": len(all_affected_urls),
            "eligible_page_count": int(page_coverage.get("eligible_pages", 0)),
            "report_confidence_percent": report_confidence,
            "formula_determinism_percent": formula_confidence,
            "confidence_components": confidence_components,
        },
    }
    snapshot = ReportSnapshot(
        snapshot_id=uuid.uuid5(report_id, "snapshot:1"),
        report_execution_id=report.id,
        snapshot_payload=snapshot_payload,
        evidence_references=evidence_references,
    )
    db.add(snapshot)
    for artifact_format in ("html", "pdf", "json"):
        content = render_report_artifact(artifact_format, snapshot_payload)
        artifact_id = uuid.uuid5(report_id, f"artifact:{artifact_format}:1")
        db.add(
            ReportArtifact(
                artifact_id=artifact_id,
                report_execution_id=report.id,
                format=artifact_format,
                media_type=ARTIFACT_MEDIA_TYPES[artifact_format],
                filename=_safe_filename(
                    run.website.name,
                    report_id,
                    artifact_format,
                ),
                size_bytes=len(content),
                checksum_sha256=hashlib.sha256(content).hexdigest(),
                storage_location=f"database://report-artifacts/{artifact_id}",
                content=content,
            )
        )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        concurrent = db.scalar(
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
                ReportExecution.idempotency_key == normalized_key,
            )
        )
        if concurrent is None or concurrent.input_fingerprint != input_fingerprint:
            raise
        return concurrent, False
    return load_report(db, report_id), True


def load_report(db: Session, report_id: uuid.UUID) -> ReportExecution:
    report = db.scalar(
        select(ReportExecution)
        .options(
            selectinload(ReportExecution.sections),
            selectinload(ReportExecution.artifacts),
            selectinload(ReportExecution.snapshot),
        )
        .where(ReportExecution.report_id == report_id)
    )
    if report is None:
        raise ReportDeliveryError("REPORT_NOT_FOUND", "Report not found.", 404)
    return report


def load_artifact(
    db: Session,
    report_id: uuid.UUID,
    artifact_format: str,
) -> ReportArtifact:
    if artifact_format not in ARTIFACT_MEDIA_TYPES:
        raise ReportDeliveryError(
            "REPORT_FORMAT_UNSUPPORTED",
            "Supported report formats are html, pdf, and json.",
            422,
        )
    report = db.scalar(select(ReportExecution).where(ReportExecution.report_id == report_id))
    if report is None:
        raise ReportDeliveryError("REPORT_NOT_FOUND", "Report not found.", 404)
    artifact = db.scalar(
        select(ReportArtifact).where(
            ReportArtifact.report_execution_id == report.id,
            ReportArtifact.format == artifact_format,
        )
    )
    if artifact is None:
        raise ReportDeliveryError(
            "REPORT_ARTIFACT_UNAVAILABLE",
            "The requested report artifact is unavailable.",
            404,
        )
    return artifact
