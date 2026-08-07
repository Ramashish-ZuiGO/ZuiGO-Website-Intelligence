import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_db
from app.errors.exceptions import ApplicationError
from app.models import (
    AgentExecution,
    AnalysisComparison,
    AnalysisRun,
    AnalysisStatus,
    DiscoveryRun,
    DiscoveryStatus,
    Website,
)
from app.schemas.agent_platform import WorkflowExecutionCreate
from app.schemas.analysis_comparison import (
    AnalysisComparisonRead,
    ComparisonGenerateRequest,
    ComparisonHistoryRead,
    ReanalysisSettingsRead,
    ReanalysisStartRead,
    ReanalysisStartRequest,
)
from app.services import profiles_registry
from app.services.analysis_comparison import (
    AnalysisComparisonError,
    comparison_artifact,
    generate_comparison,
    latest_comparison,
)
from app.services.analysis_queue import enqueue_real_analysis_journey
from app.services.workflow_execution import (
    WorkflowExecutionError,
    create_workflow_execution,
    record_dispatch,
)

router = APIRouter(tags=["Analysis comparison"])
DatabaseSession = Annotated[Session, Depends(get_db)]
ExportFormat = Literal["html", "pdf", "json"]
DEFAULT_ENGINES = ["chromium", "firefox", "webkit"]


def _application_error(exception: AnalysisComparisonError) -> ApplicationError:
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


def _completed_baseline(db: Session, run_id: uuid.UUID) -> tuple[AnalysisRun, Website]:
    run = db.get(AnalysisRun, run_id)
    if run is None:
        raise ApplicationError(
            code="ANALYSIS_RUN_NOT_FOUND",
            message="Analysis run not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    if run.status != AnalysisStatus.COMPLETED:
        raise ApplicationError(
            code="BASELINE_ANALYSIS_INCOMPLETE",
            message="Only a completed analysis can be used as a reanalysis baseline.",
            status_code=status.HTTP_409_CONFLICT,
        )
    website = db.get(Website, run.website_id)
    if website is None:
        raise ApplicationError(
            code="WEBSITE_NOT_FOUND",
            message="The baseline website was not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return run, website


def _baseline_execution(db: Session, run_id: uuid.UUID) -> AgentExecution | None:
    return db.scalar(
        select(AgentExecution)
        .where(
            AgentExecution.analysis_run_id == run_id,
            AgentExecution.workflow_id == "full_website_analysis",
        )
        .order_by(AgentExecution.created_at.desc(), AgentExecution.id.desc())
    )


def _start_read(
    execution: AgentExecution,
    run: AnalysisRun,
    baseline_id: uuid.UUID,
    *,
    reused: bool,
) -> ReanalysisStartRead:
    inputs = execution.structured_input
    return ReanalysisStartRead(
        baseline_analysis_run_id=baseline_id,
        analysis_run_id=run.id,
        discovery_run_id=uuid.UUID(str(inputs["discovery_run_id"])),
        page_analysis_execution_id=uuid.UUID(str(inputs["page_analysis_execution_id"])),
        workflow_execution_id=execution.execution_id,
        analysis_status=run.status.value,
        workflow_status=str(execution.structured_output.get("journey_status") or execution.status),
        reused=reused,
    )


@router.get(
    "/analysis-runs/{baseline_run_id}/reanalysis-settings",
    response_model=ReanalysisSettingsRead,
)
def reanalysis_settings(
    baseline_run_id: uuid.UUID,
    db: DatabaseSession,
) -> ReanalysisSettingsRead:
    baseline, website = _completed_baseline(db, baseline_run_id)
    execution = _baseline_execution(db, baseline.id)
    inputs = execution.structured_input if execution else {}
    engines = [
        engine
        for engine in inputs.get("browser_engines", DEFAULT_ENGINES)
        if engine in DEFAULT_ENGINES
    ]
    return ReanalysisSettingsRead(
        baseline_analysis_run_id=baseline.id,
        website_id=website.id,
        website_url=website.url,
        baseline_created_at=baseline.completed_at or baseline.created_at,
        maximum_pages=inputs.get("maximum_pages"),
        browser_engines=engines or DEFAULT_ENGINES,
        include_mobile=bool(inputs.get("include_mobile", True)),
        max_concurrency=max(1, min(8, int(inputs.get("max_concurrency") or 3))),
    )


@router.post(
    "/analysis-runs/{baseline_run_id}/reanalyse",
    response_model=ReanalysisStartRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_reanalysis(
    baseline_run_id: uuid.UUID,
    request: ReanalysisStartRequest,
    db: DatabaseSession,
) -> ReanalysisStartRead:
    baseline, website = _completed_baseline(db, baseline_run_id)
    existing = db.scalar(
        select(AgentExecution)
        .where(
            AgentExecution.project_id == website.project_id,
            AgentExecution.workflow_id == "full_website_analysis",
            AgentExecution.workflow_version == "1.0.0",
            AgentExecution.idempotency_key == request.idempotency_key,
        )
        .order_by(AgentExecution.created_at.desc(), AgentExecution.id.desc())
    )
    if existing is not None:
        inputs = existing.structured_input
        if (
            inputs.get("baseline_analysis_run_id") != str(baseline.id)
            or existing.analysis_run_id is None
            or inputs.get("maximum_pages") != request.maximum_pages
            or list(inputs.get("browser_engines") or []) != request.browser_engines
            or bool(inputs.get("include_mobile")) != request.include_mobile
            or int(inputs.get("max_concurrency") or 0) != request.max_concurrency
        ):
            raise ApplicationError(
                code="REANALYSIS_IDEMPOTENCY_CONFLICT",
                message="The idempotency key belongs to a different reanalysis request.",
                status_code=status.HTTP_409_CONFLICT,
            )
        retained = db.get(AnalysisRun, existing.analysis_run_id)
        if retained is None:
            raise ApplicationError(
                code="REANALYSIS_RUN_NOT_FOUND",
                message="The retained reanalysis run is unavailable.",
                status_code=status.HTTP_409_CONFLICT,
            )
        return _start_read(existing, retained, baseline.id, reused=True)

    page_execution_id = uuid.uuid4()
    discovery = DiscoveryRun(
        website_id=website.id,
        current_stage="queued",
        configuration={
            "maximum_pages": request.maximum_pages,
            "max_html_pages": request.maximum_pages,
            "max_lighthouse_pages": 0,
            "browser_engines": list(request.browser_engines),
            "include_mobile": request.include_mobile,
            "submitted_url": website.url,
            "normalized_url": website.url,
            "page_analysis_execution_id": str(page_execution_id),
            "baseline_analysis_run_id": str(baseline.id),
        },
    )
    profile = profiles_registry.get_profile(website.profile_id)
    if profile is None:
        profile = profiles_registry.get_profile("global_general")
    assert profile is not None
    current = AnalysisRun(
        website_id=website.id,
        baseline_analysis_run_id=baseline.id,
        profile_id=profile.profile_id,
        profile_version=profile.version,
    )
    db.add_all([discovery, current])
    db.flush()
    try:
        execution, created = create_workflow_execution(
            db,
            WorkflowExecutionCreate(
                workflow_id="full_website_analysis",
                project_id=website.project_id,
                analysis_run_id=current.id,
                baseline_analysis_run_id=baseline.id,
                website_id=website.id,
                page_analysis_execution_id=page_execution_id,
                discovery_run_id=discovery.id,
                submitted_url=website.url,
                normalized_url=website.url,
                maximum_pages=request.maximum_pages,
                browser_engines=request.browser_engines,
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
        retained = db.get(AnalysisRun, execution.analysis_run_id)
        assert retained is not None
        return _start_read(execution, retained, baseline.id, reused=True)
    try:
        task_id = enqueue_real_analysis_journey(
            str(current.id),
            str(discovery.id),
            str(page_execution_id),
            str(execution.execution_id),
            workflow_attempt=execution.attempt,
        )
    except Exception as exception:
        current.status = AnalysisStatus.FAILED
        current.error_code = "REANALYSIS_QUEUE_UNAVAILABLE"
        current.error_message = "The reanalysis could not be queued."
        discovery.status = DiscoveryStatus.FAILED
        discovery.current_stage = "failed"
        discovery.progress_percent = 100
        discovery.failure_code = "REANALYSIS_QUEUE_UNAVAILABLE"
        discovery.failure_message = "The reanalysis could not be queued."
        execution.status = "failed"
        execution.failure_details = {
            "code": "REANALYSIS_QUEUE_UNAVAILABLE",
            "message": "The reanalysis could not be queued.",
            "transient": True,
        }
        db.commit()
        raise ApplicationError(
            code="REANALYSIS_QUEUE_UNAVAILABLE",
            message="The reanalysis could not be queued.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exception
    current.celery_task_id = task_id
    discovery.celery_task_id = task_id
    record_dispatch(db, execution, task_id)
    db.refresh(current)
    db.refresh(execution)
    return _start_read(execution, current, baseline.id, reused=False)


@router.post(
    "/analysis-runs/{current_run_id}/comparisons/{baseline_run_id}/generate",
    response_model=AnalysisComparisonRead,
    status_code=status.HTTP_201_CREATED,
)
def generate_analysis_comparison(
    current_run_id: uuid.UUID,
    baseline_run_id: uuid.UUID,
    request: ComparisonGenerateRequest,
    db: DatabaseSession,
    response: Response,
) -> AnalysisComparison:
    try:
        comparison, created = generate_comparison(
            db,
            current_run_id,
            baseline_run_id,
            idempotency_key=request.idempotency_key,
        )
    except AnalysisComparisonError as exception:
        raise _application_error(exception) from exception
    if not created:
        response.status_code = status.HTTP_200_OK
    return comparison


@router.get(
    "/analysis-runs/{current_run_id}/comparisons/{baseline_run_id}",
    response_model=AnalysisComparisonRead,
)
def get_analysis_comparison(
    current_run_id: uuid.UUID,
    baseline_run_id: uuid.UUID,
    db: DatabaseSession,
) -> AnalysisComparison:
    try:
        return latest_comparison(db, current_run_id, baseline_run_id)
    except AnalysisComparisonError as exception:
        raise _application_error(exception) from exception


@router.get(
    "/websites/{website_id}/analysis-comparisons/history",
    response_model=ComparisonHistoryRead,
)
def comparison_history(
    website_id: uuid.UUID,
    db: DatabaseSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ComparisonHistoryRead:
    if db.get(Website, website_id) is None:
        raise ApplicationError(
            code="WEBSITE_NOT_FOUND",
            message="Website not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    total = int(
        db.scalar(
            select(func.count(AnalysisComparison.id)).where(
                AnalysisComparison.website_id == website_id
            )
        )
        or 0
    )
    items = list(
        db.scalars(
            select(AnalysisComparison)
            .options(selectinload(AnalysisComparison.artifacts))
            .where(AnalysisComparison.website_id == website_id)
            .order_by(AnalysisComparison.created_at.desc(), AnalysisComparison.id.desc())
            .offset(offset)
            .limit(limit)
        )
    )
    return ComparisonHistoryRead(items=items, total=total, limit=limit, offset=offset)


@router.get("/analysis-comparisons/{comparison_id}/download/{artifact_format}")
def download_comparison(
    comparison_id: uuid.UUID,
    artifact_format: ExportFormat,
    db: DatabaseSession,
) -> Response:
    try:
        artifact = comparison_artifact(db, comparison_id, artifact_format)
    except AnalysisComparisonError as exception:
        raise _application_error(exception) from exception
    return Response(
        content=artifact.content,
        media_type=artifact.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{artifact.filename}"',
            "X-Content-Type-Options": "nosniff",
            "X-Content-SHA256": artifact.checksum_sha256,
        },
    )
