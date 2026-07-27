import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_db
from app.errors.exceptions import ApplicationError
from app.models import AgentEvent, AgentExecution, AgentRun
from app.schemas.agent_platform import (
    AgentEventRead,
    AgentRunRead,
    ExecutionStatus,
    PaginatedAgentEvents,
    PaginatedAgentRuns,
    WorkflowExecutionCreate,
    WorkflowExecutionRead,
)
from app.services.workflow_execution import (
    WorkflowExecutionError,
    cancel_execution,
    create_workflow_execution,
    prepare_resume,
    record_dispatch,
    validate_agent_retry,
)
from app.services.workflow_queue import (
    enqueue_agent_retry,
    enqueue_workflow_execution,
    revoke_workflow_task,
)

router = APIRouter(tags=["Workflow executions"])
DatabaseSession = Annotated[Session, Depends(get_db)]


def _application_error(exception: WorkflowExecutionError) -> ApplicationError:
    return ApplicationError(
        code=exception.code,
        message=exception.message,
        status_code=exception.status_code,
    )


def _execution_or_raise(db: Session, execution_id: uuid.UUID) -> AgentExecution:
    execution = db.scalar(select(AgentExecution).where(AgentExecution.execution_id == execution_id))
    if execution is None:
        raise ApplicationError(
            code="WORKFLOW_EXECUTION_NOT_FOUND",
            message="Workflow execution not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return execution


def _run_or_raise(db: Session, run_id: uuid.UUID) -> AgentRun:
    run = db.scalar(select(AgentRun).where(AgentRun.agent_run_id == run_id))
    if run is None:
        raise ApplicationError(
            code="AGENT_RUN_NOT_FOUND",
            message="Agent run not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return run


@router.post(
    "/workflow-executions",
    response_model=WorkflowExecutionRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_workflow_execution(
    request: WorkflowExecutionCreate,
    db: DatabaseSession,
) -> AgentExecution:
    try:
        execution, created = create_workflow_execution(db, request)
    except WorkflowExecutionError as exception:
        raise _application_error(exception) from exception
    if not created:
        return execution
    try:
        task_id = enqueue_workflow_execution(
            str(execution.execution_id),
            attempt=execution.attempt,
        )
    except Exception as exception:
        execution.status = ExecutionStatus.FAILED.value
        execution.failure_details = {
            "code": "WORKFLOW_QUEUE_UNAVAILABLE",
            "message": "Workflow execution could not be queued.",
            "transient": True,
        }
        db.commit()
        raise ApplicationError(
            code="WORKFLOW_QUEUE_UNAVAILABLE",
            message="Workflow execution could not be queued.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exception
    record_dispatch(db, execution, task_id)
    db.refresh(execution)
    return execution


@router.get(
    "/workflow-executions/{execution_id}",
    response_model=WorkflowExecutionRead,
)
def get_workflow_execution(
    execution_id: uuid.UUID,
    db: DatabaseSession,
) -> AgentExecution:
    return _execution_or_raise(db, execution_id)


@router.get(
    "/workflow-executions/{execution_id}/runs",
    response_model=PaginatedAgentRuns,
)
def list_workflow_agent_runs(
    execution_id: uuid.UUID,
    db: DatabaseSession,
    agent_id: str | None = None,
    run_status: Annotated[ExecutionStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaginatedAgentRuns:
    execution = _execution_or_raise(db, execution_id)
    filters = [AgentRun.execution_id == execution.id]
    if agent_id is not None:
        filters.append(AgentRun.agent_id == agent_id)
    if run_status is not None:
        filters.append(AgentRun.status == run_status.value)
    total = db.scalar(select(func.count()).select_from(AgentRun).where(*filters)) or 0
    runs = list(
        db.scalars(
            select(AgentRun)
            .where(*filters)
            .order_by(AgentRun.created_at, AgentRun.agent_id, AgentRun.attempt)
            .offset(offset)
            .limit(limit)
        )
    )
    return PaginatedAgentRuns(
        items=[
            AgentRunRead.model_validate(run).model_copy(
                update={"execution_id": execution.execution_id}
            )
            for run in runs
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/workflow-executions/{execution_id}/events",
    response_model=PaginatedAgentEvents,
)
def list_workflow_events(
    execution_id: uuid.UUID,
    db: DatabaseSession,
    event_type: str | None = None,
    event_status: Annotated[ExecutionStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaginatedAgentEvents:
    execution = _execution_or_raise(db, execution_id)
    filters = [AgentEvent.execution_id == execution.id]
    if event_type is not None:
        filters.append(AgentEvent.event_type == event_type)
    if event_status is not None:
        filters.append(AgentEvent.status == event_status.value)
    total = db.scalar(select(func.count()).select_from(AgentEvent).where(*filters)) or 0
    events = list(
        db.scalars(
            select(AgentEvent)
            .options(selectinload(AgentEvent.agent_run))
            .where(*filters)
            .order_by(AgentEvent.sequence_number)
            .offset(offset)
            .limit(limit)
        )
    )
    items = [
        AgentEventRead(
            event_id=event.event_id,
            execution_id=execution.execution_id,
            agent_run_id=(event.agent_run.agent_run_id if event.agent_run is not None else None),
            agent_step_id=event.agent_step_id,
            event_type=event.event_type,
            sequence_number=event.sequence_number,
            status=ExecutionStatus(event.status),
            structured_payload=event.structured_payload,
            evidence_references=event.evidence_references,
            created_at=event.created_at,
        )
        for event in events
    ]
    return PaginatedAgentEvents(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/workflow-executions/{execution_id}/cancel",
    response_model=WorkflowExecutionRead,
)
def cancel_workflow_execution(
    execution_id: uuid.UUID,
    db: DatabaseSession,
) -> AgentExecution:
    execution = _execution_or_raise(db, execution_id)
    try:
        cancelled = cancel_execution(db, execution)
    except WorkflowExecutionError as exception:
        raise _application_error(exception) from exception
    task_id = cancelled.provider_version_metadata.get("celery_task_id")
    if isinstance(task_id, str) and task_id:
        try:
            revoke_workflow_task(task_id)
        except Exception:
            pass
    return cancelled


@router.post(
    "/workflow-executions/{execution_id}/resume",
    response_model=WorkflowExecutionRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def resume_workflow_execution(
    execution_id: uuid.UUID,
    db: DatabaseSession,
) -> AgentExecution:
    execution = _execution_or_raise(db, execution_id)
    try:
        resumed = prepare_resume(db, execution)
    except WorkflowExecutionError as exception:
        raise _application_error(exception) from exception
    try:
        task_id = enqueue_workflow_execution(
            str(resumed.execution_id),
            attempt=resumed.attempt,
        )
    except Exception as exception:
        resumed.status = ExecutionStatus.FAILED.value
        resumed.failure_details = {
            "code": "WORKFLOW_QUEUE_UNAVAILABLE",
            "message": "Workflow execution could not be resumed.",
            "transient": True,
        }
        db.commit()
        raise ApplicationError(
            code="WORKFLOW_QUEUE_UNAVAILABLE",
            message="Workflow execution could not be resumed.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exception
    record_dispatch(db, resumed, task_id)
    db.refresh(resumed)
    return resumed


@router.post(
    "/agent-runs/{run_id}/retry",
    response_model=WorkflowExecutionRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_agent_run(
    run_id: uuid.UUID,
    db: DatabaseSession,
) -> AgentExecution:
    run = _run_or_raise(db, run_id)
    try:
        execution = validate_agent_retry(db, run)
    except WorkflowExecutionError as exception:
        raise _application_error(exception) from exception
    next_attempt = run.attempt + 1
    try:
        task_id = enqueue_agent_retry(str(run.agent_run_id), next_attempt=next_attempt)
    except Exception as exception:
        execution.status = ExecutionStatus.FAILED.value
        execution.failure_details = {
            "code": "AGENT_RETRY_QUEUE_UNAVAILABLE",
            "message": "Agent retry could not be queued.",
            "transient": True,
        }
        db.commit()
        raise ApplicationError(
            code="AGENT_RETRY_QUEUE_UNAVAILABLE",
            message="Agent retry could not be queued.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exception
    record_dispatch(db, execution, task_id)
    db.refresh(execution)
    return execution
