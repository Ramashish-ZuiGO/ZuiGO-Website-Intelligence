import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.errors.exceptions import ApplicationError
from app.models import AnalysisRun, AnalysisStatus, Website
from app.schemas import AnalysisRunRead
from app.services.analysis_queue import enqueue_analysis

router = APIRouter(tags=["analysis-runs"])
DatabaseSession = Annotated[Session, Depends(get_db)]


def get_website_or_raise(db: Session, website_id: uuid.UUID) -> Website:
    website = db.get(Website, website_id)
    if website is None:
        raise ApplicationError(
            code="WEBSITE_NOT_FOUND",
            message="Website not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return website


@router.post(
    "/websites/{website_id}/analysis-runs",
    response_model=AnalysisRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_analysis(website_id: uuid.UUID, db: DatabaseSession) -> AnalysisRun:
    get_website_or_raise(db, website_id)
    analysis_run = AnalysisRun(website_id=website_id)
    db.add(analysis_run)
    db.commit()
    db.refresh(analysis_run)

    try:
        analysis_run.celery_task_id = enqueue_analysis(str(analysis_run.id))
    except Exception as exception:
        analysis_run.status = AnalysisStatus.FAILED
        analysis_run.error_code = "ANALYSIS_QUEUE_UNAVAILABLE"
        analysis_run.error_message = "Analysis could not be queued."
        db.commit()
        raise ApplicationError(
            code="ANALYSIS_QUEUE_UNAVAILABLE",
            message="Analysis could not be queued.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exception

    db.commit()
    db.refresh(analysis_run)
    return analysis_run


@router.get("/analysis-runs/{analysis_run_id}", response_model=AnalysisRunRead)
def get_analysis_run(analysis_run_id: uuid.UUID, db: DatabaseSession) -> AnalysisRun:
    analysis_run = db.get(AnalysisRun, analysis_run_id)
    if analysis_run is None:
        raise ApplicationError(
            code="ANALYSIS_RUN_NOT_FOUND",
            message="Analysis run not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return analysis_run


@router.get(
    "/websites/{website_id}/analysis-runs",
    response_model=list[AnalysisRunRead],
)
def list_analysis_runs(website_id: uuid.UUID, db: DatabaseSession) -> list[AnalysisRun]:
    get_website_or_raise(db, website_id)
    return list(
        db.scalars(
            select(AnalysisRun)
            .where(AnalysisRun.website_id == website_id)
            .order_by(AnalysisRun.created_at.desc(), AnalysisRun.id.desc())
        )
    )
