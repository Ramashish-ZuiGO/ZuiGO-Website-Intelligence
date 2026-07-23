import math
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.errors.exceptions import ApplicationError
from app.models import (
    ActionGenerationExecution,
    ActionGroup,
    ActionItem,
    ActionStatusHistory,
    PageAnalysisRun,
    Website,
    validate_action_transition,
)
from app.schemas.action_plan import (
    ActionGenerationExecutionRead,
    ActionGenerationStartResponse,
    ActionGroupDetailRead,
    ActionGroupRead,
    ActionItemDetailRead,
    ActionItemRead,
    ActionPlanSummary,
    ActionStatusHistoryRead,
    BulkStatusUpdateRequest,
    BulkStatusUpdateResult,
    PaginatedResponse,
    StatusUpdateRequest,
)
from app.services.action_generation import generate_actions

router = APIRouter(prefix="/websites/{website_id}/action-plan", tags=["action-plan"])
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


def get_latest_execution(db: Session, website_id: uuid.UUID) -> ActionGenerationExecution | None:
    return db.scalar(
        select(ActionGenerationExecution)
        .where(ActionGenerationExecution.website_id == website_id)
        .order_by(ActionGenerationExecution.created_at.desc())
        .limit(1)
    )


@router.post(
    "/generate",
    response_model=ActionGenerationStartResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_action_generation(
    website_id: uuid.UUID,
    page_analysis_execution_id: uuid.UUID,
    db: DatabaseSession,
) -> ActionGenerationStartResponse:
    website_or_raise(db, website_id)

    exec_exists = db.scalar(
        select(PageAnalysisRun)
        .where(PageAnalysisRun.page_analysis_execution_id == page_analysis_execution_id)
        .limit(1)
    )
    if exec_exists is None:
        raise ApplicationError(
            code="PAGE_ANALYSIS_EXECUTION_NOT_FOUND",
            message="No page analysis runs found for the given execution ID.",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    generation_execution_id = uuid.uuid4()

    try:
        result = generate_actions(
            db=db,
            website_id=website_id,
            page_analysis_execution_id=page_analysis_execution_id,
            generation_execution_id=generation_execution_id,
        )
    except Exception as exception:
        raise ApplicationError(
            code="ACTION_GENERATION_FAILED",
            message=f"Action generation failed: {exception}",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        ) from exception

    return ActionGenerationStartResponse(
        status=result.status,
        generation_execution_id=result.id,
        page_analysis_execution_id=page_analysis_execution_id,
    )


@router.get(
    "/generation-executions/{execution_id}",
    response_model=ActionGenerationExecutionRead,
)
def get_generation_execution_status(
    website_id: uuid.UUID,
    execution_id: uuid.UUID,
    db: DatabaseSession,
) -> ActionGenerationExecutionRead:
    website_or_raise(db, website_id)
    exec_row = db.get(ActionGenerationExecution, execution_id)
    if exec_row is None or exec_row.website_id != website_id:
        raise ApplicationError(
            code="EXECUTION_NOT_FOUND",
            message="Action generation execution not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return ActionGenerationExecutionRead.model_validate(exec_row)


@router.get("/summary", response_model=ActionPlanSummary)
def get_action_plan_summary(
    website_id: uuid.UUID,
    db: DatabaseSession,
    generation_execution_id: Annotated[uuid.UUID | None, Query()] = None,
) -> ActionPlanSummary:
    website_or_raise(db, website_id)

    if generation_execution_id:
        exec_row = db.get(ActionGenerationExecution, generation_execution_id)
        if exec_row is None or exec_row.website_id != website_id:
            raise ApplicationError(
                code="EXECUTION_NOT_FOUND",
                message="Action generation execution not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        latest_execution = exec_row
    else:
        latest_execution = get_latest_execution(db, website_id)

    if latest_execution is None:
        return ActionPlanSummary(
            website_id=website_id,
            generation_execution_id=None,
            total_actions=0,
            total_open=0,
            total_acknowledged=0,
            total_in_progress=0,
            total_resolved=0,
            total_ignored=0,
            total_reopened=0,
            critical_actions=0,
            high_priority_actions=0,
            pages_requiring_correction=0,
            grouped_issues=0,
            average_priority=None,
            generation_status=None,
            generation_coverage=None,
        )

    gen_exec_id = latest_execution.id
    filters = [ActionItem.generation_execution_id == gen_exec_id]

    total_actions = db.scalar(select(func.count()).select_from(ActionItem).where(*filters)) or 0
    total_open = (
        db.scalar(
            select(func.count())
            .select_from(ActionItem)
            .where(*filters, ActionItem.status == "open")
        )
        or 0
    )
    total_acknowledged = (
        db.scalar(
            select(func.count())
            .select_from(ActionItem)
            .where(*filters, ActionItem.status == "acknowledged")
        )
        or 0
    )
    total_in_progress = (
        db.scalar(
            select(func.count())
            .select_from(ActionItem)
            .where(*filters, ActionItem.status == "in_progress")
        )
        or 0
    )
    total_resolved = (
        db.scalar(
            select(func.count())
            .select_from(ActionItem)
            .where(*filters, ActionItem.status == "resolved")
        )
        or 0
    )
    total_ignored = (
        db.scalar(
            select(func.count())
            .select_from(ActionItem)
            .where(*filters, ActionItem.status == "ignored")
        )
        or 0
    )
    total_reopened = (
        db.scalar(
            select(func.count())
            .select_from(ActionItem)
            .where(*filters, ActionItem.status == "reopened")
        )
        or 0
    )
    critical_actions = (
        db.scalar(
            select(func.count())
            .select_from(ActionItem)
            .where(*filters, ActionItem.severity == "critical")
        )
        or 0
    )
    high_priority_actions = (
        db.scalar(
            select(func.count())
            .select_from(ActionItem)
            .where(*filters, ActionItem.priority_score >= 70)
        )
        or 0
    )
    pages_requiring_correction = (
        db.scalar(
            select(func.count(func.distinct(ActionItem.website_page_id)))
            .select_from(ActionItem)
            .where(*filters)
        )
        or 0
    )
    grouped_issues = (
        db.scalar(
            select(func.count())
            .select_from(ActionGroup)
            .where(ActionGroup.generation_execution_id == gen_exec_id)
        )
        or 0
    )
    avg_row = db.scalar(
        select(func.avg(ActionItem.priority_score)).select_from(ActionItem).where(*filters)
    )
    average_priority = round(float(avg_row), 1) if avg_row is not None else None

    generation_coverage = None
    if latest_execution.total_findings_processed > 0:
        generation_coverage = round(
            latest_execution.total_actions_generated
            / latest_execution.total_findings_processed
            * 100,
            1,
        )

    return ActionPlanSummary(
        website_id=website_id,
        generation_execution_id=gen_exec_id,
        total_actions=total_actions,
        total_open=total_open,
        total_acknowledged=total_acknowledged,
        total_in_progress=total_in_progress,
        total_resolved=total_resolved,
        total_ignored=total_ignored,
        total_reopened=total_reopened,
        critical_actions=critical_actions,
        high_priority_actions=high_priority_actions,
        pages_requiring_correction=pages_requiring_correction,
        grouped_issues=grouped_issues,
        average_priority=average_priority,
        generation_status=latest_execution.status,
        generation_coverage=generation_coverage,
    )


@router.get("/groups", response_model=PaginatedResponse)
def list_action_groups(
    website_id: uuid.UUID,
    db: DatabaseSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    status_filter: str | None = Query(default=None, max_length=30, alias="status"),  # noqa: B008
    severity: str | None = Query(default=None, max_length=30),  # noqa: B008
    category: str | None = Query(default=None, max_length=100),  # noqa: B008
    responsible_area: str | None = Query(default=None, max_length=100),  # noqa: B008
    responsible_role: str | None = Query(default=None, max_length=100),  # noqa: B008
    priority_min: Annotated[int | None, Query(ge=0, le=100)] = None,
    priority_max: Annotated[int | None, Query(ge=0, le=100)] = None,
    generation_execution_id: uuid.UUID | None = Query(default=None),  # noqa: B008
    sort_by: str = Query(default="priority_score", max_length=30),  # noqa: B008
    sort_order: str = Query(default="desc", max_length=4),  # noqa: B008
) -> PaginatedResponse:
    website_or_raise(db, website_id)

    if generation_execution_id:
        gen_exec = db.get(ActionGenerationExecution, generation_execution_id)
        if gen_exec is None or gen_exec.website_id != website_id:
            raise ApplicationError(
                code="EXECUTION_NOT_FOUND",
                message="Action generation execution not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        gen_exec_id = generation_execution_id
    else:
        latest = get_latest_execution(db, website_id)
        if latest is None:
            return PaginatedResponse(
                items=[],
                page=page,
                page_size=page_size,
                total=0,
                total_pages=0,
            )
        gen_exec_id = latest.id

    filters = [
        ActionGroup.generation_execution_id == gen_exec_id,
        ActionGroup.website_id == website_id,
    ]
    if status_filter:
        filters.append(ActionGroup.status == status_filter)
    if severity:
        filters.append(ActionGroup.severity == severity)
    if category:
        filters.append(ActionGroup.category == category)
    if responsible_area:
        filters.append(ActionGroup.responsible_area == responsible_area)
    if responsible_role:
        filters.append(ActionGroup.responsible_role == responsible_role)
    if priority_min is not None:
        filters.append(ActionGroup.priority_score >= priority_min)
    if priority_max is not None:
        filters.append(ActionGroup.priority_score <= priority_max)

    total = db.scalar(select(func.count()).select_from(ActionGroup).where(*filters)) or 0

    order_col = getattr(ActionGroup, sort_by, ActionGroup.priority_score)
    order_expr = order_col.desc() if sort_order == "desc" else order_col.asc()

    rows = list(
        db.scalars(
            select(ActionGroup)
            .where(*filters)
            .order_by(order_expr, ActionGroup.issue_title.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )

    items = [ActionGroupRead.model_validate(g) for g in rows]

    return PaginatedResponse(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        total_pages=math.ceil(total / page_size) if total else 0,
    )


@router.get("/groups/{group_id}", response_model=ActionGroupDetailRead)
def get_action_group_detail(
    website_id: uuid.UUID,
    group_id: uuid.UUID,
    db: DatabaseSession,
) -> ActionGroupDetailRead:
    website_or_raise(db, website_id)

    group = db.get(ActionGroup, group_id)
    if group is None or group.website_id != website_id:
        raise ApplicationError(
            code="GROUP_NOT_FOUND",
            message="Action group not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    actions = list(
        db.scalars(
            select(ActionItem)
            .where(ActionItem.action_group_id == group_id)
            .order_by(ActionItem.final_url.asc())
        )
    )

    result = ActionGroupDetailRead.model_validate(group)
    result.actions = [ActionItemRead.model_validate(a) for a in actions]
    return result


@router.get("/actions", response_model=PaginatedResponse)
def list_action_items(
    website_id: uuid.UUID,
    db: DatabaseSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    status_filter: str | None = Query(default=None, max_length=30, alias="status"),  # noqa: B008
    severity: str | None = Query(default=None, max_length=30),  # noqa: B008
    category: str | None = Query(default=None, max_length=100),  # noqa: B008
    responsible_area: str | None = Query(default=None, max_length=100),  # noqa: B008
    confidence: str | None = Query(default=None, max_length=30),  # noqa: B008
    page_url: str | None = Query(default=None, max_length=500),  # noqa: B008
    priority_min: Annotated[int | None, Query(ge=0, le=100)] = None,
    priority_max: Annotated[int | None, Query(ge=0, le=100)] = None,
    generation_execution_id: uuid.UUID | None = Query(default=None),  # noqa: B008
    group_id: uuid.UUID | None = Query(default=None),  # noqa: B008
    sort_by: str = Query(default="priority_score", max_length=30),  # noqa: B008
    sort_order: str = Query(default="desc", max_length=4),  # noqa: B008
) -> PaginatedResponse:
    website_or_raise(db, website_id)

    if generation_execution_id:
        gen_exec = db.get(ActionGenerationExecution, generation_execution_id)
        if gen_exec is None or gen_exec.website_id != website_id:
            raise ApplicationError(
                code="EXECUTION_NOT_FOUND",
                message="Action generation execution not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        gen_exec_id = generation_execution_id
    else:
        latest = get_latest_execution(db, website_id)
        if latest is None:
            return PaginatedResponse(
                items=[],
                page=page,
                page_size=page_size,
                total=0,
                total_pages=0,
            )
        gen_exec_id = latest.id

    filters = [
        ActionItem.generation_execution_id == gen_exec_id,
        ActionItem.website_id == website_id,
    ]
    if status_filter:
        filters.append(ActionItem.status == status_filter)
    if severity:
        filters.append(ActionItem.severity == severity)
    if category:
        filters.append(ActionItem.issue_category == category)
    if responsible_area:
        filters.append(ActionItem.responsible_area == responsible_area)
    if confidence:
        filters.append(ActionItem.confidence == confidence)
    if page_url:
        filters.append(ActionItem.final_url.ilike(f"%{page_url}%"))
    if priority_min is not None:
        filters.append(ActionItem.priority_score >= priority_min)
    if priority_max is not None:
        filters.append(ActionItem.priority_score <= priority_max)
    if group_id:
        filters.append(ActionItem.action_group_id == group_id)

    total = db.scalar(select(func.count()).select_from(ActionItem).where(*filters)) or 0

    order_col = getattr(ActionItem, sort_by, ActionItem.priority_score)
    order_expr = order_col.desc() if sort_order == "desc" else order_col.asc()

    rows = list(
        db.scalars(
            select(ActionItem)
            .where(*filters)
            .order_by(order_expr, ActionItem.final_url.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )

    items = [ActionItemRead.model_validate(a) for a in rows]

    return PaginatedResponse(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        total_pages=math.ceil(total / page_size) if total else 0,
    )


@router.get("/actions/{action_id}", response_model=ActionItemDetailRead)
def get_action_detail(
    website_id: uuid.UUID,
    action_id: uuid.UUID,
    db: DatabaseSession,
) -> ActionItemDetailRead:
    website_or_raise(db, website_id)

    action = db.get(ActionItem, action_id)
    if action is None or action.website_id != website_id:
        raise ApplicationError(
            code="ACTION_NOT_FOUND",
            message="Action item not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    history = list(
        db.scalars(
            select(ActionStatusHistory)
            .where(ActionStatusHistory.action_item_id == action_id)
            .order_by(ActionStatusHistory.changed_at.asc())
        )
    )

    result = ActionItemDetailRead.model_validate(action)
    result.status_history = [ActionStatusHistoryRead.model_validate(h) for h in history]
    return result


@router.patch("/actions/{action_id}/status", response_model=ActionItemRead)
def update_action_status(
    website_id: uuid.UUID,
    action_id: uuid.UUID,
    body: StatusUpdateRequest,
    db: DatabaseSession,
) -> ActionItemRead:
    website_or_raise(db, website_id)

    action = db.get(ActionItem, action_id)
    if action is None or action.website_id != website_id:
        raise ApplicationError(
            code="ACTION_NOT_FOUND",
            message="Action item not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    try:
        validate_action_transition(action.status, body.status)
    except ValueError as exc:
        raise ApplicationError(
            code="INVALID_STATUS_TRANSITION",
            message=str(exc),
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        ) from exc

    previous_status = action.status
    action.status = body.status
    db.flush()

    history = ActionStatusHistory(
        action_item_id=action.id,
        previous_status=previous_status,
        new_status=body.status,
        reason=body.reason,
        actor=body.actor,
        source=body.source,
    )
    db.add(history)
    db.commit()
    db.refresh(action)

    return ActionItemRead.model_validate(action)


@router.post("/actions/bulk-status", response_model=BulkStatusUpdateResult)
def bulk_update_action_status(
    website_id: uuid.UUID,
    body: BulkStatusUpdateRequest,
    db: DatabaseSession,
) -> BulkStatusUpdateResult:
    website_or_raise(db, website_id)

    total = len(body.action_ids)
    succeeded = 0
    failures: list[dict[str, Any]] = []

    for action_id in body.action_ids:
        action = db.get(ActionItem, action_id)
        if action is None or action.website_id != website_id:
            failures.append(
                {
                    "action_id": str(action_id),
                    "error": "Action not found",
                }
            )
            continue

        try:
            validate_action_transition(action.status, body.status)
        except ValueError as exc:
            failures.append(
                {
                    "action_id": str(action_id),
                    "error": str(exc),
                }
            )
            continue

        previous_status = action.status
        action.status = body.status

        history = ActionStatusHistory(
            action_item_id=action.id,
            previous_status=previous_status,
            new_status=body.status,
            reason=body.reason,
            actor=body.actor,
            source=body.source,
        )
        db.add(history)
        succeeded += 1

    db.commit()

    return BulkStatusUpdateResult(
        total=total,
        succeeded=succeeded,
        failed=len(failures),
        failures=failures,
    )


@router.get("/actions/{action_id}/history", response_model=list[ActionStatusHistoryRead])
def get_action_status_history(
    website_id: uuid.UUID,
    action_id: uuid.UUID,
    db: DatabaseSession,
) -> list[ActionStatusHistoryRead]:
    website_or_raise(db, website_id)

    action = db.get(ActionItem, action_id)
    if action is None or action.website_id != website_id:
        raise ApplicationError(
            code="ACTION_NOT_FOUND",
            message="Action item not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    history = list(
        db.scalars(
            select(ActionStatusHistory)
            .where(ActionStatusHistory.action_item_id == action_id)
            .order_by(ActionStatusHistory.changed_at.asc())
        )
    )

    return [ActionStatusHistoryRead.model_validate(h) for h in history]
