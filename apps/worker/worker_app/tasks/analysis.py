import logging
import time
import uuid
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from worker_app.celery_app import celery_app
from worker_app.db import SessionLocal, analysis_runs, parse_analysis_run_id, utc_now

logger = logging.getLogger(__name__)

LIFECYCLE_STAGES: tuple[tuple[int, str], ...] = (
    (20, "Preparing analysis"),
    (55, "Validating website"),
    (80, "Initializing audit"),
)


def update_run(session: Session, analysis_run_id: uuid.UUID, **values: object) -> None:
    values["updated_at"] = utc_now()
    session.execute(
        update(analysis_runs).where(analysis_runs.c.id == analysis_run_id).values(**values)
    )
    session.commit()


def advance_lifecycle(
    session: Session,
    analysis_run_id: uuid.UUID,
    stages: Iterable[tuple[int, str]] = LIFECYCLE_STAGES,
) -> None:
    for progress_percent, current_step in stages:
        update_run(
            session,
            analysis_run_id,
            progress_percent=progress_percent,
            current_step=current_step,
        )
        logger.info(
            "analysis_state analysis_run_id=%s status=running progress_percent=%s step=%s",
            analysis_run_id,
            progress_percent,
            current_step,
        )
        time.sleep(0.75)


def mark_failed(analysis_run_id: uuid.UUID, completed_at: datetime) -> None:
    with SessionLocal() as session:
        update_run(
            session,
            analysis_run_id,
            status="failed",
            current_step="Analysis failed",
            completed_at=completed_at,
            error_code="ANALYSIS_TASK_FAILED",
            error_message="Analysis lifecycle task failed.",
        )


@celery_app.task(name="worker.run_analysis")
def run_analysis(analysis_run_id: str) -> dict[str, str]:
    run_id = parse_analysis_run_id(analysis_run_id)
    try:
        with SessionLocal() as session:
            status = session.scalar(
                select(analysis_runs.c.status).where(analysis_runs.c.id == run_id)
            )
            if status is None:
                logger.warning("analysis_missing analysis_run_id=%s", run_id)
                return {"status": "missing", "analysis_run_id": analysis_run_id}
            if status != "queued":
                logger.info("analysis_skipped analysis_run_id=%s status=%s", run_id, status)
                return {"status": str(status), "analysis_run_id": analysis_run_id}

            update_run(
                session,
                run_id,
                status="running",
                progress_percent=5,
                current_step="Starting analysis",
                started_at=utc_now(),
                error_code=None,
                error_message=None,
            )
            logger.info(
                "analysis_state analysis_run_id=%s status=running progress_percent=5",
                run_id,
            )
            advance_lifecycle(session, run_id)
            update_run(
                session,
                run_id,
                status="completed",
                progress_percent=100,
                current_step="Analysis lifecycle completed",
                completed_at=utc_now(),
            )
            logger.info(
                "analysis_state analysis_run_id=%s status=completed progress_percent=100",
                run_id,
            )
    except Exception as exception:
        logger.error(
            "analysis_failed analysis_run_id=%s exception_type=%s",
            run_id,
            type(exception).__name__,
        )
        mark_failed(run_id, utc_now())
        return {"status": "failed", "analysis_run_id": analysis_run_id}

    return {"status": "completed", "analysis_run_id": analysis_run_id}
