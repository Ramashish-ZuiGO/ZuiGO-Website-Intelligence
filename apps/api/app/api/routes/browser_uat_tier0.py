"""M2 Tier 0 desktop lane: on-demand real Chrome/Edge verification.

Deliberately decoupled from full_website_analysis -- triggered explicitly per
analysis run, never automatically, so it never adds surprise execution volume
to the main pipeline. See docs/DEVICE_OS_BROWSER_QA_PLAN.md M2.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.errors.exceptions import ApplicationError
from app.models import AnalysisRun
from app.schemas.browser_uat_tier0 import BrowserUatTier0ExecutionRead, BrowserUatTier0StartRequest
from app.services.analysis_queue import enqueue_browser_uat_tier0
from app.services.browser_uat_tier0 import create_browser_uat_tier0_execution

router = APIRouter(prefix="/analysis-runs", tags=["browser-uat-tier0"])
DatabaseSession = Annotated[Session, Depends(get_db)]


@router.post(
    "/{analysis_run_id}/browser-uat/tier0",
    response_model=BrowserUatTier0ExecutionRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_browser_uat_tier0(
    analysis_run_id: uuid.UUID,
    payload: BrowserUatTier0StartRequest,
    db: DatabaseSession,
    response: Response,
) -> BrowserUatTier0ExecutionRead:
    analysis_run = db.get(AnalysisRun, analysis_run_id)
    if analysis_run is None:
        raise ApplicationError(
            code="ANALYSIS_RUN_NOT_FOUND",
            message="Analysis run not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    execution, created = create_browser_uat_tier0_execution(
        db,
        website_id=analysis_run.website_id,
        analysis_run_id=analysis_run_id,
        idempotency_key=payload.idempotency_key,
    )
    if created:
        enqueue_browser_uat_tier0(str(execution.execution_id))
    else:
        # Idempotent replay: the original request already triggered dispatch.
        response.status_code = status.HTTP_200_OK

    return BrowserUatTier0ExecutionRead.model_validate(execution)
