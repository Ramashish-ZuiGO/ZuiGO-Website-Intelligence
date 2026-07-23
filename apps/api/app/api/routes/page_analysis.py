import math
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.errors.exceptions import ApplicationError
from app.models import (
    AnalysisFinding,
    PageAnalysisRun,
    Website,
    WebsitePage,
)
from app.schemas import (
    PageAnalysisActionRecommendation,
    PageAnalysisRunList,
    PageAnalysisRunRead,
    PageAnalysisSummary,
    PageLevelScore,
    SiteCoverageDetail,
)
from app.services.analysis_queue import enqueue_page_analysis

router = APIRouter(prefix="/websites/{website_id}/page-analysis", tags=["page-analysis"])
DatabaseSession = Annotated[Session, Depends(get_db)]


def website_or_raise(db: Session, website_id: uuid.UUID) -> Website:
    website = db.get(Website, website_id)
    if website is None:
        raise ApplicationError(
            code="WEBSITE_NOT_FOUND",
            message="Website not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return website


@router.post("/run", status_code=status.HTTP_202_ACCEPTED)
def start_page_analysis(
    website_id: uuid.UUID,
    db: DatabaseSession,
) -> dict[str, Any]:
    website_or_raise(db, website_id)
    latest_run = db.scalar(
        select(Website)
        .join(Website.discovery_runs)
        .where(Website.id == website_id)
        .order_by(Website.id.desc())
    )
    if latest_run is None:
        latest_run_id = db.scalar(
            select(WebsitePage.last_discovery_run_id)
            .where(
                WebsitePage.website_id == website_id,
                WebsitePage.last_discovery_run_id.isnot(None),
            )
            .limit(1)
        )
        if latest_run_id is None:
            raise ApplicationError(
                code="NO_DISCOVERY_RUN",
                message="No discovery run exists for this website.",
                status_code=status.HTTP_409_CONFLICT,
            )
        discovery_run_id = latest_run_id
    else:
        from app.models.discovery_run import DiscoveryRun

        discovery = db.scalar(
            select(DiscoveryRun)
            .where(DiscoveryRun.website_id == website_id)
            .order_by(DiscoveryRun.created_at.desc(), DiscoveryRun.id.desc())
            .limit(1)
        )
        if discovery is None:
            raise ApplicationError(
                code="NO_DISCOVERY_RUN",
                message="No discovery run exists for this website.",
                status_code=status.HTTP_409_CONFLICT,
            )
        discovery_run_id = discovery.id

    execution_id = uuid.uuid4()

    try:
        task_id = enqueue_page_analysis(str(discovery_run_id), str(execution_id))
    except Exception as exception:
        raise ApplicationError(
            code="PAGE_ANALYSIS_QUEUE_UNAVAILABLE",
            message="Page analysis could not be queued.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exception

    return {
        "status": "queued",
        "celery_task_id": task_id,
        "discovery_run_id": str(discovery_run_id),
        "page_analysis_execution_id": str(execution_id),
    }


@router.get("/summary", response_model=PageAnalysisSummary)
def get_page_analysis_summary(
    website_id: uuid.UUID,
    db: DatabaseSession,
) -> PageAnalysisSummary:
    website_or_raise(db, website_id)
    pages = list(db.scalars(select(WebsitePage).where(WebsitePage.website_id == website_id)))
    eligible = [p for p in pages if p.eligibility_status == "eligible"]
    total_pages = len(pages)
    eligible_pages = len(eligible)

    l1_completed = sum(1 for p in eligible if p.page_analysis_level_1_status == "completed")
    l1_partial = sum(1 for p in eligible if p.page_analysis_level_1_status == "partial")
    l1_failed = sum(1 for p in eligible if p.page_analysis_level_1_status == "failed")
    l1_skipped = sum(1 for p in eligible if p.page_analysis_level_1_status == "skipped")
    l1_pending = sum(1 for p in eligible if p.page_analysis_level_1_status == "pending")

    l2_completed = sum(1 for p in eligible if p.page_analysis_level_2_status == "completed")
    l2_partial = sum(1 for p in eligible if p.page_analysis_level_2_status == "partial")
    l2_failed = sum(1 for p in eligible if p.page_analysis_level_2_status == "failed")
    l2_skipped = sum(1 for p in eligible if p.page_analysis_level_2_status == "skipped")
    l2_pending = sum(1 for p in eligible if p.page_analysis_level_2_status == "pending")

    analyzed_ids = [
        p.page_analysis_level_1_run_id for p in eligible if p.page_analysis_level_1_run_id
    ]
    finding_run_ids = (
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

    pages_with_findings = len(finding_run_ids)
    pages_without_findings = max(0, l1_completed - pages_with_findings)

    coverage_percent = (
        round((l1_completed + l1_partial + l1_failed) / eligible_pages * 100, 1)
        if eligible_pages
        else None
    )

    return PageAnalysisSummary(
        website_id=website_id,
        total_pages=total_pages,
        eligible_pages=eligible_pages,
        level_1_completed=l1_completed,
        level_1_partial=l1_partial,
        level_1_failed=l1_failed,
        level_1_skipped=l1_skipped,
        level_1_pending=l1_pending,
        level_2_completed=l2_completed,
        level_2_partial=l2_partial,
        level_2_failed=l2_failed,
        level_2_skipped=l2_skipped,
        level_2_pending=l2_pending,
        pages_with_findings=pages_with_findings,
        pages_without_findings=pages_without_findings,
        coverage_percent=coverage_percent,
    )


@router.get("/runs", response_model=PageAnalysisRunList)
def list_page_analysis_runs(
    website_id: uuid.UUID,
    db: DatabaseSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    analysis_level: int | None = Query(default=None, ge=1, le=2),
    status_filter: str | None = Query(default=None, max_length=30),
    search: str | None = Query(default=None, max_length=200),
) -> PageAnalysisRunList:
    website_or_raise(db, website_id)
    filters = [
        WebsitePage.website_id == website_id,
        WebsitePage.eligibility_status == "eligible",
    ]
    if analysis_level:
        if analysis_level == 1:
            filters.append(WebsitePage.page_analysis_level_1_run_id.isnot(None))
        else:
            filters.append(WebsitePage.page_analysis_level_2_run_id.isnot(None))
    if status_filter:
        level_col = (
            WebsitePage.page_analysis_level_1_status
            if analysis_level == 1 or analysis_level is None
            else WebsitePage.page_analysis_level_2_status
        )
        filters.append(level_col == status_filter)
    if search:
        filters.append(
            or_(
                WebsitePage.normalized_url.ilike(f"%{search}%"),
                WebsitePage.page_title.ilike(f"%{search}%"),
            )
        )

    total = db.scalar(select(func.count()).select_from(WebsitePage).where(*filters)) or 0

    level_col = (
        WebsitePage.page_analysis_level_1_status
        if analysis_level == 1
        else WebsitePage.page_analysis_level_2_status
        if analysis_level == 2
        else None
    )
    order = (
        [level_col.asc(), WebsitePage.normalized_url.asc()]
        if level_col is not None
        else [WebsitePage.normalized_url.asc()]
    )
    rows = list(
        db.scalars(
            select(WebsitePage)
            .where(*filters)
            .order_by(*order)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )

    items = []
    for wp in rows:
        run_id = (
            wp.page_analysis_level_1_run_id
            if analysis_level == 1 or analysis_level is None
            else wp.page_analysis_level_2_run_id
        )
        run = db.get(PageAnalysisRun, run_id) if run_id else None
        if run:
            items.append(PageAnalysisRunRead.model_validate(run))
        elif analysis_level is None and wp.page_analysis_level_2_run_id:
            run = db.get(PageAnalysisRun, wp.page_analysis_level_2_run_id)
            if run:
                items.append(PageAnalysisRunRead.model_validate(run))

    return PageAnalysisRunList(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        total_pages=math.ceil(total / page_size) if total else 0,
    )


@router.get("/runs/{run_id}", response_model=PageAnalysisRunRead)
def get_page_analysis_run(
    run_id: uuid.UUID,
    db: DatabaseSession,
) -> PageAnalysisRunRead:
    run = db.get(PageAnalysisRun, run_id)
    if run is None:
        raise ApplicationError(
            code="PAGE_ANALYSIS_RUN_NOT_FOUND",
            message="Page analysis run not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return PageAnalysisRunRead.model_validate(run)


@router.get("/coverage", response_model=SiteCoverageDetail)
def get_site_coverage_detail(
    website_id: uuid.UUID,
    db: DatabaseSession,
) -> SiteCoverageDetail:
    website_or_raise(db, website_id)
    pages = list(db.scalars(select(WebsitePage).where(WebsitePage.website_id == website_id)))
    eligible = [p for p in pages if p.eligibility_status == "eligible"]

    discovered_page_count = len(pages)
    eligible_page_count = len(eligible)

    l1_attempted = sum(
        1 for p in eligible if p.page_analysis_level_1_status in ("completed", "partial", "failed")
    )
    l1_successful = sum(1 for p in eligible if p.page_analysis_level_1_status == "completed")
    l1_failed = sum(1 for p in eligible if p.page_analysis_level_1_status == "failed")
    l1_partial = sum(1 for p in eligible if p.page_analysis_level_1_status == "partial")

    l2_attempted = sum(
        1 for p in eligible if p.page_analysis_level_2_status in ("completed", "partial", "failed")
    )
    l2_successful = sum(1 for p in eligible if p.page_analysis_level_2_status == "completed")
    l2_failed = sum(1 for p in eligible if p.page_analysis_level_2_status == "failed")
    l2_partial = sum(1 for p in eligible if p.page_analysis_level_2_status == "partial")

    skipped = sum(1 for p in eligible if p.page_analysis_level_1_status == "skipped")
    unanalyzed = sum(1 for p in eligible if p.page_analysis_level_1_status == "pending")

    coverage_percent = (
        round(l1_attempted / eligible_page_count * 100, 1) if eligible_page_count else None
    )

    clean_pass = (
        round(l1_successful / eligible_page_count * 100, 1) if eligible_page_count else None
    )

    limitations = []
    if l1_attempted < eligible_page_count:
        limitations.append(
            f"Only {l1_attempted} of {eligible_page_count} eligible pages analyzed "
            f"({eligible_page_count - l1_attempted} pending or skipped)."
        )

    return SiteCoverageDetail(
        website_id=website_id,
        discovery_run_id=None,
        discovered_page_count=discovered_page_count,
        eligible_page_count=eligible_page_count,
        selected_page_count=min(discovered_page_count, 50),
        level_1_attempted=l1_attempted,
        level_1_successful=l1_successful,
        level_1_failed=l1_failed,
        level_1_partial=l1_partial,
        level_2_attempted=l2_attempted,
        level_2_successful=l2_successful,
        level_2_failed=l2_failed,
        level_2_partial=l2_partial,
        skipped_page_count=skipped,
        unanalyzed_eligible_count=unanalyzed,
        coverage_percent=coverage_percent,
        clean_pass_percent=clean_pass,
        partial_result_status=l1_partial > 0 or l2_partial > 0,
        coverage_limitations=limitations,
        calculated_at=datetime.now(UTC),
    )


@router.get("/pages-with-issues")
def get_pages_with_issues(
    website_id: uuid.UUID,
    db: DatabaseSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> dict[str, Any]:
    website_or_raise(db, website_id)

    failed_pages = list(
        db.scalars(
            select(WebsitePage)
            .where(
                WebsitePage.website_id == website_id,
                WebsitePage.eligibility_status == "eligible",
                or_(
                    WebsitePage.page_analysis_level_1_status.in_(["failed", "partial", "skipped"]),
                    WebsitePage.page_analysis_level_2_status.in_(["failed", "partial", "skipped"]),
                ),
            )
            .order_by(WebsitePage.normalized_url.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    total = (
        db.scalar(
            select(func.count())
            .select_from(WebsitePage)
            .where(
                WebsitePage.website_id == website_id,
                WebsitePage.eligibility_status == "eligible",
                or_(
                    WebsitePage.page_analysis_level_1_status.in_(["failed", "partial", "skipped"]),
                    WebsitePage.page_analysis_level_2_status.in_(["failed", "partial", "skipped"]),
                ),
            )
        )
        or 0
    )

    items = []
    for wp in failed_pages:
        l1_run = (
            db.get(PageAnalysisRun, wp.page_analysis_level_1_run_id)
            if wp.page_analysis_level_1_run_id
            else None
        )
        l2_run = (
            db.get(PageAnalysisRun, wp.page_analysis_level_2_run_id)
            if wp.page_analysis_level_2_run_id
            else None
        )
        issues = []
        if l1_run and l1_run.status in ("failed", "skipped"):
            issues.append(
                {
                    "level": 1,
                    "status": l1_run.status,
                    "reason_code": l1_run.failure_reason_code,
                    "reason_text": l1_run.failure_reason_text,
                }
            )
        if l2_run and l2_run.status in ("failed", "skipped"):
            issues.append(
                {
                    "level": 2,
                    "status": l2_run.status,
                    "reason_code": l2_run.failure_reason_code,
                    "reason_text": l2_run.failure_reason_text,
                }
            )
        items.append(
            {
                "page_id": str(wp.id),
                "page_url": wp.normalized_url,
                "page_title": wp.page_title,
                "page_type": wp.page_type,
                "issues": issues,
            }
        )

    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": math.ceil(total / page_size) if total else 0,
    }


@router.get("/scores", response_model=list[PageLevelScore])
def get_page_level_scores(
    website_id: uuid.UUID,
    db: DatabaseSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> list[PageLevelScore]:
    website_or_raise(db, website_id)
    rows = list(
        db.scalars(
            select(WebsitePage)
            .where(
                WebsitePage.website_id == website_id,
                WebsitePage.eligibility_status == "eligible",
            )
            .order_by(WebsitePage.normalized_url.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    results = []
    for wp in rows:
        l1_run = (
            db.get(PageAnalysisRun, wp.page_analysis_level_1_run_id)
            if wp.page_analysis_level_1_run_id
            else None
        )
        l2_run = (
            db.get(PageAnalysisRun, wp.page_analysis_level_2_run_id)
            if wp.page_analysis_level_2_run_id
            else None
        )

        if l2_run and l2_run.status == "completed":
            from app.models.analysis_score import AnalysisScore

            score_row = (
                db.scalar(
                    select(AnalysisScore).where(
                        AnalysisScore.analysis_run_id == l2_run.deep_analysis_run_id
                    )
                )
                if l2_run.deep_analysis_run_id
                else None
            )
            if score_row:
                results.append(
                    PageLevelScore(
                        page_id=wp.id,
                        page_url=wp.normalized_url,
                        page_title=wp.page_title,
                        analysis_level=2,
                        analysis_status=l2_run.status,
                        score=score_row.overall_score,
                        confidence=(
                            "high"
                            if (score_row.confidence_percent or 0) >= 80
                            else "medium"
                            if (score_row.confidence_percent or 0) >= 50
                            else "low"
                        ),
                        score_available=True,
                    )
                )
                continue

        results.append(
            PageLevelScore(
                page_id=wp.id,
                page_url=wp.normalized_url,
                page_title=wp.page_title,
                analysis_level=1,
                analysis_status=l1_run.status if l1_run else "pending",
                score=None,
                confidence="unavailable",
                score_available=False,
            )
        )

    return results


@router.get("/recommendations", response_model=list[PageAnalysisActionRecommendation])
def get_page_analysis_recommendations(
    website_id: uuid.UUID,
    db: DatabaseSession,
) -> list[PageAnalysisActionRecommendation]:
    website_or_raise(db, website_id)
    pages = list(
        db.scalars(
            select(WebsitePage).where(
                WebsitePage.website_id == website_id,
                WebsitePage.eligibility_status == "eligible",
            )
        )
    )
    recommendations: list[PageAnalysisActionRecommendation] = []

    for wp in pages:
        l1_run = (
            db.get(PageAnalysisRun, wp.page_analysis_level_1_run_id)
            if wp.page_analysis_level_1_run_id
            else None
        )
        if l1_run and l1_run.status == "completed":
            signals = l1_run.basic_seo_signals
            if signals.get("no_h1"):
                recommendations.append(
                    PageAnalysisActionRecommendation(
                        page_id=wp.id,
                        page_url=wp.normalized_url,
                        page_title=wp.page_title,
                        issue_title="Missing H1 heading",
                        issue_category="seo",
                        severity="medium",
                        evidence={"h1_count": 0},
                        responsible_area="CMS/content",
                        responsible_role="Content editor",
                        action_location="Page content template",
                        remediation="Add a single H1 heading that describes the page topic.",
                        verification_method="Inspect the rendered page source for an <h1> element.",
                        source="page_analysis",
                        confidence="high",
                        analysis_level=1,
                    )
                )
            if signals.get("multiple_h1"):
                recommendations.append(
                    PageAnalysisActionRecommendation(
                        page_id=wp.id,
                        page_url=wp.normalized_url,
                        page_title=wp.page_title,
                        issue_title="Multiple H1 headings",
                        issue_category="seo",
                        severity="low",
                        evidence={"h1_count": signals.get("h1_count", 0)},
                        responsible_area="CMS/content",
                        responsible_role="Content editor",
                        action_location="Page content template",
                        remediation="Use only one H1 per page.",
                        verification_method="Review the page heading structure.",
                        source="page_analysis",
                        confidence="high",
                        analysis_level=1,
                    )
                )
            if not signals.get("has_title"):
                recommendations.append(
                    PageAnalysisActionRecommendation(
                        page_id=wp.id,
                        page_url=wp.normalized_url,
                        page_title=wp.page_title,
                        issue_title="Missing page title",
                        issue_category="seo",
                        severity="high",
                        evidence={},
                        responsible_area="CMS/content",
                        responsible_role="Content editor",
                        action_location="Page metadata",
                        remediation="Add a descriptive <title> tag to the page.",
                        verification_method="Check the <title> element in the HTML head.",
                        source="page_analysis",
                        confidence="high",
                        analysis_level=1,
                    )
                )
            if not signals.get("has_meta_description"):
                recommendations.append(
                    PageAnalysisActionRecommendation(
                        page_id=wp.id,
                        page_url=wp.normalized_url,
                        page_title=wp.page_title,
                        issue_title="Missing meta description",
                        issue_category="seo",
                        severity="medium",
                        evidence={},
                        responsible_area="CMS/content",
                        responsible_role="Content editor",
                        action_location="Page metadata",
                        remediation="Add a meta description summarizing the page content.",
                        verification_method="Check the meta description element in the HTML head.",
                        source="page_analysis",
                        confidence="high",
                        analysis_level=1,
                    )
                )
            if not signals.get("has_canonical"):
                recommendations.append(
                    PageAnalysisActionRecommendation(
                        page_id=wp.id,
                        page_url=wp.normalized_url,
                        page_title=wp.page_title,
                        issue_title="Missing canonical URL",
                        issue_category="seo",
                        severity="medium",
                        evidence={},
                        responsible_area="frontend",
                        responsible_role="Developer",
                        action_location="Page head template",
                        remediation="Add a canonical link element to the HTML head.",
                        verification_method="Check for a canonical link element in the HTML head.",
                        source="page_analysis",
                        confidence="high",
                        analysis_level=1,
                    )
                )

            a11y = l1_run.basic_accessibility_signals
            images_missing = a11y.get("images_missing_alt", 0) or 0
            if images_missing > 0:
                recommendations.append(
                    PageAnalysisActionRecommendation(
                        page_id=wp.id,
                        page_url=wp.normalized_url,
                        page_title=wp.page_title,
                        issue_title=f"{images_missing} images missing alt text",
                        issue_category="accessibility",
                        severity="medium",
                        evidence={"images_missing_alt": images_missing},
                        responsible_area="CMS/content",
                        responsible_role="Content editor",
                        action_location="Image component",
                        remediation="Add descriptive alt attributes to all images.",
                        verification_method="Use an accessibility checker to audit alt text.",
                        source="page_analysis",
                        confidence="high",
                        analysis_level=1,
                    )
                )
            if not a11y.get("has_html_lang"):
                recommendations.append(
                    PageAnalysisActionRecommendation(
                        page_id=wp.id,
                        page_url=wp.normalized_url,
                        page_title=wp.page_title,
                        issue_title="Missing HTML lang attribute",
                        issue_category="accessibility",
                        severity="medium",
                        evidence={},
                        responsible_area="frontend",
                        responsible_role="Developer",
                        action_location="Root HTML element",
                        remediation='Add lang="..." attribute to the <html> element.',
                        verification_method="Inspect the <html> tag for the lang attribute.",
                        source="page_analysis",
                        confidence="high",
                        analysis_level=1,
                    )
                )

            security = l1_run.security_observations
            if not security.get("https"):
                recommendations.append(
                    PageAnalysisActionRecommendation(
                        page_id=wp.id,
                        page_url=wp.normalized_url,
                        page_title=wp.page_title,
                        issue_title="Page not served over HTTPS",
                        issue_category="security",
                        severity="high",
                        evidence={"https": False},
                        responsible_area="CDN/server",
                        responsible_role="DevOps",
                        action_location="Web server configuration",
                        remediation="Configure HTTPS with a valid TLS certificate and redirect HTTP to HTTPS.",  # noqa: E501
                        verification_method="Check browser padlock and redirect chain.",
                        source="page_analysis",
                        confidence="high",
                        analysis_level=1,
                    )
                )
            if not security.get("x_frame_options"):
                recommendations.append(
                    PageAnalysisActionRecommendation(
                        page_id=wp.id,
                        page_url=wp.normalized_url,
                        page_title=wp.page_title,
                        issue_title="Missing X-Frame-Options header",
                        issue_category="security",
                        severity="medium",
                        evidence={},
                        responsible_area="CDN/server",
                        responsible_role="DevOps",
                        action_location="HTTP response headers",
                        remediation="Add X-Frame-Options: DENY or SAMEORIGIN to prevent clickjacking.",  # noqa: E501
                        verification_method="Check response headers using browser DevTools or curl.",  # noqa: E501
                        source="page_analysis",
                        confidence="high",
                        analysis_level=1,
                    )
                )
            if not security.get("x_content_type_options"):
                recommendations.append(
                    PageAnalysisActionRecommendation(
                        page_id=wp.id,
                        page_url=wp.normalized_url,
                        page_title=wp.page_title,
                        issue_title="Missing X-Content-Type-Options header",
                        issue_category="security",
                        severity="medium",
                        evidence={},
                        responsible_area="CDN/server",
                        responsible_role="DevOps",
                        action_location="HTTP response headers",
                        remediation="Add X-Content-Type-Options: nosniff to prevent MIME sniffing.",
                        verification_method="Check response headers.",
                        source="page_analysis",
                        confidence="high",
                        analysis_level=1,
                    )
                )

        if l1_run and l1_run.status == "failed":
            recommendations.append(
                PageAnalysisActionRecommendation(
                    page_id=wp.id,
                    page_url=wp.normalized_url,
                    page_title=wp.page_title,
                    issue_title=f"Page analysis failed: {l1_run.failure_reason_code or 'unknown'}",
                    issue_category="technical",
                    severity="high"
                    if l1_run.failure_reason_code in ("unsafe_url", "redirect_outside_origin")
                    else "medium",
                    evidence={"failure_reason_code": l1_run.failure_reason_code},
                    responsible_area="backend",
                    responsible_role="Developer",
                    action_location="Page URL or server configuration",
                    remediation=(
                        "Check that the page URL is accessible and returns HTML content. "
                        "Verify robots.txt does not block the URL. "
                        f"Reason: {l1_run.failure_reason_text or 'Unknown'}"
                    ),
                    verification_method="Visit the page URL in a browser and check server logs.",
                    source="page_analysis",
                    confidence="high",
                    analysis_level=1,
                )
            )

    return recommendations


@router.get("/failed-skipped")
def get_failed_skipped_pages(
    website_id: uuid.UUID,
    db: DatabaseSession,
) -> list[dict[str, Any]]:
    website_or_raise(db, website_id)
    rows = list(
        db.scalars(
            select(WebsitePage)
            .where(
                WebsitePage.website_id == website_id,
                WebsitePage.eligibility_status == "eligible",
                or_(
                    WebsitePage.page_analysis_level_1_status.in_(["failed", "skipped"]),
                    WebsitePage.page_analysis_level_2_status.in_(["failed", "skipped"]),
                ),
            )
            .order_by(WebsitePage.normalized_url.asc())
        )
    )
    result = []
    for wp in rows:
        l1_run = (
            db.get(PageAnalysisRun, wp.page_analysis_level_1_run_id)
            if wp.page_analysis_level_1_run_id
            else None
        )
        l2_run = (
            db.get(PageAnalysisRun, wp.page_analysis_level_2_run_id)
            if wp.page_analysis_level_2_run_id
            else None
        )
        statuses = {}
        if l1_run and l1_run.status in ("failed", "skipped"):
            statuses["level_1"] = {
                "status": l1_run.status,
                "reason_code": l1_run.failure_reason_code,
                "reason_text": l1_run.failure_reason_text,
            }
        if l2_run and l2_run.status in ("failed", "skipped"):
            statuses["level_2"] = {
                "status": l2_run.status,
                "reason_code": l2_run.failure_reason_code,
                "reason_text": l2_run.failure_reason_text,
            }
        if statuses:
            result.append(
                {
                    "page_id": str(wp.id),
                    "page_url": wp.normalized_url,
                    "page_title": wp.page_title,
                    "page_type": wp.page_type,
                    "statuses": statuses,
                }
            )
    return result
