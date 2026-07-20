import logging
import time
import uuid
from collections.abc import Callable
from datetime import datetime
from urllib.parse import urlsplit

from billiard.exceptions import SoftTimeLimitExceeded
from sqlalchemy import delete, insert, select, update
from sqlalchemy.orm import Session

from worker_app.ai import generate_interpretation
from worker_app.analysis.errors import AnalysisFailure, FailureDetail
from worker_app.analysis.findings import generate_findings
from worker_app.analysis.lighthouse_audit import parse_lighthouse, run_lighthouse
from worker_app.analysis.playwright_audit import (
    chromium_executable_path,
    inspect_page,
    normalize_playwright_error,
)
from worker_app.analysis.scoring import FORMULA_VERSION, calculate_score
from worker_app.analysis.url_safety import UrlSafetyError, validate_public_url
from worker_app.celery_app import celery_app
from worker_app.config import get_settings
from worker_app.db import (
    SessionLocal,
    analysis_findings,
    analysis_interpretations,
    analysis_results,
    analysis_runs,
    analysis_scores,
    parse_analysis_run_id,
    utc_now,
    websites,
)

logger = logging.getLogger(__name__)
SAFE_AI_PLAYWRIGHT_KEYS = {
    "canonical_url",
    "html_language",
    "h1_count",
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
    "http_status_code",
    "page_title",
    "meta_description",
}


def safe_log_url(value: str) -> str:
    parsed = urlsplit(value)
    return f"{parsed.scheme}://{parsed.hostname or ''}/"


def update_run(session: Session, analysis_run_id: uuid.UUID, **values: object) -> None:
    values["updated_at"] = utc_now()
    session.execute(
        update(analysis_runs).where(analysis_runs.c.id == analysis_run_id).values(**values)
    )
    session.commit()


def stage(session: Session, analysis_run_id: uuid.UUID, progress: int, step: str) -> None:
    current_progress = session.scalar(
        select(analysis_runs.c.progress_percent).where(analysis_runs.c.id == analysis_run_id)
    )
    progress = max(progress, current_progress or 0)
    update_run(
        session,
        analysis_run_id,
        status="running",
        progress_percent=progress,
        current_step=step,
    )
    logger.info(
        "analysis_state analysis_run_id=%s status=running progress_percent=%s step=%s",
        analysis_run_id,
        progress,
        step,
    )


def persist_results(
    session: Session,
    analysis_run_id: uuid.UUID,
    requested_url: str,
    playwright_data: dict[str, object],
    lighthouse_data: dict[str, object],
    findings: list[dict[str, object]],
    score: dict[str, object],
    started_at: datetime,
    completed_at: datetime,
) -> None:
    metrics = parse_lighthouse(lighthouse_data)
    session.execute(
        delete(analysis_findings).where(analysis_findings.c.analysis_run_id == analysis_run_id)
    )
    session.execute(
        delete(analysis_results).where(analysis_results.c.analysis_run_id == analysis_run_id)
    )
    session.execute(
        delete(analysis_scores).where(analysis_scores.c.analysis_run_id == analysis_run_id)
    )
    session.execute(
        delete(analysis_interpretations).where(
            analysis_interpretations.c.analysis_run_id == analysis_run_id
        )
    )
    now = utc_now()
    session.execute(
        insert(analysis_results).values(
            id=uuid.uuid4(),
            analysis_run_id=analysis_run_id,
            requested_url=requested_url,
            final_url=playwright_data["final_url"],
            http_status_code=playwright_data.get("http_status_code"),
            page_title=playwright_data.get("page_title"),
            meta_description=playwright_data.get("meta_description"),
            lighthouse_version=metrics.get("lighthouse_version"),
            user_agent=playwright_data.get("user_agent"),
            analysis_started_at=started_at,
            analysis_completed_at=completed_at,
            raw_lighthouse_data=lighthouse_data,
            raw_playwright_data=playwright_data,
            created_at=now,
            updated_at=now,
        )
    )
    if findings:
        session.execute(
            insert(analysis_findings),
            [
                {
                    "id": uuid.uuid4(),
                    "analysis_run_id": analysis_run_id,
                    "created_at": now,
                    **item,
                }
                for item in findings
            ],
        )
    session.execute(
        insert(analysis_scores).values(
            id=uuid.uuid4(),
            analysis_run_id=analysis_run_id,
            created_at=now,
            updated_at=now,
            **score,
        )
    )
    session.commit()


def persist_interpretation(
    session: Session, analysis_run_id: uuid.UUID, interpretation: dict[str, object]
) -> None:
    now = utc_now()
    session.execute(
        delete(analysis_interpretations).where(
            analysis_interpretations.c.analysis_run_id == analysis_run_id
        )
    )
    session.execute(
        insert(analysis_interpretations).values(
            id=uuid.uuid4(),
            analysis_run_id=analysis_run_id,
            generated_at=now,
            created_at=now,
            updated_at=now,
            **interpretation,
        )
    )
    session.commit()


def mark_failed(analysis_run_id: uuid.UUID, error_code: str, message: str) -> None:
    with SessionLocal() as session:
        update_run(
            session,
            analysis_run_id,
            status="failed",
            current_step="Analysis failed",
            completed_at=utc_now(),
            error_code=error_code,
            error_message=message,
        )


def safe_failure(exception: Exception) -> FailureDetail:
    if isinstance(exception, AnalysisFailure):
        return exception.detail
    if isinstance(exception, UrlSafetyError):
        return FailureDetail(exception.code, exception.safe_message, "loading_website", False)
    if isinstance(exception, SoftTimeLimitExceeded):
        return FailureDetail(
            "ANALYSIS_DEADLINE_EXCEEDED", "The analysis deadline was exceeded.", "failed", False
        )
    if exception.__class__.__module__.startswith("playwright"):
        normalized = normalize_playwright_error(exception)
        return FailureDetail(
            normalized.code, normalized.safe_message, "collecting_page_evidence", False
        )
    return FailureDetail(
        "INTERNAL_ANALYSIS_ERROR", "The analysis could not be completed.", "failed", False
    )


def run_with_retries[T](
    operation: Callable[[], T],
    *,
    max_attempts: int,
    backoff_seconds: float,
    context: dict[str, object],
) -> tuple[T, int]:
    for attempt in range(1, max_attempts + 1):
        try:
            return operation(), attempt
        except AnalysisFailure as exception:
            failure = exception.with_attempt(attempt)
            if not failure.detail.retryable or attempt >= max_attempts:
                raise failure from exception
            logger.warning(
                "analysis_retry analysis_run_id=%s project_id=%s website_id=%s "
                "stage=%s attempt=%s failure_code=%s",
                context["analysis_run_id"],
                context["project_id"],
                context["website_id"],
                failure.detail.stage,
                attempt,
                failure.detail.code,
            )
            if backoff_seconds:
                time.sleep(backoff_seconds)
    raise AssertionError("retry loop exhausted")


@celery_app.task(
    name="worker.run_analysis",
    soft_time_limit=305,
    time_limit=315,
    acks_late=True,
)
def run_analysis(analysis_run_id: str) -> dict[str, str]:
    run_id = parse_analysis_run_id(analysis_run_id)
    settings = get_settings()
    job_started = time.monotonic()
    context: dict[str, object] = {"analysis_run_id": run_id, "project_id": None, "website_id": None}

    def ensure_deadline() -> None:
        elapsed = time.monotonic() - job_started
        if elapsed >= settings.analysis_job_timeout_seconds:
            raise AnalysisFailure(
                FailureDetail(
                    "ANALYSIS_DEADLINE_EXCEEDED",
                    "The analysis deadline was exceeded.",
                    "failed",
                    False,
                    internal_detail=f"elapsed_seconds={elapsed:.3f}",
                )
            )

    try:
        with SessionLocal() as session:
            row = (
                session.execute(
                    select(analysis_runs.c.status, analysis_runs.c.website_id).where(
                        analysis_runs.c.id == run_id
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                logger.warning("analysis_missing analysis_run_id=%s", run_id)
                return {"status": "missing", "analysis_run_id": analysis_run_id}
            if row["status"] == "completed":
                return {"status": "completed", "analysis_run_id": analysis_run_id}
            website_row = (
                session.execute(
                    select(websites.c.url, websites.c.name).where(
                        websites.c.id == row["website_id"]
                    )
                )
                .mappings()
                .one_or_none()
            )
            if website_row is None:
                return {"status": "missing", "analysis_run_id": analysis_run_id}
            requested_url = website_row["url"]
            context["website_id"] = row["website_id"]
            context["project_id"] = session.scalar(
                select(websites.c.project_id).where(websites.c.id == row["website_id"])
            )

            started_at = utc_now()
            update_run(
                session,
                run_id,
                status="running",
                progress_percent=5,
                current_step="queued",
                started_at=started_at,
                completed_at=None,
                error_code=None,
                error_message=None,
            )
            validate_public_url(requested_url)
            ensure_deadline()
            stage(session, run_id, 10, "preparing_browser")
            stage(session, run_id, 20, "loading_website")
            playwright_started = time.monotonic()
            playwright_result, playwright_attempt = run_with_retries(
                lambda: inspect_page(
                    requested_url,
                    launch_timeout_ms=settings.browser_launch_timeout_ms,
                    navigation_timeout_ms=settings.navigation_timeout_ms,
                    dom_readiness_timeout_ms=settings.dom_readiness_timeout_ms,
                    stabilization_ms=settings.page_stabilization_ms,
                    collection_timeout_ms=settings.evidence_collection_timeout_ms,
                ),
                max_attempts=settings.analysis_max_attempts,
                backoff_seconds=settings.analysis_retry_backoff_seconds,
                context=context,
            )
            playwright_data = playwright_result
            playwright_data["attempt_count"] = playwright_attempt
            logger.info(
                "analysis_stage_complete analysis_run_id=%s project_id=%s website_id=%s "
                "stage=collecting_page_evidence attempt=%s requested_url=%s final_url=%s "
                "elapsed_ms=%s timeout_ms=%s",
                run_id,
                context["project_id"],
                context["website_id"],
                playwright_attempt,
                safe_log_url(requested_url),
                safe_log_url(str(playwright_data["final_url"])),
                round((time.monotonic() - playwright_started) * 1000),
                settings.navigation_timeout_ms,
            )
            ensure_deadline()
            stage(session, run_id, 45, "collecting_page_evidence")
            stage(session, run_id, 55, "running_lighthouse")
            lighthouse_started = time.monotonic()
            lighthouse_result, lighthouse_attempt = run_with_retries(
                lambda: run_lighthouse(
                    str(playwright_data["final_url"]),
                    chromium_executable_path(),
                    settings.lighthouse_timeout_seconds,
                ),
                max_attempts=settings.analysis_max_attempts,
                backoff_seconds=settings.analysis_retry_backoff_seconds,
                context=context,
            )
            lighthouse_data = lighthouse_result
            lighthouse_data.setdefault("_zuigo_execution", {})["attempt_count"] = lighthouse_attempt
            logger.info(
                "analysis_stage_complete analysis_run_id=%s project_id=%s website_id=%s "
                "stage=running_lighthouse attempt=%s requested_url=%s final_url=%s "
                "elapsed_ms=%s timeout_ms=%s lighthouse_exit_code=%s",
                run_id,
                context["project_id"],
                context["website_id"],
                lighthouse_attempt,
                safe_log_url(requested_url),
                safe_log_url(str(playwright_data["final_url"])),
                round((time.monotonic() - lighthouse_started) * 1000),
                settings.lighthouse_timeout_seconds * 1000,
                lighthouse_data["_zuigo_execution"].get("exit_code"),
            )
            validate_public_url(
                str(lighthouse_data.get("finalDisplayedUrl") or playwright_data["final_url"])
            )
            ensure_deadline()
            stage(session, run_id, 75, "calculating_score")
            metrics = parse_lighthouse(lighthouse_data)
            findings = generate_findings(playwright_data, metrics)
            score = calculate_score(
                metrics,
                playwright_data,
                findings,
                audit_completed=True,
            )
            logger.info(
                "analysis_score analysis_run_id=%s formula_version=%s",
                run_id,
                FORMULA_VERSION,
            )
            stage(session, run_id, 85, "saving_report")
            completed_at = utc_now()
            persist_results(
                session,
                run_id,
                requested_url,
                playwright_data,
                lighthouse_data,
                findings,
                score,
                started_at,
                completed_at,
            )
            ensure_deadline()
            stage(session, run_id, 90, "generating_interpretation")
            try:
                interpretation = generate_interpretation(
                    {
                        "website": {
                            "name": website_row["name"],
                            "requested_url": requested_url,
                            "final_url": playwright_data["final_url"],
                            "analysis_date": completed_at.isoformat(),
                        },
                        "scores": {
                            key: score[key]
                            for key in (
                                "overall_score",
                                "performance_score",
                                "accessibility_score",
                                "best_practices_score",
                                "seo_score",
                                "technical_quality_score",
                                "confidence_percent",
                                "formula_version",
                            )
                        },
                        "deductions": score["deductions"],
                        "lighthouse_metrics": metrics,
                        "playwright_measurements": {
                            key: value
                            for key, value in playwright_data.items()
                            if key in SAFE_AI_PLAYWRIGHT_KEYS
                        },
                        "findings": findings,
                    },
                    get_settings(),
                )
                persist_interpretation(session, run_id, interpretation)
                logger.info(
                    "analysis_interpretation analysis_run_id=%s provider=%s model=%s "
                    "generation_mode=%s prompt_version=%s",
                    run_id,
                    interpretation["provider"],
                    interpretation["model"],
                    interpretation["generation_mode"],
                    interpretation["prompt_version"],
                )
            except Exception as interpretation_exception:
                logger.warning(
                    "analysis_interpretation_unavailable analysis_run_id=%s exception_type=%s",
                    run_id,
                    type(interpretation_exception).__name__,
                )
            update_run(
                session,
                run_id,
                status="completed",
                progress_percent=100,
                current_step="completed",
                completed_at=completed_at,
            )
            logger.info(
                "analysis_state analysis_run_id=%s status=completed progress_percent=100",
                run_id,
            )
    except Exception as exception:
        failure = safe_failure(exception)
        logger.error(
            "analysis_failed analysis_run_id=%s project_id=%s website_id=%s "
            "stage=%s attempt=%s retryable=%s failure_code=%s "
            "exception_type=%s elapsed_ms=%s",
            run_id,
            context["project_id"],
            context["website_id"],
            failure.stage,
            failure.attempt,
            failure.retryable,
            failure.code,
            type(exception).__name__,
            round((time.monotonic() - job_started) * 1000),
        )
        mark_failed(run_id, failure.code, failure.safe_message)
        return {"status": "failed", "analysis_run_id": analysis_run_id}

    return {"status": "completed", "analysis_run_id": analysis_run_id}
