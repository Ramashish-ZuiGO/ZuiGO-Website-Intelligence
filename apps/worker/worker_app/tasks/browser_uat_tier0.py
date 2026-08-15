"""M2 Tier 0 desktop lane: dispatch a GitHub Actions run for real Chrome/Edge
verification, poll it to completion, and record the result.

Polling reschedules itself via ``apply_async(countdown=...)`` rather than
blocking inside a running task, so a poll cycle never holds a worker
concurrency slot hostage -- consistent with the existing
CELERY_WORKER_CONCURRENCY / worker_prefetch_multiplier=1 policy in
docs/PRODUCTION_OPERATIONS.md.
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from app.db.session import SessionLocal
from app.models import (
    TERMINAL_BROWSER_UAT_TIER0_STATUSES,
    BrowserUatTier0Execution,
    BrowserUatTier0Status,
    Website,
)
from app.services.browser_uat_tier0 import ingest_browser_uat_tier0_job_result
from sqlalchemy import select

from worker_app.celery_app import celery_app
from worker_app.config import get_settings
from worker_app.integrations.browser_uat_tier0_dispatch import (
    DispatchUnavailableError,
    GitHubActionsTier0DispatchClient,
    Tier0DispatchClient,
)

logger = logging.getLogger(__name__)

# ~30 minutes at the interval below -- bounded so a stuck/never-completing
# GitHub Actions run cannot poll forever.
MAX_POLL_ATTEMPTS = 60
POLL_INTERVAL_SECONDS = 30


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _build_dispatch_client() -> Tier0DispatchClient:
    settings = get_settings()
    token = settings.github_actions_token
    # Checking `is None` alone is not enough: docker-compose's `${VAR:-}`
    # substitution sets an unset env var to an EMPTY STRING inside the
    # container, not "absent" -- and pydantic-settings parses that as
    # SecretStr(''), not None, for an Optional[SecretStr] field (verified
    # empirically before relying on this, not assumed). An empty token would
    # otherwise silently reach GitHub as a blank Bearer header instead of
    # failing cleanly here.
    if token is None or not token.get_secret_value().strip():
        raise DispatchUnavailableError("GITHUB_ACTIONS_TOKEN is not configured.")
    return GitHubActionsTier0DispatchClient(
        repo=settings.github_actions_repo,
        ref=settings.github_actions_ref,
        token=token.get_secret_value(),
    )


def _finalize(
    execution_id: str,
    *,
    status: BrowserUatTier0Status,
    output: dict[str, Any],
    provider_run_reference: str | None = None,
) -> None:
    with SessionLocal() as db:
        execution = db.scalar(
            select(BrowserUatTier0Execution).where(
                BrowserUatTier0Execution.execution_id == uuid.UUID(execution_id)
            )
        )
        if execution is None:
            return
        execution.status = status.value
        execution.completed_at = _utc_now()
        execution.structured_output = output
        if provider_run_reference:
            execution.provider_run_reference = provider_run_reference
        db.commit()


@celery_app.task(name="worker.dispatch_browser_uat_tier0", acks_late=True)
def dispatch_browser_uat_tier0(execution_id: str) -> dict[str, Any]:
    with SessionLocal() as db:
        execution = db.scalar(
            select(BrowserUatTier0Execution)
            .where(BrowserUatTier0Execution.execution_id == uuid.UUID(execution_id))
            .with_for_update()
        )
        if execution is None:
            raise RuntimeError("Browser UAT Tier 0 execution is unavailable.")
        if execution.status != BrowserUatTier0Status.PENDING.value:
            # A redelivered/duplicate dispatch must not re-trigger the run.
            return {"status": execution.status, "skipped": True}
        execution.status = BrowserUatTier0Status.RUNNING.value
        execution.started_at = _utc_now()
        website = db.get(Website, execution.website_id)
        correlation_id = execution.correlation_id
        target_url = website.url if website is not None else None
        db.commit()

    if not target_url:
        logger.warning(
            "browser_uat_tier0_dispatch_unavailable execution_id=%s reason=%s",
            execution_id,
            "website_url_unavailable",
        )
        _finalize(
            execution_id,
            status=BrowserUatTier0Status.UNAVAILABLE,
            output={"reason": "Website URL unavailable."},
        )
        return {"status": "unavailable"}

    try:
        client = _build_dispatch_client()
        client.dispatch(correlation_id=correlation_id, target_url=target_url, pages=[target_url])
    except DispatchUnavailableError as exception:
        logger.warning(
            "browser_uat_tier0_dispatch_unavailable execution_id=%s reason=%s",
            execution_id,
            exception,
        )
        _finalize(
            execution_id,
            status=BrowserUatTier0Status.UNAVAILABLE,
            output={"reason": str(exception)},
        )
        return {"status": "unavailable"}

    poll_browser_uat_tier0.apply_async(args=[execution_id], countdown=POLL_INTERVAL_SECONDS)
    return {"status": "dispatched"}


@celery_app.task(name="worker.poll_browser_uat_tier0", acks_late=True)
def poll_browser_uat_tier0(execution_id: str, attempt: int = 1) -> dict[str, Any]:
    with SessionLocal() as db:
        execution = db.scalar(
            select(BrowserUatTier0Execution).where(
                BrowserUatTier0Execution.execution_id == uuid.UUID(execution_id)
            )
        )
        if execution is None:
            return {"status": "unavailable", "skipped": True}
        if execution.status in TERMINAL_BROWSER_UAT_TIER0_STATUSES:
            return {"status": execution.status, "skipped": True}
        correlation_id = execution.correlation_id
        execution_pk = execution.id

    if attempt > MAX_POLL_ATTEMPTS:
        logger.warning(
            "browser_uat_tier0_poll_timeout execution_id=%s attempt=%s",
            execution_id,
            attempt,
        )
        _finalize(
            execution_id,
            status=BrowserUatTier0Status.UNAVAILABLE,
            output={"reason": "Polling exceeded the maximum wait window."},
        )
        return {"status": "unavailable", "reason": "timeout"}

    try:
        client = _build_dispatch_client()
        result = client.poll(correlation_id=correlation_id)
    except DispatchUnavailableError as exception:
        logger.warning(
            "browser_uat_tier0_poll_unavailable execution_id=%s attempt=%s reason=%s",
            execution_id,
            attempt,
            exception,
        )
        _finalize(
            execution_id,
            status=BrowserUatTier0Status.UNAVAILABLE,
            output={"reason": str(exception)},
        )
        return {"status": "unavailable"}

    if result.status != "completed":
        poll_browser_uat_tier0.apply_async(
            args=[execution_id, attempt + 1], countdown=POLL_INTERVAL_SECONDS
        )
        return {"status": "running", "attempt": attempt}

    job_results = result.results or []
    for job_result in job_results:
        with SessionLocal() as db:
            ingest_browser_uat_tier0_job_result(
                db, execution_id=execution_pk, job_result=job_result
            )

    final_status = (
        BrowserUatTier0Status.COMPLETED
        if result.conclusion == "success"
        else BrowserUatTier0Status.PARTIAL
    )
    _finalize(
        execution_id,
        # Lightweight summary only -- the real per-page/per-viewport
        # evidence now lives in BrowserUatTier0PageResult/ViewportResult
        # (M4) via the ingestion above, not duplicated here. See that
        # model's own docstring for why structured_output stays lightweight.
        status=final_status,
        output={"artifact_count": len(job_results)},
        provider_run_reference=result.provider_run_reference,
    )
    return {"status": final_status.value, "artifact_count": len(job_results)}
