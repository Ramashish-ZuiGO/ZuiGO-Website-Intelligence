import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.agent_platform import AgentExecution
from app.models.analysis_run import AnalysisRun
from app.models.performance import PerformanceSnapshot
from app.models.website import Website
from app.services.performance_service import collect_performance_evidence, compare_performance

router = APIRouter(prefix="", tags=["performance"])
DatabaseSession = Annotated[Session, Depends(get_db)]


def get_website_or_raise(db: Session, website_id: uuid.UUID) -> Website:
    website = db.scalar(select(Website).where(Website.id == website_id))
    if not website:
        raise HTTPException(status_code=404, detail="Website not found")
    return website


def get_analysis_run_or_raise(db: Session, run_id: uuid.UUID) -> AnalysisRun:
    run = db.scalar(select(AnalysisRun).where(AnalysisRun.id == run_id))
    if not run:
        raise HTTPException(status_code=404, detail="Analysis run not found")
    return run


@router.get("/websites/{website_id}/performance")
def get_website_performance(website_id: uuid.UUID, db: DatabaseSession) -> dict:
    website = get_website_or_raise(db, website_id)
    snapshots = db.scalars(
        select(PerformanceSnapshot)
        .where(PerformanceSnapshot.website_id == website.id)
        .order_by(PerformanceSnapshot.created_at.desc())
    ).all()

    # Just return raw mapped for now
    return {"data": [{c.name: getattr(s, c.name) for c in s.__table__.columns} for s in snapshots]}


@router.get("/websites/{website_id}/performance/history")
def get_website_performance_history(website_id: uuid.UUID, db: DatabaseSession) -> dict:
    website = get_website_or_raise(db, website_id)
    snapshots = db.scalars(
        select(PerformanceSnapshot)
        .where(PerformanceSnapshot.website_id == website.id)
        .order_by(PerformanceSnapshot.created_at.desc())
    ).all()
    return {
        "history": [{c.name: getattr(s, c.name) for c in s.__table__.columns} for s in snapshots]
    }


@router.get("/websites/{website_id}/performance/comparison")
def get_website_performance_comparison(website_id: uuid.UUID, db: DatabaseSession) -> dict:
    """
    Get a comparison of Field and Lab performance evidence for a given website.
    Highlights discrepancies where lab environment measurements differ significantly
    from real user observations in the field.
    """
    website = get_website_or_raise(db, website_id)
    return compare_performance(db, website.id)


@router.get("/analysis-runs/{run_id}/performance")
def get_analysis_run_performance(run_id: uuid.UUID, db: DatabaseSession) -> dict:
    run = get_analysis_run_or_raise(db, run_id)
    # FE-9: real field-performance (CrUX) evidence is collected once per
    # page-analysis execution (worker_app/tasks/page_analysis.py), tagged by
    # execution_id rather than analysis_run_id -- page analysis runs BEFORE
    # the main AnalysisRun exists, so it never had a real analysis_run_id to
    # tag rows with. This mirrors the same real pattern report_delivery.py
    # already uses for L2 accessibility/lighthouse evidence (M15). Without
    # this, field rows exist in the database but this endpoint -- the one
    # the frontend Performance panel actually calls -- would never find them.
    filters = [PerformanceSnapshot.analysis_run_id == run.id]
    workflow = db.scalar(select(AgentExecution).where(AgentExecution.analysis_run_id == run.id))
    page_execution_id = (
        workflow.structured_input.get("page_analysis_execution_id") if workflow else None
    )
    if page_execution_id:
        filters.append(PerformanceSnapshot.execution_id == uuid.UUID(str(page_execution_id)))
    snapshots = db.scalars(
        select(PerformanceSnapshot)
        .where(PerformanceSnapshot.website_id == run.website_id, or_(*filters))
        .order_by(PerformanceSnapshot.created_at.desc())
    ).all()
    return {"data": [{c.name: getattr(s, c.name) for c in s.__table__.columns} for s in snapshots]}


@router.post("/analysis-runs/{run_id}/performance/collect")
def collect_run_performance(run_id: uuid.UUID, db: DatabaseSession) -> dict:
    run = get_analysis_run_or_raise(db, run_id)
    website = get_website_or_raise(db, run.website_id)

    # execution UUID is run_id in this case, or we generate a new one
    result = collect_performance_evidence(
        db, execution_id=run.id, website=website, analysis_run=run
    )
    return result
