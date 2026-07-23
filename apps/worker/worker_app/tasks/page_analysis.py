import logging
import time
import uuid
from typing import Any

from sqlalchemy import and_, insert, select, update

from worker_app.celery_app import celery_app
from worker_app.config import get_settings
from worker_app.db import (
    SessionLocal,
    analysis_runs,
    discovery_runs,
    page_analysis_runs,
    utc_now,
    website_pages,
)

logger = logging.getLogger(__name__)


def select_level2_pages(
    pages: list[dict[str, Any]],
    max_lighthouse_pages: int,
) -> list[dict[str, Any]]:
    priority_types = [
        "homepage",
        "navigation",
        "contact",
        "about",
        "product",
        "service",
    ]

    def priority_key(page: dict[str, Any]) -> tuple[int, int, str]:
        page_type = str(page.get("page_type", "")).lower()
        internal_links = int(page.get("internal_link_count") or 0)

        if page_type in priority_types:
            type_priority = priority_types.index(page_type)
        else:
            type_priority = len(priority_types)

        return (type_priority, -internal_links, str(page.get("normalized_url", "")))

    sorted_pages = sorted(pages, key=priority_key)
    return sorted_pages[:max_lighthouse_pages]


def update_page_analysis_run(
    session: Any,
    run_id: uuid.UUID,
    **values: Any,
) -> None:
    values["updated_at"] = utc_now()
    session.execute(
        update(page_analysis_runs).where(page_analysis_runs.c.id == run_id).values(**values)
    )


def update_website_page_status(
    session: Any,
    page_id: uuid.UUID,
    level: int,
    status: str,
    run_id: uuid.UUID,
) -> None:
    now = utc_now()
    level_col = f"page_analysis_level_{level}_status"
    run_id_col = f"page_analysis_level_{level}_run_id"
    at_col = f"page_analysis_level_{level}_at"
    values: dict[str, Any] = {
        level_col: status,
        run_id_col: run_id,
    }
    if status in ("completed", "partial", "failed"):
        values[at_col] = now
    session.execute(update(website_pages).where(website_pages.c.id == page_id).values(**values))


@celery_app.task(
    name="worker.run_page_analysis",
    soft_time_limit=600,
    time_limit=620,
    acks_late=True,
)
def run_page_analysis(discovery_run_id: str, page_analysis_execution_id: str) -> dict[str, Any]:
    run_id = uuid.UUID(discovery_run_id)
    execution_uuid = uuid.UUID(page_analysis_execution_id)
    settings = get_settings()
    job_started = time.monotonic()

    with SessionLocal() as session:
        run = (
            session.execute(select(discovery_runs).where(discovery_runs.c.id == run_id))
            .mappings()
            .first()
        )
        if not run:
            return {"status": "missing", "discovery_run_id": discovery_run_id}

        website_id = run["website_id"]
        config = run["configuration"]

        max_l1 = config.get("max_html_pages", 50)
        max_l2 = config.get("max_lighthouse_pages", 10)
        per_page_timeout = config.get("request_timeout_seconds", 15)
        total_deadline = job_started + config.get("deadline_seconds", 300)

        eligible_pages = list(
            session.execute(
                select(website_pages)
                .where(
                    and_(
                        website_pages.c.website_id == website_id,
                        website_pages.c.eligibility_status == "eligible",
                        website_pages.c.last_discovery_run_id == run_id,
                    )
                )
                .order_by(website_pages.c.crawl_depth.asc(), website_pages.c.normalized_url.asc())
                .limit(max_l1)
            ).mappings()
        )

        l1_attempted = 0
        l1_successful = 0
        l1_failed = 0
        l2_attempted = 0
        l2_successful = 0
        l2_failed = 0

        for page in eligible_pages:
            if time.monotonic() >= total_deadline:
                logger.warning("page_analysis_deadline discovery_run_id=%s", discovery_run_id)
                break

            existing = session.execute(
                select(page_analysis_runs.c.id).where(
                    page_analysis_runs.c.website_page_id == page["id"],
                    page_analysis_runs.c.analysis_level == 1,
                    page_analysis_runs.c.page_analysis_execution_id == execution_uuid,
                )
            ).first()
            if existing:
                logger.info(
                    "page_l1_skipped_retry page_id=%s execution_id=%s",
                    page["id"],
                    page_analysis_execution_id,
                )
                continue

            l1_run_uuid = uuid.uuid4()
            now = utc_now()
            session.execute(
                insert(page_analysis_runs).values(
                    id=l1_run_uuid,
                    website_page_id=page["id"],
                    discovery_run_id=run_id,
                    page_analysis_execution_id=execution_uuid,
                    analysis_level=1,
                    status="running",
                    analysis_started_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.commit()

            l1_attempted += 1
            from worker_app.analysis.page_analysis import analyze_page_level_1

            url = str(page.get("final_url") or page["original_url"])

            try:
                result = analyze_page_level_1(
                    page_url=url,
                    timeout=per_page_timeout,
                )
                status = result["status"]
                if status == "completed":
                    l1_successful += 1
                else:
                    l1_failed += 1

                update_values = {
                    "status": status,
                    "analysis_completed_at": utc_now(),
                    "requested_url": result["requested_url"],
                    "final_url": result["final_url"],
                    "canonical_url": result.get("canonical_url"),
                    "http_status_code": result.get("http_status_code"),
                    "redirect_chain": result.get("redirect_chain", []),
                    "page_title": result.get("page_title"),
                    "meta_description": result.get("meta_description"),
                    "heading_structure": result.get("heading_structure", []),
                    "robots_directives": result.get("robots_directives", {}),
                    "content_type": result.get("content_type"),
                    "language": result.get("language"),
                    "structured_data_present": result.get("structured_data_present"),
                    "internal_link_count": result.get("internal_link_count"),
                    "external_link_count": result.get("external_link_count"),
                    "image_count": result.get("image_count"),
                    "images_missing_alt": result.get("images_missing_alt"),
                    "form_count": result.get("form_count"),
                    "basic_accessibility_signals": result.get("basic_accessibility_signals", {}),
                    "basic_seo_signals": result.get("basic_seo_signals", {}),
                    "security_observations": result.get("security_observations", {}),
                    "evidence": result.get("evidence", {}),
                    "elapsed_ms": result.get("elapsed_ms"),
                    "failure_reason_code": result.get("failure_reason_code"),
                    "failure_reason_text": result.get("failure_reason_text"),
                }
                update_page_analysis_run(session, l1_run_uuid, **update_values)
                update_website_page_status(session, page["id"], 1, status, l1_run_uuid)
                session.commit()

            except Exception as exception:
                l1_failed += 1
                update_page_analysis_run(
                    session,
                    l1_run_uuid,
                    status="failed",
                    failure_reason_code="page_analysis_error",
                    failure_reason_text=str(exception)[:500],
                    analysis_completed_at=utc_now(),
                )
                update_website_page_status(session, page["id"], 1, "failed", l1_run_uuid)
                session.commit()
                logger.warning(
                    "page_l1_failed page_id=%s error=%s",
                    page["id"],
                    exception,
                )

        l2_candidates = [
            p
            for p in eligible_pages
            if p.get("page_analysis_level_1_status") in ("completed", "partial")
        ]

        l2_selected = select_level2_pages(l2_candidates, max_l2)

        for page in l2_selected:
            if time.monotonic() >= total_deadline:
                break

            existing = session.execute(
                select(page_analysis_runs.c.id).where(
                    page_analysis_runs.c.website_page_id == page["id"],
                    page_analysis_runs.c.analysis_level == 2,
                    page_analysis_runs.c.page_analysis_execution_id == execution_uuid,
                )
            ).first()
            if existing:
                logger.info(
                    "page_l2_skipped_retry page_id=%s execution_id=%s",
                    page["id"],
                    page_analysis_execution_id,
                )
                continue

            l2_run_uuid = uuid.uuid4()
            now = utc_now()
            session.execute(
                insert(page_analysis_runs).values(
                    id=l2_run_uuid,
                    website_page_id=page["id"],
                    discovery_run_id=run_id,
                    page_analysis_execution_id=execution_uuid,
                    analysis_level=2,
                    status="running",
                    analysis_started_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.commit()
            l2_attempted += 1

            url = str(page.get("final_url") or page["original_url"])

            try:
                from worker_app.analysis.lighthouse_audit import run_lighthouse
                from worker_app.analysis.playwright_audit import (
                    chromium_executable_path,
                    inspect_page,
                )

                playwright_data = inspect_page(
                    url,
                    launch_timeout_ms=settings.browser_launch_timeout_ms,
                    navigation_timeout_ms=settings.navigation_timeout_ms,
                    dom_readiness_timeout_ms=settings.dom_readiness_timeout_ms,
                    stabilization_ms=settings.page_stabilization_ms,
                    collection_timeout_ms=settings.evidence_collection_timeout_ms,
                    max_resources=settings.diagnostic_max_resources,
                    responsive_viewports=settings.parsed_responsive_viewports,
                )

                lh_url = str(playwright_data.get("final_url", url))
                lighthouse_data = run_lighthouse(
                    lh_url,
                    chromium_executable_path(),
                    settings.lighthouse_timeout_seconds,
                )

                analysis_run_uuid = uuid.uuid4()
                now = utc_now()
                from worker_app.analysis.findings import generate_findings
                from worker_app.analysis.lighthouse_audit import parse_lighthouse
                from worker_app.analysis.scoring import calculate_score

                metrics = parse_lighthouse(lighthouse_data)
                findings = generate_findings(playwright_data, metrics)
                score = calculate_score(metrics, playwright_data, findings, audit_completed=True)

                session.execute(
                    insert(analysis_runs).values(
                        id=analysis_run_uuid,
                        website_id=website_id,
                        status="completed",
                        progress_percent=100,
                        current_step="completed",
                        started_at=now,
                        completed_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                )
                session.commit()

                from worker_app.tasks.analysis import persist_results

                persist_results(
                    session,
                    analysis_run_uuid,
                    url,
                    playwright_data,
                    lighthouse_data,
                    findings,
                    score,
                    {},
                    now,
                    now,
                )

                update_page_analysis_run(
                    session,
                    l2_run_uuid,
                    status="completed",
                    analysis_completed_at=utc_now(),
                    requested_url=url,
                    final_url=playwright_data.get("final_url"),
                    page_title=playwright_data.get("page_title"),
                    meta_description=playwright_data.get("meta_description"),
                    internal_link_count=playwright_data.get("internal_link_count"),
                    external_link_count=playwright_data.get("external_link_count"),
                    image_count=playwright_data.get("image_count"),
                    images_missing_alt=playwright_data.get("images_missing_alt"),
                    form_count=playwright_data.get("form_count"),
                    deep_analysis_run_id=analysis_run_uuid,
                )
                update_website_page_status(session, page["id"], 2, "completed", l2_run_uuid)
                session.commit()
                l2_successful += 1

            except Exception as exception:
                l2_failed += 1
                update_page_analysis_run(
                    session,
                    l2_run_uuid,
                    status="failed",
                    failure_reason_code="page_l2_error",
                    failure_reason_text=str(exception)[:500],
                    analysis_completed_at=utc_now(),
                )
                update_website_page_status(session, page["id"], 2, "failed", l2_run_uuid)
                session.commit()
                logger.warning(
                    "page_l2_failed page_id=%s error=%s",
                    page["id"],
                    exception,
                )

        return {
            "status": "completed",
            "discovery_run_id": discovery_run_id,
            "l1_attempted": l1_attempted,
            "l1_successful": l1_successful,
            "l1_failed": l1_failed,
            "l2_attempted": l2_attempted,
            "l2_successful": l2_successful,
            "l2_failed": l2_failed,
        }
