import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_db
from app.errors.exceptions import ApplicationError
from app.models import (
    AgentCheckpoint,
    AgentExecution,
    AgentRun,
    AnalysisRun,
    AnalysisStatus,
    ReportExecution,
    ScoreExecution,
    Website,
)
from app.schemas.agent_platform import WorkflowExecutionCreate
from app.schemas.report_delivery import (
    AnalysisJourneyStartRead,
    AnalysisJourneyStartRequest,
    EvidenceCoverageRead,
    PaginatedReports,
    ReportArtifactList,
    ReportExecutionRead,
    ReportGenerateRequest,
    ReportStatusRead,
    WorkflowProgressRead,
)
from app.services import profiles_registry
from app.services.agent_platform_registry import WorkflowRegistry
from app.services.analysis_queue import enqueue_analysis_journey
from app.services.report_delivery import (
    ReportDeliveryError,
    generate_report,
    load_artifact,
    load_report,
)
from app.services.tool_execution import sanitize_persisted_value
from app.services.workflow_execution import (
    TERMINAL_EXECUTION_STATUSES,
    WorkflowExecutionError,
    create_workflow_execution,
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
    active_order = [
        agent_id
        for agent_id in workflow.deterministic_order
        if not (
            agent_id == "repository_intelligence_agent"
            and not execution.structured_input.get("repository_connection_id")
        )
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
    terminal_count = sum(
        latest[item].status in TERMINAL_EXECUTION_STATUSES
        for item in active_order
        if item in latest
    )
    progress = round(terminal_count / len(active_order) * 100, 2) if active_order else 100.0
    running = next(
        (item for item in active_order if item in latest and latest[item].status == "running"),
        None,
    )
    current_stage = (
        running
        or next((item for item in active_order if item in pending), None)
        or "workflow_complete"
    )
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
    return WorkflowProgressRead(
        execution_id=execution.execution_id,
        analysis_run_id=execution.analysis_run_id,
        status=execution.status,
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
        resume_available=retryable and resumable_checkpoint is not None,
        started_at=execution.started_at,
        completed_at=execution.completed_at,
        elapsed_seconds=max(0.0, round((end - start).total_seconds(), 3)),
        unavailable_tools=unavailable_tools,
        unavailable_providers=unavailable_providers,
        safe_error_summaries=safe_errors,
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
    return ReportStatusRead(
        report_id=report.report_id,
        status=report.status,
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


@router.get("/reports/{report_id}/download/{artifact_format}")
def download_report(
    report_id: uuid.UUID,
    artifact_format: str,
    db: DatabaseSession,
) -> Response:
    try:
        artifact = load_artifact(db, report_id, artifact_format.casefold())
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
