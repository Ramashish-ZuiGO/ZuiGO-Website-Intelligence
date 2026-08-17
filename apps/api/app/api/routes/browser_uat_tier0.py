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
from app.schemas.browser_uat_tier0 import (
    BrowserUatTier0ExecutionRead,
    BrowserUatTier0ResultsRead,
    BrowserUatTier0StartRequest,
)
from app.services.analysis_queue import enqueue_browser_uat_tier0
from app.services.browser_uat_tier0 import (
    create_browser_uat_tier0_execution,
    fetch_latest_tier0_execution,
    fetch_latest_tier0_structural_results,
)

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


def _analysis_run_or_404(db: DatabaseSession, analysis_run_id: uuid.UUID) -> AnalysisRun:
    analysis_run = db.get(AnalysisRun, analysis_run_id)
    if analysis_run is None:
        raise ApplicationError(
            code="ANALYSIS_RUN_NOT_FOUND",
            message="Analysis run not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return analysis_run


@router.get(
    "/{analysis_run_id}/browser-uat/tier0",
    response_model=BrowserUatTier0ExecutionRead,
)
def get_browser_uat_tier0_status(
    analysis_run_id: uuid.UUID,
    db: DatabaseSession,
) -> BrowserUatTier0ExecutionRead:
    """Poll target: the most recent Tier 0 execution for this analysis run,
    in ANY status (pending/running/completed/partial/failed/cancelled/
    unavailable) -- a frontend polls this to know whether to keep waiting,
    not just whether evidence is ready yet (see
    fetch_latest_tier0_execution's own docstring for why this is a
    different query than the one the Findings Register/M5 evidence mapping
    use). 404 only means no Tier 0 check has ever been started for this
    analysis run -- distinct from a check that's still pending or running.
    """
    _analysis_run_or_404(db, analysis_run_id)

    execution = fetch_latest_tier0_execution(db, analysis_run_id=analysis_run_id)
    if execution is None:
        raise ApplicationError(
            code="BROWSER_UAT_TIER0_NOT_FOUND",
            message="No Tier 0 browser check has been started for this analysis run.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return BrowserUatTier0ExecutionRead.model_validate(execution)


@router.get(
    "/{analysis_run_id}/browser-uat/tier0/results",
    response_model=BrowserUatTier0ResultsRead,
)
def get_browser_uat_tier0_results(
    analysis_run_id: uuid.UUID,
    db: DatabaseSession,
) -> BrowserUatTier0ResultsRead:
    """Real per-page, per-viewport structural evidence from the most recent
    USABLE (terminal, evidence-bearing) Tier 0 execution -- the same
    evidence the Complete Findings Register and Browser Compatibility
    matrix are built from, exposed directly for a frontend results view.

    Deliberately never 404s just because no usable execution exists yet
    (still pending/running, or nothing requested) -- an empty
    page_results list is the honest, correct response for an analysis run
    that is itself real. Use GET .../tier0 to distinguish "never started"
    from "started, not finished yet" from "done."
    """
    _analysis_run_or_404(db, analysis_run_id)

    page_results = fetch_latest_tier0_structural_results(db, analysis_run_id=analysis_run_id)
    return BrowserUatTier0ResultsRead(page_results=page_results)
