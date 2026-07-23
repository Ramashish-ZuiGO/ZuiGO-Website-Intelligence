import logging
import uuid
from typing import Any

from sqlalchemy import insert, select, update

from worker_app.celery_app import celery_app
from worker_app.config import get_settings
from worker_app.db import (
    SessionLocal,
    analysis_results,
    analysis_runs,
    discovery_runs,
    utc_now,
    website_pages,
    websites,
)
from worker_app.discovery.engine import (
    DiscoveryConfig,
    DiscoveryError,
    discover_site,
    normalize_url,
)

logger = logging.getLogger(__name__)


def discovery_config() -> DiscoveryConfig:
    settings = get_settings()
    return DiscoveryConfig(
        max_discovered_urls=settings.discovery_max_urls,
        max_html_pages=settings.discovery_max_html_pages,
        max_crawl_depth=settings.discovery_max_depth,
        max_links_per_page=settings.discovery_max_links_per_page,
        max_sitemap_files=settings.discovery_max_sitemap_files,
        max_sitemap_depth=settings.discovery_max_sitemap_depth,
        max_redirects=settings.discovery_max_redirects,
        request_timeout_seconds=settings.discovery_request_timeout_seconds,
        deadline_seconds=settings.discovery_deadline_seconds,
        max_response_bytes=settings.discovery_max_response_bytes,
        include_verified_subdomains=settings.discovery_include_verified_subdomains,
    )


def update_discovery_run(session: Any, run_id: uuid.UUID, **values: Any) -> None:
    values["updated_at"] = utc_now()
    session.execute(update(discovery_runs).where(discovery_runs.c.id == run_id).values(**values))
    session.commit()


def stage(session: Any, run_id: uuid.UUID, progress: int, name: str) -> None:
    current = session.scalar(
        select(discovery_runs.c.progress_percent).where(discovery_runs.c.id == run_id)
    )
    update_discovery_run(
        session,
        run_id,
        status="running",
        progress_percent=max(progress, current or 0),
        current_stage=name,
    )


def persist_pages(
    session: Any,
    run_id: uuid.UUID,
    website_id: uuid.UUID,
    pages: list[dict[str, Any]],
    latest_analysis: dict[str, Any] | None,
) -> None:
    now = utc_now()
    homepage_normalized = (
        normalize_url(str(latest_analysis["final_url"])) if latest_analysis else None
    )
    for page in pages:
        existing = (
            session.execute(
                select(website_pages).where(
                    website_pages.c.website_id == website_id,
                    website_pages.c.normalized_url == page["normalized_url"],
                )
            )
            .mappings()
            .first()
        )
        is_analyzed_homepage = page["normalized_url"] == homepage_normalized
        values = {
            "original_url": page["original_url"],
            "final_url": page["final_url"],
            "canonical_url": page["canonical_url"],
            "page_title": page["page_title"],
            "page_type": page["page_type"],
            "page_type_confidence": page["confidence_percent"],
            "page_type_indicators": page["indicators"],
            "classification_version": page["classification_version"],
            "discovery_source": page["discovery_source"],
            "discovery_evidence": page["discovery_evidence"],
            "source_page_url": page["source_page_url"],
            "crawl_depth": page["crawl_depth"],
            "origin_relation": page["origin_relation"],
            "robots_status": page["robots_status"],
            "eligibility_status": page["eligibility_status"],
            "exclusion_reason": page["exclusion_reason"],
            "skip_reason": page["skip_reason"],
            "last_discovery_run_id": run_id,
            "latest_analysis_run_id": (
                latest_analysis["id"] if is_analyzed_homepage and latest_analysis else None
            ),
            "latest_analysis_status": (
                latest_analysis["status"] if is_analyzed_homepage and latest_analysis else "pending"
            ),
            "last_discovered_at": now,
            "updated_at": now,
        }
        if existing:
            session.execute(
                update(website_pages).where(website_pages.c.id == existing["id"]).values(**values)
            )
        else:
            session.execute(
                insert(website_pages).values(
                    id=uuid.uuid4(),
                    website_id=website_id,
                    normalized_url=page["normalized_url"],
                    first_discovered_at=now,
                    created_at=now,
                    **values,
                )
            )
    session.commit()


@celery_app.task(name="worker.run_discovery")
def run_discovery(discovery_run_id: str) -> None:
    run_id = uuid.UUID(discovery_run_id)
    with SessionLocal() as session:
        run = (
            session.execute(select(discovery_runs).where(discovery_runs.c.id == run_id))
            .mappings()
            .first()
        )
        if not run:
            return
        website = (
            session.execute(select(websites).where(websites.c.id == run["website_id"]))
            .mappings()
            .first()
        )
        if not website:
            update_discovery_run(
                session,
                run_id,
                status="failed",
                progress_percent=100,
                current_stage="failed",
                failure_code="INTERNAL_DISCOVERY_ERROR",
                failure_message="The website no longer exists.",
                completed_at=utc_now(),
            )
            return
        config = discovery_config()
        update_discovery_run(
            session,
            run_id,
            status="running",
            current_stage="loading_robots",
            progress_percent=5,
            started_at=utc_now(),
            configuration=config.__dict__,
        )
        latest = (
            session.execute(
                select(
                    analysis_runs.c.id,
                    analysis_runs.c.status,
                    analysis_results.c.final_url,
                    analysis_results.c.raw_playwright_data,
                )
                .join(
                    analysis_results,
                    analysis_results.c.analysis_run_id == analysis_runs.c.id,
                )
                .where(analysis_runs.c.website_id == website["id"])
                .order_by(analysis_runs.c.created_at.desc())
                .limit(1)
            )
            .mappings()
            .first()
        )
        rendered_links = (
            latest["raw_playwright_data"].get("rendered_dom_links", []) if latest else []
        )
        try:
            stage(session, run_id, 20, "loading_sitemaps")
            result = discover_site(website["url"], config, rendered_links=rendered_links)
            stage(session, run_id, 75, "classifying_pages")
            persist_pages(
                session,
                run_id,
                website["id"],
                result["pages"],
                dict(latest) if latest else None,
            )
            stage(session, run_id, 90, "saving_coverage")
            counts = result["counts"]
            update_discovery_run(
                session,
                run_id,
                status=result["status"],
                current_stage="completed",
                progress_percent=100,
                robots_details=result["robots"],
                sitemap_details=result["sitemaps"],
                urls_discovered=counts["discovered"],
                urls_unique=counts["unique"],
                urls_eligible=counts["eligible"],
                urls_excluded=counts["excluded"],
                urls_skipped=counts["skipped"],
                sitemap_count=counts["sitemaps"],
                crawl_limit_reached=result["crawl_limit_reached"],
                maximum_depth_reached=result["maximum_depth_reached"],
                failure_code=(result["errors"][0]["code"] if result["errors"] else None),
                failure_message=(
                    "Discovery completed with bounded partial failures."
                    if result["errors"]
                    else None
                ),
                completed_at=utc_now(),
            )
        except DiscoveryError as exception:
            logger.warning("discovery_failed discovery_run_id=%s code=%s", run_id, exception.code)
            update_discovery_run(
                session,
                run_id,
                status="failed",
                current_stage="failed",
                progress_percent=100,
                failure_code=exception.code,
                failure_message=exception.safe_message,
                completed_at=utc_now(),
            )
        except Exception:
            logger.exception("discovery_internal_error discovery_run_id=%s", run_id)
            update_discovery_run(
                session,
                run_id,
                status="failed",
                current_stage="failed",
                progress_percent=100,
                failure_code="INTERNAL_DISCOVERY_ERROR",
                failure_message="Website discovery failed safely.",
                completed_at=utc_now(),
            )
