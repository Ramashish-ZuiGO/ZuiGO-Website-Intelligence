import math
import re
import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.errors.exceptions import ApplicationError
from app.models import AnalysisFinding, DiscoveryRun, DiscoveryStatus, Website, WebsitePage
from app.schemas import CoverageSummary, DiscoveryRunRead, WebsitePageList, WebsitePageRead
from app.services.analysis_queue import enqueue_discovery

router = APIRouter(tags=["website-discovery"])
DatabaseSession = Annotated[Session, Depends(get_db)]
SENSITIVE_QUERY_PATTERN = re.compile(
    r"(?:token|secret|password|passwd|session|auth|signature|key)", re.I
)


def website_or_raise(db: Session, website_id: uuid.UUID) -> Website:
    website = db.get(Website, website_id)
    if website is None:
        raise ApplicationError(
            code="WEBSITE_NOT_FOUND",
            message="Website not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return website


def safe_url(url: str | None) -> str | None:
    if not url:
        return url
    parsed = urlsplit(url)
    query = [
        (key, "[redacted]" if SENSITIVE_QUERY_PATTERN.search(key) else value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
    ]
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))


def page_read(page: WebsitePage) -> WebsitePageRead:
    value = WebsitePageRead.model_validate(page)
    evidence = [
        {
            key: safe_url(item_value)
            if key in {"original_url", "source_page_url"} and isinstance(item_value, str)
            else item_value
            for key, item_value in item.items()
        }
        for item in value.discovery_evidence
    ]
    return value.model_copy(
        update={
            "normalized_url": safe_url(value.normalized_url),
            "original_url": safe_url(value.original_url),
            "final_url": safe_url(value.final_url),
            "canonical_url": safe_url(value.canonical_url),
            "source_page_url": safe_url(value.source_page_url),
            "discovery_evidence": evidence,
        }
    )


@router.post(
    "/websites/{website_id}/discovery-runs",
    response_model=DiscoveryRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_discovery(website_id: uuid.UUID, db: DatabaseSession) -> DiscoveryRun:
    website_or_raise(db, website_id)
    run = DiscoveryRun(website_id=website_id, current_stage="queued")
    db.add(run)
    db.commit()
    db.refresh(run)
    try:
        run.celery_task_id = enqueue_discovery(str(run.id))
    except Exception as exception:
        run.status = DiscoveryStatus.FAILED
        run.progress_percent = 100
        run.current_stage = "failed"
        run.failure_code = "DISCOVERY_QUEUE_UNAVAILABLE"
        run.failure_message = "Website discovery could not be queued."
        db.commit()
        raise ApplicationError(
            code="DISCOVERY_QUEUE_UNAVAILABLE",
            message="Website discovery could not be queued.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exception
    db.commit()
    db.refresh(run)
    return run


@router.get("/discovery-runs/{run_id}", response_model=DiscoveryRunRead)
def get_discovery_run(run_id: uuid.UUID, db: DatabaseSession) -> DiscoveryRun:
    run = db.get(DiscoveryRun, run_id)
    if run is None:
        raise ApplicationError(
            code="DISCOVERY_RUN_NOT_FOUND",
            message="Discovery run not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return run


@router.get("/websites/{website_id}/pages", response_model=WebsitePageList)
def list_pages(
    website_id: uuid.UUID,
    db: DatabaseSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    eligibility: Literal["eligible", "excluded", "skipped"] | None = None,
    page_type: str | None = Query(default=None, max_length=50),
    discovery_source: str | None = Query(default=None, max_length=50),
    robots_status: Literal["allowed", "disallowed", "unknown"] | None = None,
    latest_analysis_status: Literal["pending", "completed", "partial", "failed"] | None = None,
    search: str | None = Query(default=None, max_length=200),
) -> WebsitePageList:
    website_or_raise(db, website_id)
    latest_run_id = db.scalar(
        select(DiscoveryRun.id)
        .where(DiscoveryRun.website_id == website_id)
        .order_by(DiscoveryRun.created_at.desc(), DiscoveryRun.id.desc())
        .limit(1)
    )
    filters = [WebsitePage.website_id == website_id]
    if latest_run_id:
        filters.append(WebsitePage.last_discovery_run_id == latest_run_id)
    if eligibility:
        filters.append(WebsitePage.eligibility_status == eligibility)
    if page_type:
        filters.append(WebsitePage.page_type == page_type)
    if discovery_source:
        filters.append(WebsitePage.discovery_source == discovery_source)
    if robots_status:
        filters.append(WebsitePage.robots_status == robots_status)
    if latest_analysis_status:
        filters.append(WebsitePage.latest_analysis_status == latest_analysis_status)
    if search:
        filters.append(
            or_(
                WebsitePage.normalized_url.ilike(f"%{search}%"),
                WebsitePage.page_title.ilike(f"%{search}%"),
            )
        )
    total = db.scalar(select(func.count()).select_from(WebsitePage).where(*filters)) or 0
    rows = list(
        db.scalars(
            select(WebsitePage)
            .where(*filters)
            .order_by(WebsitePage.normalized_url.asc(), WebsitePage.id.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return WebsitePageList(
        items=[page_read(item) for item in rows],
        page=page,
        page_size=page_size,
        total=total,
        total_pages=math.ceil(total / page_size) if total else 0,
    )


@router.get("/website-pages/{page_id}", response_model=WebsitePageRead)
def get_page(page_id: uuid.UUID, db: DatabaseSession) -> WebsitePageRead:
    page = db.get(WebsitePage, page_id)
    if page is None:
        raise ApplicationError(
            code="WEBSITE_PAGE_NOT_FOUND",
            message="Discovered page not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return page_read(page)


@router.get("/websites/{website_id}/coverage", response_model=CoverageSummary)
def coverage(website_id: uuid.UUID, db: DatabaseSession) -> CoverageSummary:
    website_or_raise(db, website_id)
    run = db.scalar(
        select(DiscoveryRun)
        .where(DiscoveryRun.website_id == website_id)
        .order_by(DiscoveryRun.created_at.desc(), DiscoveryRun.id.desc())
        .limit(1)
    )
    if run is None:
        return CoverageSummary(
            website_id=website_id,
            discovery_run_id=None,
            discovered_urls=0,
            unique_pages=0,
            eligible_pages=0,
            excluded_pages=0,
            skipped_pages=0,
            robots_disallowed_pages=0,
            analyzed_pages=0,
            completed_analyses=0,
            partial_analyses=0,
            failed_analyses=0,
            pending_analyses=0,
            pages_requiring_action=0,
            pages_without_findings=0,
            analyzed_coverage_numerator=0,
            analyzed_coverage_denominator=0,
            analyzed_coverage_percent=None,
            crawl_limit_reached=False,
            maximum_depth_reached=0,
            calculated_at=datetime.now(UTC),
        )
    pages = list(
        db.scalars(
            select(WebsitePage).where(
                WebsitePage.website_id == website_id,
                WebsitePage.last_discovery_run_id == run.id,
            )
        )
    )
    eligible = [item for item in pages if item.eligibility_status == "eligible"]
    completed = sum(item.latest_analysis_status == "completed" for item in eligible)
    partial = sum(item.latest_analysis_status == "partial" for item in eligible)
    failed = sum(item.latest_analysis_status == "failed" for item in eligible)
    analyzed = completed + partial + failed
    analyzed_ids = [item.latest_analysis_run_id for item in eligible if item.latest_analysis_run_id]
    action_runs = (
        set(
            db.scalars(
                select(AnalysisFinding.analysis_run_id)
                .where(AnalysisFinding.analysis_run_id.in_(analyzed_ids))
                .distinct()
            )
        )
        if analyzed_ids
        else set()
    )
    denominator = len(eligible)
    return CoverageSummary(
        website_id=website_id,
        discovery_run_id=run.id,
        discovered_urls=run.urls_discovered,
        unique_pages=len(pages),
        eligible_pages=denominator,
        excluded_pages=sum(item.eligibility_status == "excluded" for item in pages),
        skipped_pages=sum(item.eligibility_status == "skipped" for item in pages),
        robots_disallowed_pages=sum(item.robots_status == "disallowed" for item in pages),
        analyzed_pages=analyzed,
        completed_analyses=completed,
        partial_analyses=partial,
        failed_analyses=failed,
        pending_analyses=sum(item.latest_analysis_status == "pending" for item in eligible),
        pages_requiring_action=len(action_runs),
        pages_without_findings=max(0, analyzed - len(action_runs)),
        analyzed_coverage_numerator=analyzed,
        analyzed_coverage_denominator=denominator,
        analyzed_coverage_percent=(round(analyzed / denominator * 100, 1) if denominator else None),
        crawl_limit_reached=run.crawl_limit_reached,
        maximum_depth_reached=run.maximum_depth_reached,
        calculated_at=datetime.now(UTC),
    )
