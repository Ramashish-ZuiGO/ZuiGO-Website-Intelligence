import re
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, status
from sqlalchemy import case, select
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_db
from app.errors.exceptions import ApplicationError
from app.models import AnalysisFinding, AnalysisRun, AnalysisStatus, FindingSeverity, Website
from app.schemas import (
    AnalysisReportResponse,
    AnalysisResultsResponse,
    AnalysisResultSummary,
    AnalysisRunRead,
)
from app.services.analysis_queue import enqueue_analysis

router = APIRouter(tags=["analysis-runs"])
DatabaseSession = Annotated[Session, Depends(get_db)]
SAFE_PLAYWRIGHT_KEYS = {
    "canonical_url",
    "html_language",
    "h1_count",
    "h1_texts",
    "image_count",
    "images_missing_alt",
    "internal_link_count",
    "external_link_count",
    "form_count",
    "button_count",
    "console_errors",
    "page_javascript_errors",
    "failed_network_requests",
    "https_usage",
    "responsive_viewport",
    "technology_indicators",
}


def get_website_or_raise(db: Session, website_id: uuid.UUID) -> Website:
    website = db.get(Website, website_id)
    if website is None:
        raise ApplicationError(
            code="WEBSITE_NOT_FOUND",
            message="Website not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return website


def lighthouse_metrics(data: dict[str, Any]) -> dict[str, Any]:
    categories = data.get("categories") if isinstance(data.get("categories"), dict) else {}
    audits = data.get("audits") if isinstance(data.get("audits"), dict) else {}

    def score(name: str) -> int | None:
        category = categories.get(name)
        value = category.get("score") if isinstance(category, dict) else None
        return round(value * 100) if isinstance(value, (int, float)) else None

    def metric(name: str) -> float | None:
        audit = audits.get(name)
        value = audit.get("numericValue") if isinstance(audit, dict) else None
        return float(value) if isinstance(value, (int, float)) else None

    def bounded_items(name: str, keys: tuple[str, ...], limit: int = 10) -> list[dict[str, Any]]:
        audit = audits.get(name)
        details = audit.get("details", {}) if isinstance(audit, dict) else {}
        items = details.get("items", []) if isinstance(details, dict) else []
        return [
            {key: item.get(key) for key in keys if item.get(key) is not None}
            for item in items[:limit]
            if isinstance(item, dict)
        ]

    breakdown: list[dict[str, Any]] = []
    for category_name in ("performance", "accessibility", "best-practices", "seo"):
        category = categories.get(category_name, {})
        refs = category.get("auditRefs", []) if isinstance(category, dict) else []
        for audit_ref in refs:
            audit_id = audit_ref.get("id")
            audit = audits.get(audit_id, {})
            audit_score = audit.get("score")
            manual = audit.get("scoreDisplayMode") == "manual"
            if not manual and not (isinstance(audit_score, (int, float)) and audit_score < 1):
                continue
            details = audit.get("details", {})
            breakdown.append(
                {
                    "audit_id": str(audit_id)[:120],
                    "title": str(audit.get("title") or audit_id)[:300],
                    "score": audit_score,
                    "display_value": str(audit.get("displayValue") or "")[:300] or None,
                    "explanation": str(audit.get("explanation") or audit.get("description") or "")[
                        :600
                    ]
                    or None,
                    "category": category_name,
                    "evidence_summary": (
                        {
                            "detail_type": details.get("type"),
                            "item_count": (
                                len(details.get("items", []))
                                if isinstance(details.get("items"), list)
                                else None
                            ),
                        }
                        if isinstance(details, dict)
                        else None
                    ),
                    "manual_check": manual,
                }
            )
            if len(breakdown) >= 40:
                break
        if len(breakdown) >= 40:
            break

    config = data.get("configSettings", {})
    environment = data.get("environment", {})
    user_agent = str(environment.get("networkUserAgent") or environment.get("hostUserAgent") or "")
    chromium_match = re.search(r"(?:Chrome|Chromium)/([0-9.]+)", user_agent)
    lcp_items = bounded_items(
        "largest-contentful-paint-element", ("nodeLabel", "snippet", "selector"), 1
    )

    return {
        "performance_score": score("performance"),
        "accessibility_score": score("accessibility"),
        "best_practices_score": score("best-practices"),
        "seo_score": score("seo"),
        "first_contentful_paint_ms": metric("first-contentful-paint"),
        "largest_contentful_paint_ms": metric("largest-contentful-paint"),
        "total_blocking_time_ms": metric("total-blocking-time"),
        "cumulative_layout_shift": metric("cumulative-layout-shift"),
        "speed_index_ms": metric("speed-index"),
        "time_to_interactive_ms": metric("interactive"),
        "time_to_interactive_context": {
            "status": "legacy_supplementary",
            "core_web_vital": False,
            "included_in_performance_score": False,
        },
        "lighthouse_context": {
            "lighthouse_version": data.get("lighthouseVersion"),
            "chromium_version": chromium_match.group(1) if chromium_match else None,
            "form_factor": config.get("formFactor"),
            "throttling_method": config.get("throttlingMethod"),
            "screen_emulation": config.get("screenEmulation"),
            "audit_timestamp": data.get("fetchTime"),
        },
        "lighthouse_audit_breakdown": breakdown,
        "accessibility_context": {
            "automated_checks_completed": score("accessibility") is not None,
            "score_100_proves_compliance": False,
            "manual_testing_required": True,
        },
        "performance_evidence": {
            "lcp_element": lcp_items[0] if lcp_items else None,
            "render_blocking_resources": bounded_items(
                "render-blocking-resources", ("url", "totalBytes", "wastedMs")
            ),
            "long_tasks": bounded_items("long-tasks", ("url", "duration", "startTime")),
            "main_thread_work": bounded_items(
                "mainthread-work-breakdown", ("group", "groupLabel", "duration")
            ),
            "script_execution": bounded_items(
                "bootup-time", ("url", "total", "scripting", "scriptParseCompile")
            ),
        },
    }


def run_response(analysis_run: AnalysisRun) -> AnalysisRunRead:
    summary = None
    if analysis_run.result is not None:
        metrics = lighthouse_metrics(analysis_run.result.raw_lighthouse_data)
        summary = AnalysisResultSummary(
            final_url=analysis_run.result.final_url,
            http_status_code=analysis_run.result.http_status_code,
            page_title=analysis_run.result.page_title,
            performance_score=metrics["performance_score"],
            accessibility_score=metrics["accessibility_score"],
            best_practices_score=metrics["best_practices_score"],
            seo_score=metrics["seo_score"],
            overall_score=analysis_run.score.overall_score if analysis_run.score else None,
            technical_quality_score=(
                analysis_run.score.technical_quality_score if analysis_run.score else None
            ),
            confidence_percent=(
                analysis_run.score.confidence_percent if analysis_run.score else None
            ),
            finding_count=len(analysis_run.findings),
        )
    return AnalysisRunRead.model_validate(analysis_run).model_copy(
        update={"result_summary": summary}
    )


@router.post(
    "/websites/{website_id}/analysis-runs",
    response_model=AnalysisRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_analysis(website_id: uuid.UUID, db: DatabaseSession) -> AnalysisRunRead:
    get_website_or_raise(db, website_id)
    analysis_run = AnalysisRun(website_id=website_id)
    db.add(analysis_run)
    db.commit()
    db.refresh(analysis_run)
    try:
        analysis_run.celery_task_id = enqueue_analysis(str(analysis_run.id))
    except Exception as exception:
        analysis_run.status = AnalysisStatus.FAILED
        analysis_run.error_code = "ANALYSIS_QUEUE_UNAVAILABLE"
        analysis_run.error_message = "Analysis could not be queued."
        db.commit()
        raise ApplicationError(
            code="ANALYSIS_QUEUE_UNAVAILABLE",
            message="Analysis could not be queued.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exception
    db.commit()
    db.refresh(analysis_run)
    return run_response(analysis_run)


@router.get("/analysis-runs/{analysis_run_id}", response_model=AnalysisRunRead)
def get_analysis_run(analysis_run_id: uuid.UUID, db: DatabaseSession) -> AnalysisRunRead:
    analysis_run = db.scalar(
        select(AnalysisRun)
        .options(
            selectinload(AnalysisRun.result),
            selectinload(AnalysisRun.diagnostics),
            selectinload(AnalysisRun.findings),
            selectinload(AnalysisRun.score),
        )
        .where(AnalysisRun.id == analysis_run_id)
    )
    if analysis_run is None:
        raise ApplicationError(
            code="ANALYSIS_RUN_NOT_FOUND",
            message="Analysis run not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return run_response(analysis_run)


@router.get("/websites/{website_id}/analysis-runs", response_model=list[AnalysisRunRead])
def list_analysis_runs(website_id: uuid.UUID, db: DatabaseSession) -> list[AnalysisRunRead]:
    get_website_or_raise(db, website_id)
    runs = list(
        db.scalars(
            select(AnalysisRun)
            .options(
                selectinload(AnalysisRun.result),
                selectinload(AnalysisRun.findings),
                selectinload(AnalysisRun.score),
            )
            .where(AnalysisRun.website_id == website_id)
            .order_by(AnalysisRun.created_at.desc(), AnalysisRun.id.desc())
        )
    )
    return [run_response(run) for run in runs]


@router.get("/analysis-runs/{analysis_run_id}/results", response_model=AnalysisResultsResponse)
def get_analysis_results(
    analysis_run_id: uuid.UUID, db: DatabaseSession
) -> AnalysisResultsResponse:
    analysis_run = db.scalar(
        select(AnalysisRun)
        .options(
            selectinload(AnalysisRun.result),
            selectinload(AnalysisRun.diagnostics),
        )
        .where(AnalysisRun.id == analysis_run_id)
    )
    if analysis_run is None:
        raise ApplicationError(
            code="ANALYSIS_RUN_NOT_FOUND",
            message="Analysis run not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    if analysis_run.result is None:
        raise ApplicationError(
            code="ANALYSIS_RESULTS_NOT_AVAILABLE",
            message="Analysis results are not available.",
            status_code=status.HTTP_409_CONFLICT,
        )
    severity_order = case(
        (AnalysisFinding.severity == FindingSeverity.CRITICAL, 0),
        (AnalysisFinding.severity == FindingSeverity.HIGH, 1),
        (AnalysisFinding.severity == FindingSeverity.MEDIUM, 2),
        (AnalysisFinding.severity == FindingSeverity.LOW, 3),
        else_=4,
    )
    findings = list(
        db.scalars(
            select(AnalysisFinding)
            .where(AnalysisFinding.analysis_run_id == analysis_run_id)
            .order_by(severity_order, AnalysisFinding.created_at)
        )
    )
    return AnalysisResultsResponse(
        result=analysis_run.result,
        lighthouse_metrics=lighthouse_metrics(analysis_run.result.raw_lighthouse_data),
        playwright_measurements={
            key: value
            for key, value in analysis_run.result.raw_playwright_data.items()
            if key in SAFE_PLAYWRIGHT_KEYS
        },
        findings=findings,
        diagnostics={item.group_name: item.payload for item in analysis_run.diagnostics},
    )


@router.get("/analysis-runs/{analysis_run_id}/report", response_model=AnalysisReportResponse)
def get_analysis_report(analysis_run_id: uuid.UUID, db: DatabaseSession) -> AnalysisReportResponse:
    analysis_run = db.scalar(
        select(AnalysisRun)
        .options(
            selectinload(AnalysisRun.result),
            selectinload(AnalysisRun.score),
            selectinload(AnalysisRun.website),
            selectinload(AnalysisRun.interpretation),
            selectinload(AnalysisRun.diagnostics),
        )
        .execution_options(populate_existing=True)
        .where(AnalysisRun.id == analysis_run_id)
    )
    if analysis_run is None:
        raise ApplicationError(
            code="ANALYSIS_RUN_NOT_FOUND",
            message="Analysis run not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    if analysis_run.result is None or analysis_run.score is None:
        raise ApplicationError(
            code="ANALYSIS_REPORT_NOT_AVAILABLE",
            message="Analysis report is not available.",
            status_code=status.HTTP_409_CONFLICT,
        )
    severity_order = case(
        (AnalysisFinding.severity == FindingSeverity.CRITICAL, 0),
        (AnalysisFinding.severity == FindingSeverity.HIGH, 1),
        (AnalysisFinding.severity == FindingSeverity.MEDIUM, 2),
        (AnalysisFinding.severity == FindingSeverity.LOW, 3),
        else_=4,
    )
    findings = list(
        db.scalars(
            select(AnalysisFinding)
            .where(AnalysisFinding.analysis_run_id == analysis_run_id)
            .order_by(
                severity_order,
                AnalysisFinding.category,
                AnalysisFinding.finding_code,
            )
        )
    )
    return AnalysisReportResponse(
        report_id=analysis_run.score.id,
        analysis_run_id=analysis_run.id,
        analysis_status=analysis_run.status.value,
        website={
            "id": analysis_run.website.id,
            "name": analysis_run.website.name,
            "url": analysis_run.website.url,
        },
        result=analysis_run.result,
        score=analysis_run.score,
        lighthouse_metrics=lighthouse_metrics(analysis_run.result.raw_lighthouse_data),
        playwright_measurements={
            key: value
            for key, value in analysis_run.result.raw_playwright_data.items()
            if key in SAFE_PLAYWRIGHT_KEYS
        },
        findings=findings,
        interpretation=analysis_run.interpretation,
        diagnostics={item.group_name: item.payload for item in analysis_run.diagnostics},
    )
