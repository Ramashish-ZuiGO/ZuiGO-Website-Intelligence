import hashlib
import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_db
from app.errors.exceptions import ApplicationError
from app.models import (
    AgentCheckpoint,
    AgentExecution,
    AgentRun,
    AnalysisRun,
    AnalysisStatus,
    DiscoveryRun,
    DiscoveryRunPage,
    DiscoveryStatus,
    PageAnalysisRun,
    Project,
    ReportExecution,
    ScoreExecution,
    Website,
    WebsitePage,
)
from app.schemas.agent_platform import WorkflowExecutionCreate
from app.schemas.report_delivery import (
    AnalysisJourneyStartRead,
    AnalysisJourneyStartRequest,
    EvidenceCoverageRead,
    PaginatedReports,
    RealWebsiteAnalysisStartRead,
    RealWebsiteAnalysisStartRequest,
    RecentRealAnalysisRead,
    ReportArtifactList,
    ReportExecutionRead,
    ReportGenerateRequest,
    ReportStatusRead,
    WorkflowProgressRead,
)
from app.services import profiles_registry
from app.services.agent_platform_registry import WorkflowRegistry
from app.services.analysis_queue import (
    enqueue_analysis_journey,
    enqueue_real_analysis_journey,
)
from app.services.page_selection import select_scheduled_pages
from app.services.public_url_safety import (
    PublicURLSafetyError,
    validate_and_normalize_public_url,
)
from app.services.report_delivery import (
    TEMPLATE_VERSION,
    ReportDeliveryError,
    _discovery_message,
    generate_report,
    load_artifact,
    load_report,
    render_additional_report_artifact,
)
from app.services.resource_classification import (
    ResourceClassification,
    classify_resource,
)
from app.services.tool_execution import sanitize_persisted_value
from app.services.workflow_execution import (
    TERMINAL_EXECUTION_STATUSES,
    WorkflowExecutionError,
    create_workflow_execution,
    real_execution_is_stale,
    real_execution_last_update,
    record_dispatch,
)

router = APIRouter(tags=["Report delivery"])
DatabaseSession = Annotated[Session, Depends(get_db)]


def _report_error(exception: ReportDeliveryError) -> ApplicationError:
    return ApplicationError(
        code=exception.code,
        message=exception.safe_message,
        status_code=exception.status_code,
    )


def _workflow_error(exception: WorkflowExecutionError) -> ApplicationError:
    return ApplicationError(
        code=exception.code,
        message=exception.message,
        status_code=exception.status_code,
    )


def _real_start_read(
    execution: AgentExecution,
    analysis_run: AnalysisRun,
    *,
    reused: bool,
) -> RealWebsiteAnalysisStartRead:
    payload = execution.structured_input
    return RealWebsiteAnalysisStartRead(
        project_id=execution.project_id,
        website_id=uuid.UUID(str(payload["website_id"])),
        analysis_run_id=analysis_run.id,
        discovery_run_id=uuid.UUID(str(payload["discovery_run_id"])),
        page_analysis_execution_id=uuid.UUID(str(payload["page_analysis_execution_id"])),
        workflow_execution_id=execution.execution_id,
        submitted_url=str(payload["submitted_url"]),
        normalized_url=str(payload["normalized_url"]),
        analysis_status=analysis_run.status.value,
        workflow_status=str(execution.structured_output.get("journey_status") or execution.status),
        reused=reused,
    )


@router.post(
    "/analysis/start",
    response_model=RealWebsiteAnalysisStartRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_real_website_analysis(
    request: RealWebsiteAnalysisStartRequest,
    db: DatabaseSession,
) -> RealWebsiteAnalysisStartRead:
    try:
        normalized_url = validate_and_normalize_public_url(request.website_url)
    except PublicURLSafetyError as exception:
        raise ApplicationError(
            code=exception.code,
            message=exception.safe_message,
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        ) from exception

    existing = db.scalar(
        select(AgentExecution)
        .where(
            AgentExecution.workflow_id == "full_website_analysis",
            AgentExecution.workflow_version == "1.0.0",
            AgentExecution.idempotency_key == request.idempotency_key,
        )
        .order_by(AgentExecution.created_at.desc(), AgentExecution.id.desc())
    )
    if existing is not None:
        if (
            existing.structured_input.get("normalized_url") != normalized_url
            or not existing.structured_input.get("discovery_run_id")
            or existing.analysis_run_id is None
        ):
            raise ApplicationError(
                code="ANALYSIS_IDEMPOTENCY_CONFLICT",
                message="The idempotency key belongs to a different analysis request.",
                status_code=status.HTTP_409_CONFLICT,
            )
        analysis_run = db.get(AnalysisRun, existing.analysis_run_id)
        if analysis_run is None:
            raise ApplicationError(
                code="ANALYSIS_RUN_NOT_FOUND",
                message="The retained analysis run is unavailable.",
                status_code=status.HTTP_409_CONFLICT,
            )
        return _real_start_read(existing, analysis_run, reused=True)

    website = db.scalar(
        select(Website)
        .where(Website.url == normalized_url)
        .order_by(Website.created_at, Website.id)
    )
    if website is None:
        hostname = urlsplit(normalized_url).hostname or "Website"
        project = Project(
            name=f"{hostname} website analysis",
            description="Created from the real website analysis homepage.",
        )
        db.add(project)
        db.flush()
        website = Website(
            project_id=project.id,
            url=normalized_url,
            name=hostname,
        )
        db.add(website)
        db.flush()
    project = db.get(Project, website.project_id)
    assert project is not None

    page_analysis_execution_id = uuid.uuid4()
    # Standard workflow schedules engineering-signal engines only. Firefox is
    # outside the locked customer UAT contract (Chrome/Edge/Safari) and is not
    # scheduled here; the request's verbatim engine list is retained for audit.
    scheduled_engines = [engine for engine in request.browser_engines if engine != "firefox"] or [
        "chromium",
        "webkit",
    ]
    discovery = DiscoveryRun(
        website_id=website.id,
        current_stage="queued",
        configuration={
            "maximum_pages": request.maximum_pages,
            "max_html_pages": request.maximum_pages,
            "max_lighthouse_pages": 0,
            "browser_engines": scheduled_engines,
            "requested_browser_engines": list(request.browser_engines),
            "include_mobile": request.include_mobile,
            "submitted_url": request.website_url,
            "normalized_url": normalized_url,
            "page_analysis_execution_id": str(page_analysis_execution_id),
        },
    )
    profile = profiles_registry.get_profile(website.profile_id)
    if profile is None:
        profile = profiles_registry.get_profile("global_general")
    assert profile is not None
    analysis_run = AnalysisRun(
        website_id=website.id,
        profile_id=profile.profile_id,
        profile_version=profile.version,
    )
    db.add_all([discovery, analysis_run])
    db.flush()
    try:
        execution, created = create_workflow_execution(
            db,
            WorkflowExecutionCreate(
                workflow_id="full_website_analysis",
                project_id=project.id,
                analysis_run_id=analysis_run.id,
                website_id=website.id,
                page_analysis_execution_id=page_analysis_execution_id,
                discovery_run_id=discovery.id,
                submitted_url=request.website_url,
                normalized_url=normalized_url,
                maximum_pages=request.maximum_pages,
                browser_engines=scheduled_engines,
                include_mobile=request.include_mobile,
                execute_repository_agent=True,
                idempotency_key=request.idempotency_key,
                max_concurrency=request.max_concurrency,
            ),
        )
    except WorkflowExecutionError as exception:
        db.rollback()
        raise _workflow_error(exception) from exception
    if not created:
        persisted_run = db.get(AnalysisRun, execution.analysis_run_id)
        assert persisted_run is not None
        return _real_start_read(execution, persisted_run, reused=True)
    try:
        task_id = enqueue_real_analysis_journey(
            str(analysis_run.id),
            str(discovery.id),
            str(page_analysis_execution_id),
            str(execution.execution_id),
            workflow_attempt=execution.attempt,
        )
    except Exception as exception:
        analysis_run.status = AnalysisStatus.FAILED
        analysis_run.error_code = "REAL_ANALYSIS_QUEUE_UNAVAILABLE"
        analysis_run.error_message = "The website analysis could not be queued."
        discovery.status = DiscoveryStatus.FAILED
        discovery.current_stage = "failed"
        discovery.progress_percent = 100
        discovery.failure_code = "REAL_ANALYSIS_QUEUE_UNAVAILABLE"
        discovery.failure_message = "The website analysis could not be queued."
        execution.status = "failed"
        execution.failure_details = {
            "code": "REAL_ANALYSIS_QUEUE_UNAVAILABLE",
            "message": "The website analysis could not be queued.",
            "transient": True,
        }
        db.commit()
        raise ApplicationError(
            code="REAL_ANALYSIS_QUEUE_UNAVAILABLE",
            message="The website analysis could not be queued.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exception
    analysis_run.celery_task_id = task_id
    discovery.celery_task_id = task_id
    record_dispatch(db, execution, task_id)
    db.refresh(analysis_run)
    db.refresh(execution)
    return _real_start_read(execution, analysis_run, reused=False)


@router.get("/analysis/recent", response_model=list[RecentRealAnalysisRead])
def recent_real_analyses(
    db: DatabaseSession,
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
) -> list[RecentRealAnalysisRead]:
    executions = list(
        db.scalars(
            select(AgentExecution)
            .where(
                AgentExecution.workflow_id == "full_website_analysis",
                AgentExecution.structured_input["normalized_url"].as_string().isnot(None),
            )
            .order_by(AgentExecution.created_at.desc(), AgentExecution.id.desc())
            .limit(limit)
        )
    )
    return [
        RecentRealAnalysisRead(
            project_id=item.project_id,
            website_id=uuid.UUID(str(item.structured_input["website_id"])),
            analysis_run_id=uuid.UUID(str(item.structured_input["analysis_run_id"])),
            workflow_execution_id=item.execution_id,
            submitted_url=str(item.structured_input["submitted_url"]),
            normalized_url=str(item.structured_input["normalized_url"]),
            status=item.status,
            created_at=item.created_at,
        )
        for item in executions
    ]


@router.post(
    "/projects/{project_id}/websites/{website_id}/analysis/start",
    response_model=AnalysisJourneyStartRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_analysis_journey(
    project_id: uuid.UUID,
    website_id: uuid.UUID,
    request: AnalysisJourneyStartRequest,
    db: DatabaseSession,
) -> AnalysisJourneyStartRead:
    website = db.get(Website, website_id)
    if website is None:
        raise ApplicationError(
            code="WEBSITE_NOT_FOUND",
            message="Website not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    if website.project_id != project_id:
        raise ApplicationError(
            code="ANALYSIS_SCOPE_MISMATCH",
            message="Website does not belong to the requested project.",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    existing = db.scalar(
        select(AgentExecution).where(
            AgentExecution.project_id == project_id,
            AgentExecution.workflow_id == "full_website_analysis",
            AgentExecution.workflow_version == "1.0.0",
            AgentExecution.idempotency_key == request.idempotency_key,
        )
    )
    if existing is not None:
        if (
            existing.structured_input.get("website_id") != str(website_id)
            or existing.analysis_run_id is None
        ):
            raise ApplicationError(
                code="ANALYSIS_IDEMPOTENCY_CONFLICT",
                message="The idempotency key is associated with a different analysis scope.",
                status_code=status.HTTP_409_CONFLICT,
            )
        analysis_run = db.get(AnalysisRun, existing.analysis_run_id)
        if analysis_run is None:
            raise ApplicationError(
                code="ANALYSIS_RUN_NOT_FOUND",
                message="The idempotent workflow no longer has an analysis run.",
                status_code=status.HTTP_409_CONFLICT,
            )
        return AnalysisJourneyStartRead(
            analysis_run_id=analysis_run.id,
            workflow_execution_id=existing.execution_id,
            analysis_status=analysis_run.status.value,
            workflow_status=existing.status,
            reused=True,
        )

    profile = profiles_registry.get_profile(website.profile_id)
    if profile is None:
        profile = profiles_registry.get_profile("global_general")
    assert profile is not None
    analysis_run = AnalysisRun(
        website_id=website.id,
        profile_id=profile.profile_id,
        profile_version=profile.version,
    )
    db.add(analysis_run)
    db.flush()
    try:
        execution, created = create_workflow_execution(
            db,
            WorkflowExecutionCreate(
                workflow_id="full_website_analysis",
                project_id=project_id,
                analysis_run_id=analysis_run.id,
                website_id=website_id,
                repository_connection_id=request.repository_connection_id,
                page_analysis_execution_id=request.page_analysis_execution_id,
                idempotency_key=request.idempotency_key,
                max_concurrency=request.max_concurrency,
            ),
        )
    except WorkflowExecutionError as exception:
        db.rollback()
        raise _workflow_error(exception) from exception
    if not created:
        persisted_run = db.get(AnalysisRun, execution.analysis_run_id)
        assert persisted_run is not None
        return AnalysisJourneyStartRead(
            analysis_run_id=persisted_run.id,
            workflow_execution_id=execution.execution_id,
            analysis_status=persisted_run.status.value,
            workflow_status=execution.status,
            reused=True,
        )
    try:
        analysis_task_id, workflow_task_id = enqueue_analysis_journey(
            str(analysis_run.id),
            str(execution.execution_id),
            workflow_attempt=execution.attempt,
        )
    except Exception as exception:
        analysis_run.status = AnalysisStatus.FAILED
        analysis_run.error_code = "ANALYSIS_JOURNEY_QUEUE_UNAVAILABLE"
        analysis_run.error_message = "The analysis journey could not be queued."
        execution.status = "failed"
        execution.failure_details = {
            "code": "ANALYSIS_JOURNEY_QUEUE_UNAVAILABLE",
            "message": "The analysis journey could not be queued.",
            "transient": True,
        }
        db.commit()
        raise ApplicationError(
            code="ANALYSIS_JOURNEY_QUEUE_UNAVAILABLE",
            message="The analysis journey could not be queued.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exception
    analysis_run.celery_task_id = analysis_task_id
    record_dispatch(db, execution, workflow_task_id)
    db.refresh(analysis_run)
    db.refresh(execution)
    return AnalysisJourneyStartRead(
        analysis_run_id=analysis_run.id,
        workflow_execution_id=execution.execution_id,
        analysis_status=analysis_run.status.value,
        workflow_status=execution.status,
        reused=False,
    )


@router.get(
    "/workflow-executions/{execution_id}/progress",
    response_model=WorkflowProgressRead,
)
def workflow_progress(
    execution_id: uuid.UUID,
    db: DatabaseSession,
) -> WorkflowProgressRead:
    execution = db.scalar(select(AgentExecution).where(AgentExecution.execution_id == execution_id))
    if execution is None:
        raise ApplicationError(
            code="WORKFLOW_EXECUTION_NOT_FOUND",
            message="Workflow execution not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    workflow = WorkflowRegistry.get(execution.workflow_id)
    if workflow is None:
        raise ApplicationError(
            code="WORKFLOW_VERSION_UNAVAILABLE",
            message="The pinned workflow definition is unavailable.",
            status_code=status.HTTP_409_CONFLICT,
        )
    runs = list(
        db.scalars(
            select(AgentRun)
            .where(AgentRun.execution_id == execution.id)
            .order_by(
                AgentRun.agent_id,
                AgentRun.attempt.desc(),
                AgentRun.created_at.desc(),
            )
        )
    )
    latest: dict[str, AgentRun] = {}
    for run in runs:
        latest.setdefault(run.agent_id, run)
    repository_agent_enabled = bool(
        execution.structured_input.get("repository_connection_id")
        or execution.structured_input.get("execute_repository_agent")
    )
    active_order = [
        agent_id
        for agent_id in workflow.deterministic_order
        if agent_id != "repository_intelligence_agent" or repository_agent_enabled
    ]
    completed = [
        item for item in active_order if latest.get(item) and latest[item].status == "completed"
    ]
    partial = [
        item for item in active_order if latest.get(item) and latest[item].status == "partial"
    ]
    failed = [item for item in active_order if latest.get(item) and latest[item].status == "failed"]
    unavailable = [
        item for item in active_order if latest.get(item) and latest[item].status == "unavailable"
    ]
    pending = [
        item
        for item in active_order
        if item not in latest or latest[item].status in {"pending", "running"}
    ]
    score = (
        db.scalar(
            select(ScoreExecution)
            .where(ScoreExecution.analysis_run_id == execution.analysis_run_id)
            .order_by(ScoreExecution.created_at.desc(), ScoreExecution.id.desc())
        )
        if execution.analysis_run_id
        else None
    )
    coverage = EvidenceCoverageRead(
        status=(
            "available"
            if score and not score.unavailable_metrics
            else "partial"
            if score
            else "unavailable"
        ),
        numerator=score.evidence_coverage_numerator if score else 0,
        denominator=score.evidence_coverage_denominator if score else 5,
        percentage=score.evidence_coverage_percentage if score else None,
    )
    unavailable_tools = sorted(
        {
            str(activity.get("tool_id"))
            for run in latest.values()
            for activity in run.tool_activity_summary
            if activity.get("status") == "unavailable" and activity.get("tool_id")
        }
    )
    unavailable_providers = sorted(
        {
            str(metadata.get("provider"))
            for run in latest.values()
            for metadata in [run.provider_version_metadata]
            if metadata.get("provider") in {"disabled", "unavailable"}
        }
    )
    safe_errors = []
    for details in [
        execution.failure_details,
        *(run.failure_details for run in latest.values()),
    ]:
        if not details:
            continue
        sanitized = sanitize_persisted_value(details)
        safe_errors.append(
            {
                "code": str(sanitized.get("code") or sanitized.get("failure_code") or "failed"),
                "message": str(
                    sanitized.get("message")
                    or sanitized.get("failure_message")
                    or "An execution step failed."
                ),
            }
        )
    now = datetime.now(UTC)
    end = execution.completed_at or now
    start = execution.started_at
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    resumable_checkpoint = db.scalar(
        select(AgentCheckpoint.id).where(
            AgentCheckpoint.execution_id == execution.id,
            AgentCheckpoint.resumable.is_(True),
        )
    )
    retryable = execution.status in {"failed", "partial", "unavailable", "cancelled"}
    discovery_id = execution.structured_input.get("discovery_run_id")
    discovery = db.get(DiscoveryRun, uuid.UUID(str(discovery_id))) if discovery_id else None
    discovery_status = (
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
    if discovery_status is None:
        discovery_completeness = None
    elif discovery_status in _ACTIVE_STATUSES:
        discovery_completeness = None
    else:
        discovery_completeness = _TERMINAL_COMPLETENESS.get(discovery_status)
    recoverable_discovery_codes = {
        "DISCOVERY_DEADLINE_EXCEEDED",
        "DISCOVERY_PAGE_FETCH_FAILED",
        "DNS_RESOLUTION_FAILED",
        "RESPONSE_DECOMPRESSION_FAILED",
        "ROBOTS_FETCH_FAILED",
        "SITEMAP_FETCH_FAILED",
    }
    discovery_recoverable = bool(
        discovery
        and discovery_completeness in {"partial", "failed"}
        and discovery.failure_code in recoverable_discovery_codes
    )
    if discovery and discovery.failure_code:
        safe_errors.append(
            {
                "code": discovery.failure_code,
                "message": discovery.failure_message
                or "Website discovery retained partial evidence.",
            }
        )
    page_execution_id = execution.structured_input.get("page_analysis_execution_id")
    level_one_runs = (
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
    historical_page_ids = {item.website_page_id for item in level_one_runs}
    pages = (
        list(
            db.scalars(
                select(WebsitePage)
                .where(
                    WebsitePage.website_id
                    == uuid.UUID(str(execution.structured_input["website_id"])),
                    or_(
                        # Run-scoped membership (immutable, concurrency-safe).
                        WebsitePage.id.in_(
                            select(DiscoveryRunPage.website_page_id).where(
                                DiscoveryRunPage.discovery_run_id == discovery.id
                            )
                        ),
                        # Legacy fallback; this pointer only ever equals this run's
                        # own discovery id, so it never matches another run's pages.
                        WebsitePage.last_discovery_run_id == discovery.id,
                        WebsitePage.id.in_(historical_page_ids),
                    ),
                )
                .order_by(
                    WebsitePage.crawl_depth,
                    WebsitePage.normalized_url,
                    WebsitePage.id,
                )
            )
        )
        if discovery
        else []
    )
    run_by_page_id = {item.website_page_id: item for item in level_one_runs}

    def resource_for(page: WebsitePage):
        page_run = run_by_page_id.get(page.id)
        return classify_resource(
            page.normalized_url,
            final_url=page_run.final_url if page_run else page.final_url,
            content_type=page_run.content_type if page_run else None,
            failure_code=page_run.failure_reason_code if page_run else None,
            eligibility_status=page.eligibility_status,
            exclusion_reason=page.exclusion_reason,
            skip_reason=page.skip_reason,
            origin_relation=page.origin_relation,
        )

    classifications = {item.id: resource_for(item) for item in pages}
    eligible_pages = [
        item
        for item in pages
        if classifications[item.id].classification == ResourceClassification.ELIGIBLE_HTML_PAGE
    ]
    selected_ids = {
        uuid.UUID(str(item))
        for item in execution.structured_output.get("page_analysis_summary", {}).get(
            "selected_page_ids", []
        )
    } or {item.website_page_id for item in level_one_runs}
    if selected_ids:
        scheduled_pages = [item for item in eligible_pages if item.id in selected_ids]
    else:
        raw_limit = execution.structured_input.get("maximum_pages")
        page_limit = int(raw_limit) if raw_limit is not None else None
        scheduled_pages = select_scheduled_pages(
            eligible_pages,
            page_limit,
        )
    scheduled_ids = [item.id for item in scheduled_pages]
    scheduled_id_set = set(scheduled_ids)
    scheduled_level_one_runs = [
        item for item in level_one_runs if item.website_page_id in scheduled_id_set
    ]
    scheduled_count = len(scheduled_pages)
    eligible_count = len(eligible_pages)
    visited_count = sum(item.analysis_started_at is not None for item in scheduled_level_one_runs)
    successful_count = sum(
        item.status == "completed"
        and item.final_url is not None
        and item.http_status_code is not None
        for item in scheduled_level_one_runs
    )
    failed_count = sum(item.status == "failed" for item in scheduled_level_one_runs)
    incomplete_count = sum(
        item.status in {"pending", "running", "partial"}
        or (
            item.status == "completed" and (item.final_url is None or item.http_status_code is None)
        )
        for item in scheduled_level_one_runs
    )
    pages_by_id = {item.id: item for item in scheduled_pages}
    all_pages_by_id = {item.id: item for item in pages}
    failed_page_details = [
        {
            "url": (
                item.requested_url or pages_by_id[item.website_page_id].normalized_url
                if item.website_page_id in pages_by_id
                else "URL unavailable"
            ),
            "reason": item.failure_reason_text or "The page analysis failed without a safe reason.",
            "reason_code": item.failure_reason_code or "PAGE_ANALYSIS_FAILED",
        }
        for item in scheduled_level_one_runs
        if item.status == "failed"
    ]
    resource_inventory = [
        {
            "url": item.requested_url
            or (
                all_pages_by_id[item.website_page_id].normalized_url
                if item.website_page_id in all_pages_by_id
                else "URL unavailable"
            ),
            "final_url": item.final_url,
            "http_status": item.http_status_code,
            "response_content_type": item.content_type,
            "detected_content_type": None,
            "content_type_detection": "No independent content sniff was persisted.",
            "classification": classifications[item.website_page_id].classification.value,
            "classification_basis": classifications[item.website_page_id].evidence_basis,
            "failure_stage": "Page analysis response validation",
            "failure_reason": item.failure_reason_text,
            "browser_navigation": (
                "A browser could open an asset viewer, but this is not an HTML-page "
                "compatibility test; asset navigation was not attempted."
            ),
        }
        for item in level_one_runs
        if item.website_page_id in classifications
        and classifications[item.website_page_id].classification
        in {
            ResourceClassification.DOCUMENT_ASSET,
            ResourceClassification.MEDIA_STATIC_ASSET,
            ResourceClassification.UNSUPPORTED_RESOURCE,
        }
    ]
    completed_stage_ids = set(execution.structured_output.get("completed_stage_ids", []))
    page_stage_terminal = (
        "page_analysis" in completed_stage_ids or execution.status in TERMINAL_EXECUTION_STATUSES
    )
    skipped_count = max(0, scheduled_count - visited_count) if page_stage_terminal else 0
    not_scheduled_count = max(0, eligible_count - scheduled_count)
    coverage_percentage = (
        round(successful_count / eligible_count * 100, 1) if eligible_count else None
    )

    stale = real_execution_is_stale(execution)
    current_journey_stage = str(execution.structured_output.get("journey_stage") or "setup")
    journey_status = str(execution.structured_output.get("journey_status") or execution.status)
    raw_browser = dict(execution.structured_output.get("browser_compatibility", {}))
    raw_browser_status = str(raw_browser.get("status") or "not_started")
    if raw_browser_status == "pending":
        raw_browser_status = "not_started"
    if (
        current_journey_stage in {"browser_compatibility", "browser_engine_analysis"}
        and journey_status == "running"
        and raw_browser_status in {"not_started", "queued"}
    ):
        raw_browser_status = "running"
    browser_stage_stale = bool(
        stale and current_journey_stage in {"browser_compatibility", "browser_engine_analysis"}
    )
    if browser_stage_stale:
        raw_browser_status = "timed_out"
    observations = list(raw_browser.get("observations", []))
    unavailable_engine_set = {
        str(obs.get("engine")) for obs in observations if obs.get("state") == "unavailable"
    }
    matrix = list(raw_browser.get("matrix", []))
    raw_engine_rows = {
        str(item.get("engine")): item
        for item in raw_browser.get("engines", [])
        if isinstance(item, dict) and item.get("engine")
    }
    browser_eligible = scheduled_count
    browser_engines = []
    for engine in execution.structured_input.get("browser_engines", []):
        row = dict(raw_engine_rows.get(engine, {}))
        attempted_urls = {
            str(item.get("page_url"))
            for item in observations
            if item.get("engine") == engine and item.get("page_url")
        }
        tested_urls = {
            str(item.get("page_url"))
            for item in observations
            if item.get("engine") == engine
            and item.get("page_url")
            and item.get("state") not in {"not_tested", "unavailable"}
        }
        attempted_pages = int(
            row.get("attempted_pages") or row.get("tested_pages") or len(attempted_urls)
        )
        engine_eligible_count = browser_eligible
        states = [
            str(item.get("engines", {}).get(engine, "not_tested"))
            for item in matrix
            if isinstance(item, dict)
        ]
        unavailable_pages = int(row.get("unavailable_pages", states.count("unavailable")))
        failed_pages = int(row.get("failed_pages", states.count("incompatible")))
        timed_out_pages = (
            max(
                0,
                engine_eligible_count - len(tested_urls) - unavailable_pages - failed_pages,
            )
            if browser_stage_stale
            else 0
        )
        browser_engines.append(
            {
                "engine": engine,
                "eligible_pages": engine_eligible_count,
                "queued_pages": (
                    0
                    if browser_stage_stale
                    else min(
                        engine_eligible_count,
                        max(
                            0,
                            int(
                                row.get(
                                    "queued_pages",
                                    engine_eligible_count - attempted_pages,
                                )
                            ),
                        ),
                    )
                ),
                "attempted_pages": min(engine_eligible_count, attempted_pages),
                "tested_pages": min(engine_eligible_count, len(tested_urls)),
                "passed_pages": int(row.get("passed_pages", states.count("compatible"))),
                "partial_pages": int(
                    row.get(
                        "partial_pages",
                        states.count("partially_compatible"),
                    )
                ),
                "failed_pages": failed_pages,
                "inconclusive_pages": int(
                    row.get(
                        "inconclusive_pages",
                        states.count("inconclusive") + states.count("not_tested"),
                    )
                ),
                "unavailable_pages": unavailable_pages,
                "timed_out_pages": timed_out_pages,
                "availability_status": (
                    "unavailable"
                    if (
                        raw_browser_status in {"unavailable", "timed_out"}
                        or (engine in unavailable_engine_set and len(tested_urls) == 0)
                    )
                    else "available"
                ),
            }
        )
    browser_progress = {
        **raw_browser,
        "status": raw_browser_status,
        "eligible_page_count": browser_eligible,
        "engines": browser_engines,
    }

    repository_connected = bool(execution.structured_input.get("repository_connection_id"))
    agent_states = [
        {
            "agent_id": agent_id,
            "status": (
                "not_applicable"
                if agent_id == "repository_intelligence_agent" and not repository_connected
                else latest[agent_id].status
                if agent_id in latest
                else "running"
                if agent_id == "discovery_agent"
                and current_journey_stage == "website_discovery"
                and journey_status == "running"
                else discovery.status.value
                if discovery
                and hasattr(discovery.status, "value")
                and agent_id == "discovery_agent"
                else str(discovery.status)
                if discovery and agent_id == "discovery_agent"
                else "unavailable"
                if execution.status in {"failed", "cancelled", "unavailable"}
                else "queued"
            ),
        }
        for agent_id in active_order
    ]
    for state in agent_states:
        if state["status"] == "pending":
            state["status"] = "queued"
        if (
            state["agent_id"] == "repository_intelligence_agent"
            and not repository_connected
            and state["status"] == "unavailable"
        ):
            state["status"] = "not_applicable"

    stage_definitions = (
        ("setup", "URL validation and setup", 5),
        ("website_discovery", "Website discovery", 15),
        ("page_analysis", "Page analysis", 20),
        ("browser_compatibility", "Browser compatibility", 20),
        ("evidence_validation", "Evidence validation", 10),
        ("diagnostics_scoring", "Diagnostics and scoring", 15),
        ("remediation", "Remediation", 7),
        ("report_generation", "Report generation", 8),
    )
    failed_stage = (
        execution.structured_output.get("failed_stage_id")
        or execution.failure_details.get("failed_stage")
        if execution.status == "failed"
        else None
    )
    if execution.status == "failed" and not failed_stage:
        failed_stage = {
            "website_discovery": "website_discovery",
            "page_analysis": "page_analysis",
            "primary_page_analysis": "diagnostics_scoring",
            "browser_engine_analysis": "browser_compatibility",
            "browser_compatibility": "browser_compatibility",
            "multi_agent_analysis": "evidence_validation",
        }.get(
            str(execution.structured_output.get("journey_stage")),
            "setup",
        )
    if stale:
        failed_stage = {
            "website_discovery": "website_discovery",
            "page_analysis": "page_analysis",
            "primary_page_analysis": "diagnostics_scoring",
            "browser_engine_analysis": "browser_compatibility",
            "browser_compatibility": "browser_compatibility",
            "multi_agent_analysis": "evidence_validation",
        }.get(current_journey_stage, "setup")

    def agent_status(agent_id: str) -> str:
        return latest[agent_id].status if agent_id in latest else "queued"

    stage_statuses: dict[str, str] = {
        "setup": "completed",
        "website_discovery": (
            "failed"
            if failed_stage == "website_discovery"
            else "running"
            if current_journey_stage == "website_discovery" and journey_status == "running"
            else discovery.status.value
            if discovery and hasattr(discovery.status, "value")
            else str(discovery.status)
            if discovery
            else "queued"
        ),
        "page_analysis": (
            "failed"
            if failed_stage == "page_analysis"
            else "completed"
            if page_stage_terminal and scheduled_count > 0 and successful_count == scheduled_count
            else "partial"
            if page_stage_terminal and visited_count > 0
            else "running"
            if current_journey_stage in {"page_analysis", "primary_page_analysis"}
            else "queued"
        ),
        "browser_compatibility": (
            "failed"
            if raw_browser_status == "failed_to_start"
            else "unavailable"
            if raw_browser_status == "unavailable"
            else "running"
            if current_journey_stage in {"browser_compatibility", "browser_engine_analysis"}
            and journey_status == "running"
            and raw_browser_status in {"not_started", "queued", "running"}
            else raw_browser_status
        ),
        "evidence_validation": agent_status("evidence_validation_agent"),
        "diagnostics_scoring": (
            "running"
            if current_journey_stage == "primary_page_analysis"
            else "completed"
            if score
            and all(
                agent_status(item) == "completed"
                for item in (
                    "performance_agent",
                    "accessibility_agent",
                    "site_diagnostics_agent",
                )
            )
            else "partial"
            if all(
                agent_status(item) in TERMINAL_EXECUTION_STATUSES
                for item in (
                    "performance_agent",
                    "accessibility_agent",
                    "site_diagnostics_agent",
                )
            )
            else "running"
            if any(
                agent_status(item) == "running"
                for item in (
                    "performance_agent",
                    "accessibility_agent",
                    "site_diagnostics_agent",
                )
            )
            else "queued"
        ),
        "remediation": agent_status("remediation_agent"),
        "report_generation": agent_status("report_agent"),
    }
    if failed_stage in stage_statuses:
        stage_statuses[str(failed_stage)] = "failed"
    terminal_stage_states = {
        "completed",
        "partial",
        "unavailable",
        "not_applicable",
    }
    stage_rows = [
        {
            "stage_id": stage_id,
            "label": label,
            "weight": weight,
            "status": (
                "queued"
                if stage_statuses[stage_id] in {"pending", "not_started"}
                else stage_statuses[stage_id]
            ),
        }
        for stage_id, label, weight in stage_definitions
    ]
    progress = round(
        sum(
            row["weight"]
            if row["status"] in terminal_stage_states
            else row["weight"] * 0.5
            if row["status"] == "running"
            else 0
            for row in stage_rows
        ),
        2,
    )
    if execution.status in {"completed", "partial", "unavailable"}:
        progress = 100.0
    active_stage = next(
        (row["stage_id"] for row in stage_rows if row["status"] == "running"),
        None,
    )
    current_stage = (
        str(failed_stage)
        if failed_stage
        else active_stage
        or next(
            (row["stage_id"] for row in stage_rows if row["status"] not in terminal_stage_states),
            "workflow_complete",
        )
    )
    if not discovery_id:
        terminal_count = sum(
            latest[item].status in TERMINAL_EXECUTION_STATUSES
            for item in active_order
            if item in latest
        )
        progress = round(terminal_count / len(active_order) * 100, 2) if active_order else 100.0
        running_agent = next(
            (item for item in active_order if item in latest and latest[item].status == "running"),
            None,
        )
        current_stage = (
            running_agent
            or next((item for item in active_order if item in pending), None)
            or "workflow_complete"
        )
    last_progress_update = real_execution_last_update(execution)
    display_status = (
        "failed"
        if stale
        else str(
            execution.structured_output.get("journey_status") or execution.status
            if execution.status == "pending"
            else execution.status
        )
    )
    business_error = (
        "The analysis stopped reporting progress. Retry can continue from retained evidence."
        if stale
        else str(execution.failure_details.get("message") or "") or None
    )
    retryable = bool(
        execution.attempt < 3
        and (
            discovery_recoverable
            or stale
            or (
                display_status in {"failed", "cancelled"}
                and execution.failure_details.get("transient") is True
            )
            or (
                display_status == "partial"
                and failed_stage
                and execution.failure_details.get("transient") is True
            )
        )
    )
    report_exists = bool(
        db.scalar(
            select(ReportExecution.id)
            .where(ReportExecution.analysis_run_id == execution.analysis_run_id)
            .limit(1)
        )
    )
    report_generation_available = bool(
        report_exists or agent_status("report_agent") in {"completed", "partial", "unavailable"}
    )
    return WorkflowProgressRead(
        execution_id=execution.execution_id,
        analysis_run_id=execution.analysis_run_id,
        status=display_status,
        current_stage=current_stage,
        completed_agent_ids=completed,
        partial_agent_ids=partial,
        pending_agent_ids=pending,
        failed_agent_ids=failed,
        unavailable_agent_ids=unavailable,
        progress_percentage=progress,
        evidence_coverage=coverage,
        attempt=execution.attempt,
        retry_available=retryable,
        resume_available=retryable and (resumable_checkpoint is not None or discovery is not None),
        started_at=execution.started_at,
        completed_at=execution.completed_at,
        elapsed_seconds=max(0.0, round((end - start).total_seconds(), 3)),
        unavailable_tools=unavailable_tools,
        unavailable_providers=unavailable_providers,
        safe_error_summaries=safe_errors,
        submitted_website=execution.structured_input.get("submitted_url")
        or execution.structured_input.get("website_url"),
        page_coverage={
            "discovery_status": discovery_status,
            "discovery_completeness": discovery_completeness,
            "discovery_failure_code": discovery.failure_code if discovery else None,
            "discovery_failure_message": discovery.failure_message if discovery else None,
            "discovery_retry_available": discovery_recoverable and execution.attempt < 3,
            "discovered_pages": discovery.urls_discovered if discovery else 0,
            "normalized_pages": discovery.urls_unique if discovery else len(pages),
            "eligible_pages": eligible_count,
            "scheduled_pages": scheduled_count,
            "not_scheduled_pages": not_scheduled_count,
            "visited_pages": visited_count,
            "successfully_analysed_pages": successful_count,
            "failed_pages": failed_count,
            "failed_page_details": failed_page_details,
            "document_assets": sum(
                item["classification"] == ResourceClassification.DOCUMENT_ASSET.value
                for item in resource_inventory
            ),
            "media_static_assets": sum(
                item["classification"] == ResourceClassification.MEDIA_STATIC_ASSET.value
                for item in resource_inventory
            ),
            "resource_inventory": resource_inventory,
            "skipped_pages": skipped_count,
            "incomplete_pages": incomplete_count,
            "coverage_numerator": successful_count,
            "coverage_denominator": eligible_count,
            "coverage_percentage": coverage_percentage,
            "analysed_page_coverage_percentage": coverage_percentage,
            "full_site_coverage_percentage": (
                coverage_percentage if discovery_completeness == "complete" else None
            ),
            "full_site_coverage_confidence": (
                "established"
                if discovery_completeness == "complete"
                else "pending"
                if discovery_completeness is None
                else "not_established"
            ),
            "discovery_stage_status": (discovery_status if discovery_status else "not_started"),
            "discovery_completeness_message": _discovery_message(
                discovery_status if discovery_status else "not_started",
                discovery_completeness,
                discovery,
            ),
        },
        browser_engine_progress=browser_progress,
        agent_states=agent_states,
        stages=stage_rows,
        completed_stage_ids=[
            row["stage_id"] for row in stage_rows if row["status"] in terminal_stage_states
        ],
        active_stage_id=active_stage,
        pending_stage_ids=[row["stage_id"] for row in stage_rows if row["status"] == "queued"],
        failed_stage_id=str(failed_stage) if failed_stage else None,
        last_progress_update=last_progress_update,
        stale=stale,
        business_error_message=business_error,
        report_generation_available=report_generation_available,
    )


@router.post(
    "/analysis-runs/{run_id}/reports/generate",
    response_model=ReportExecutionRead,
    status_code=status.HTTP_201_CREATED,
)
def generate_analysis_report(
    run_id: uuid.UUID,
    request: ReportGenerateRequest,
    db: DatabaseSession,
) -> ReportExecution:
    try:
        report, _created = generate_report(
            db,
            run_id,
            idempotency_key=request.idempotency_key,
            workflow_execution_id=request.workflow_execution_id,
            report_type=request.report_type,
        )
    except ReportDeliveryError as exception:
        raise _report_error(exception) from exception
    return report


def _paginated_reports(
    db: Session,
    filters: list[object],
    *,
    report_status: str | None,
    report_type: str | None,
    limit: int,
    offset: int,
) -> PaginatedReports:
    if report_status is not None:
        filters.append(ReportExecution.status == report_status)
    if report_type is not None:
        filters.append(ReportExecution.report_type == report_type)
    total = db.scalar(select(func.count(ReportExecution.id)).where(*filters)) or 0
    reports = list(
        db.scalars(
            select(ReportExecution)
            .options(
                selectinload(ReportExecution.sections),
                selectinload(ReportExecution.artifacts),
            )
            .where(*filters)
            .order_by(ReportExecution.created_at.desc(), ReportExecution.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    return PaginatedReports(
        items=[ReportExecutionRead.model_validate(item) for item in reports],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/analysis-runs/{run_id}/reports",
    response_model=PaginatedReports,
)
def list_analysis_reports(
    run_id: uuid.UUID,
    db: DatabaseSession,
    report_status: Annotated[
        Literal["pending", "running", "completed", "partial", "failed", "unavailable"] | None,
        Query(alias="status"),
    ] = None,
    report_type: Annotated[
        str | None,
        Query(pattern=r"^[a-z][a-z0-9_]*$", max_length=100),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaginatedReports:
    if db.get(AnalysisRun, run_id) is None:
        raise ApplicationError(
            code="ANALYSIS_RUN_NOT_FOUND",
            message="Analysis run not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return _paginated_reports(
        db,
        [ReportExecution.analysis_run_id == run_id],
        report_status=report_status,
        report_type=report_type,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/websites/{website_id}/reports/history",
    response_model=PaginatedReports,
)
def website_report_history(
    website_id: uuid.UUID,
    db: DatabaseSession,
    report_status: Annotated[
        Literal["pending", "running", "completed", "partial", "failed", "unavailable"] | None,
        Query(alias="status"),
    ] = None,
    report_type: Annotated[
        str | None,
        Query(pattern=r"^[a-z][a-z0-9_]*$", max_length=100),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaginatedReports:
    if db.get(Website, website_id) is None:
        raise ApplicationError(
            code="WEBSITE_NOT_FOUND",
            message="Website not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return _paginated_reports(
        db,
        [ReportExecution.website_id == website_id],
        report_status=report_status,
        report_type=report_type,
        limit=limit,
        offset=offset,
    )


@router.get("/reports/{report_id}", response_model=ReportExecutionRead)
def report_detail(report_id: uuid.UUID, db: DatabaseSession) -> ReportExecution:
    try:
        return load_report(db, report_id)
    except ReportDeliveryError as exception:
        raise _report_error(exception) from exception


@router.get("/reports/{report_id}/status", response_model=ReportStatusRead)
def report_status(report_id: uuid.UUID, db: DatabaseSession) -> ReportStatusRead:
    try:
        report = load_report(db, report_id)
    except ReportDeliveryError as exception:
        raise _report_error(exception) from exception
    completed = sum(item.status not in {"unavailable", "excluded"} for item in report.sections)
    quality = None
    if report.snapshot:
        quality = report.snapshot.snapshot_payload.get("report_quality")
    return ReportStatusRead(
        report_id=report.report_id,
        status=report.status,
        report_quality=quality,
        completed_section_count=completed,
        total_section_count=len(report.sections),
        unavailable_sections=report.unavailable_sections,
        evidence_coverage=EvidenceCoverageRead(
            status=(
                "available"
                if not report.unavailable_sections
                else "partial"
                if completed
                else "unavailable"
            ),
            numerator=report.evidence_coverage_numerator,
            denominator=report.evidence_coverage_denominator,
            percentage=report.evidence_coverage_percentage,
        ),
        started_at=report.started_at,
        completed_at=report.completed_at,
        failure_details=report.failure_details,
        partial_completion_details=report.partial_completion_details,
    )


@router.get("/reports/{report_id}/artifacts", response_model=ReportArtifactList)
def report_artifacts(report_id: uuid.UUID, db: DatabaseSession) -> ReportArtifactList:
    try:
        report = load_report(db, report_id)
    except ReportDeliveryError as exception:
        raise _report_error(exception) from exception
    return ReportArtifactList(items=report.artifacts)


# Formats that are persisted as frozen artifacts at report-generation time.
# For these, a version-mismatched historical report can fall back to the stored
# bytes instead of being re-rendered under newer template code.
_STORED_ARTIFACT_FORMATS = {"pdf", "html", "json"}


@router.get("/reports/{report_id}/download/{artifact_format}")
def download_report(
    report_id: uuid.UUID,
    artifact_format: str,
    db: DatabaseSession,
) -> Response:
    normalized_format = artifact_format.casefold()
    if normalized_format in {
        "pdf",
        "presentation_pdf",
        "technical_appendix",
        "page_inventory",
    }:
        try:
            report = load_report(db, report_id)
        except ReportDeliveryError as exception:
            raise _report_error(exception) from exception
        if report.snapshot is None:
            raise ApplicationError(
                code="REPORT_SNAPSHOT_UNAVAILABLE",
                message="The immutable report snapshot is unavailable.",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        # Version-aware immutability guard. On-the-fly rendering reproduces the
        # originally generated bytes only while the code still implements the
        # template version the report was generated under. If the template
        # version has since moved on, re-rendering an old snapshot with new
        # layout code would silently change a historical artifact. When a frozen
        # stored artifact exists for the format, serve it instead so the
        # historical report never changes meaning or canonical values.
        if (
            report.template_version != TEMPLATE_VERSION
            and normalized_format in _STORED_ARTIFACT_FORMATS
        ):
            try:
                stored = load_artifact(db, report_id, normalized_format)
            except ReportDeliveryError:
                stored = None
            if stored is not None:
                return Response(
                    content=stored.content,
                    media_type=stored.media_type,
                    headers={
                        "Content-Disposition": f'attachment; filename="{stored.filename}"',
                        "X-Content-SHA256": stored.checksum_sha256,
                        "X-Content-Type-Options": "nosniff",
                        "Cache-Control": "private, max-age=31536000, immutable",
                    },
                )
        try:
            content, media_type, filename = render_additional_report_artifact(
                normalized_format,
                report.snapshot.snapshot_payload,
            )
        except ValueError as exception:
            raise ApplicationError(
                code="REPORT_FORMAT_UNSUPPORTED",
                message="The requested report format is unsupported.",
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            ) from exception
        checksum = hashlib.sha256(content).hexdigest()
        return Response(
            content=content,
            media_type=media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Content-SHA256": checksum,
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "private, max-age=31536000, immutable",
            },
        )
    try:
        artifact = load_artifact(db, report_id, normalized_format)
    except ReportDeliveryError as exception:
        raise _report_error(exception) from exception
    return Response(
        content=artifact.content,
        media_type=artifact.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{artifact.filename}"',
            "X-Content-SHA256": artifact.checksum_sha256,
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=31536000, immutable",
        },
    )
