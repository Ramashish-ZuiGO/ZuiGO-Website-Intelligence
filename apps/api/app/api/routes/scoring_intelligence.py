import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.errors.exceptions import ApplicationError
from app.models import AnalysisRun, ScoreExecution, Website
from app.schemas.scoring_intelligence import (
    PaginatedScoreExecutions,
    ScoreBreakdownRead,
    ScoreCalculateRequest,
    ScoreExecutionRead,
    ScoreExecutionWithTrend,
    ScoringFormulaRead,
    ScoringProfileRead,
)
from app.services import profiles_registry
from app.services.scoring_formula import (
    CATEGORY_WEIGHTS,
    FORMULA_ID,
    FORMULA_VERSION,
    SEVERITY_DEDUCTIONS,
)
from app.services.scoring_intelligence import (
    FORMULA_LIMITATIONS,
    ScoringIntelligenceError,
    calculate_score_execution,
    load_score_execution,
    score_trend,
)

router = APIRouter(tags=["scoring-intelligence"])
DatabaseSession = Annotated[Session, Depends(get_db)]


def _application_error(exception: ScoringIntelligenceError) -> ApplicationError:
    return ApplicationError(
        code=exception.code,
        message=exception.safe_message,
        status_code=exception.status_code,
    )


def _read_with_trend(db: Session, execution: ScoreExecution) -> ScoreExecutionWithTrend:
    base = ScoreExecutionRead.model_validate(execution)
    return ScoreExecutionWithTrend(
        **base.model_dump(),
        trend=score_trend(db, execution),
    )


def _website_or_raise(db: Session, website_id: uuid.UUID) -> Website:
    website = db.get(Website, website_id)
    if website is None:
        raise ApplicationError(
            code="WEBSITE_NOT_FOUND",
            message="Website not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return website


@router.post(
    "/analysis-runs/{run_id}/scores/calculate",
    response_model=ScoreExecutionRead,
    status_code=status.HTTP_201_CREATED,
)
def calculate_run_score(
    run_id: uuid.UUID,
    request: ScoreCalculateRequest,
    db: DatabaseSession,
) -> ScoreExecution:
    try:
        execution, _created = calculate_score_execution(
            db, run_id, idempotency_key=request.idempotency_key
        )
    except ScoringIntelligenceError as exception:
        raise _application_error(exception) from exception
    return execution


@router.get(
    "/analysis-runs/{run_id}/scores",
    response_model=PaginatedScoreExecutions,
)
def list_run_scores(
    run_id: uuid.UUID,
    db: DatabaseSession,
    execution_status: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaginatedScoreExecutions:
    if db.get(AnalysisRun, run_id) is None:
        raise ApplicationError(
            code="ANALYSIS_RUN_NOT_FOUND",
            message="Analysis run not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    filters = [ScoreExecution.analysis_run_id == run_id]
    if execution_status:
        filters.append(ScoreExecution.status == execution_status)
    total = db.scalar(select(func.count()).select_from(ScoreExecution).where(*filters)) or 0
    rows = list(
        db.scalars(
            select(ScoreExecution)
            .where(*filters)
            .order_by(ScoreExecution.created_at.desc(), ScoreExecution.id.desc())
            .offset(offset)
            .limit(limit)
        )
    )
    return PaginatedScoreExecutions(
        items=[_read_with_trend(db, item) for item in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/websites/{website_id}/scores", response_model=ScoreExecutionWithTrend)
def get_latest_website_score(
    website_id: uuid.UUID,
    db: DatabaseSession,
) -> ScoreExecutionWithTrend:
    _website_or_raise(db, website_id)
    execution = db.scalar(
        select(ScoreExecution)
        .where(ScoreExecution.website_id == website_id)
        .order_by(ScoreExecution.created_at.desc(), ScoreExecution.id.desc())
    )
    if execution is None:
        raise ApplicationError(
            code="SCORE_NOT_CALCULATED",
            message="No score execution has been calculated for this website.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return _read_with_trend(db, execution)


@router.get(
    "/websites/{website_id}/scores/history",
    response_model=PaginatedScoreExecutions,
)
def website_score_history(
    website_id: uuid.UUID,
    db: DatabaseSession,
    formula_version: str | None = None,
    profile_id: str | None = None,
    execution_status: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaginatedScoreExecutions:
    _website_or_raise(db, website_id)
    filters = [ScoreExecution.website_id == website_id]
    if formula_version:
        filters.append(ScoreExecution.formula_version == formula_version)
    if profile_id:
        filters.append(ScoreExecution.scoring_profile_id == profile_id)
    if execution_status:
        filters.append(ScoreExecution.status == execution_status)
    total = db.scalar(select(func.count()).select_from(ScoreExecution).where(*filters)) or 0
    rows = list(
        db.scalars(
            select(ScoreExecution)
            .where(*filters)
            .order_by(ScoreExecution.created_at.desc(), ScoreExecution.id.desc())
            .offset(offset)
            .limit(limit)
        )
    )
    return PaginatedScoreExecutions(
        items=[_read_with_trend(db, item) for item in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/scores/{score_execution_id}", response_model=ScoreExecutionWithTrend)
def get_score_execution(
    score_execution_id: uuid.UUID,
    db: DatabaseSession,
) -> ScoreExecutionWithTrend:
    try:
        execution = load_score_execution(db, score_execution_id)
    except ScoringIntelligenceError as exception:
        raise _application_error(exception) from exception
    return _read_with_trend(db, execution)


@router.get("/scores/{score_execution_id}/breakdown", response_model=ScoreBreakdownRead)
def get_score_breakdown(
    score_execution_id: uuid.UUID,
    db: DatabaseSession,
) -> ScoreBreakdownRead:
    try:
        execution = load_score_execution(db, score_execution_id)
    except ScoringIntelligenceError as exception:
        raise _application_error(exception) from exception
    if execution.snapshot is None or execution.explanation is None:
        raise ApplicationError(
            code="SCORE_BREAKDOWN_UNAVAILABLE",
            message="The score breakdown is unavailable.",
            status_code=status.HTTP_409_CONFLICT,
        )
    return ScoreBreakdownRead(
        execution=ScoreExecutionRead.model_validate(execution),
        snapshot=execution.snapshot,
        categories=execution.categories,
        contributions=execution.contributions,
        explanation=execution.explanation,
        trend=score_trend(db, execution),
    )


@router.get("/scoring/formulas", response_model=list[ScoringFormulaRead])
def list_scoring_formulas() -> list[ScoringFormulaRead]:
    return [
        ScoringFormulaRead(
            formula_id=FORMULA_ID,
            version=FORMULA_VERSION,
            category_weights=CATEGORY_WEIGHTS,
            rounding="round-half-up to nearest integer",
            unavailable_behavior="exclude and normalize remaining available weights",
            technical_quality_deductions=SEVERITY_DEDUCTIONS,
            limitations=FORMULA_LIMITATIONS,
            llm_calculation_allowed=False,
        )
    ]


@router.get("/scoring/profiles", response_model=list[ScoringProfileRead])
def list_scoring_profiles() -> list[ScoringProfileRead]:
    return [
        ScoringProfileRead(
            profile_id=profile.profile_id,
            version=profile.version,
            name=profile.name,
            bands={
                "critical_below": 25,
                "poor_below": 50,
                "needs_improvement_below": 90,
                "good_below": 95,
                "excellent_at_or_above": 95,
            },
            threshold_rules=[rule.model_dump(mode="json") for rule in profile.threshold_rules],
            limitations=[
                *profile.limitations,
                "Bands are descriptive internal thresholds, not competitor or ranking claims.",
            ],
        )
        for profile in profiles_registry.get_all_profiles()
    ]
