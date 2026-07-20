import logging
import uuid
from datetime import datetime

from billiard.exceptions import SoftTimeLimitExceeded
from sqlalchemy import delete, insert, select, update
from sqlalchemy.orm import Session

from worker_app.ai import generate_interpretation
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


def update_run(session: Session, analysis_run_id: uuid.UUID, **values: object) -> None:
    values["updated_at"] = utc_now()
    session.execute(
        update(analysis_runs).where(analysis_runs.c.id == analysis_run_id).values(**values)
    )
    session.commit()


def stage(session: Session, analysis_run_id: uuid.UUID, progress: int, step: str) -> None:
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


def safe_failure(exception: Exception) -> tuple[str, str]:
    if isinstance(exception, UrlSafetyError):
        return exception.code, exception.safe_message
    if isinstance(exception, SoftTimeLimitExceeded):
        return "ANALYSIS_TIMEOUT", "The website analysis timed out."
    if isinstance(exception, RuntimeError) and str(exception) == "LIGHTHOUSE_FAILED":
        return "LIGHTHOUSE_FAILED", "The Lighthouse audit failed."
    if exception.__class__.__module__.startswith("playwright"):
        normalized = normalize_playwright_error(exception)
        return normalized.code, normalized.safe_message
    return "ANALYSIS_PROCESSING_FAILED", "The analysis could not be completed."


@celery_app.task(
    name="worker.run_analysis",
    soft_time_limit=240,
    time_limit=270,
    acks_late=True,
)
def run_analysis(analysis_run_id: str) -> dict[str, str]:
    run_id = parse_analysis_run_id(analysis_run_id)
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

            started_at = utc_now()
            update_run(
                session,
                run_id,
                status="running",
                progress_percent=5,
                current_step="Validating target",
                started_at=started_at,
                completed_at=None,
                error_code=None,
                error_message=None,
            )
            validate_public_url(requested_url)
            stage(session, run_id, 15, "Launching browser")
            stage(session, run_id, 35, "Inspecting page")
            playwright_data = inspect_page(requested_url)
            stage(session, run_id, 60, "Running Lighthouse")
            lighthouse_data = run_lighthouse(
                str(playwright_data["final_url"]), chromium_executable_path()
            )
            validate_public_url(
                str(lighthouse_data.get("finalDisplayedUrl") or playwright_data["final_url"])
            )
            stage(session, run_id, 80, "Generating verified findings")
            metrics = parse_lighthouse(lighthouse_data)
            findings = generate_findings(playwright_data, metrics)
            stage(session, run_id, 88, "Calculating transparent scores")
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
            stage(session, run_id, 90, "Saving verified results")
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
            stage(session, run_id, 92, "Generating evidence-grounded interpretation")
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
                current_step="Analysis completed",
                completed_at=completed_at,
            )
            logger.info(
                "analysis_state analysis_run_id=%s status=completed progress_percent=100",
                run_id,
            )
    except Exception as exception:
        error_code, message = safe_failure(exception)
        logger.error(
            "analysis_failed analysis_run_id=%s error_code=%s exception_type=%s",
            run_id,
            error_code,
            type(exception).__name__,
        )
        mark_failed(run_id, error_code, message)
        return {"status": "failed", "analysis_run_id": analysis_run_id}

    return {"status": "completed", "analysis_run_id": analysis_run_id}
