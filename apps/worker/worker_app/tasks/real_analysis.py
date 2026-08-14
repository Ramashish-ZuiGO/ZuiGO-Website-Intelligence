import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from app.db.session import SessionLocal
from app.models import (
    AgentArtifact,
    AgentExecution,
    AnalysisRun,
    DiscoveryRun,
    DiscoveryRunPage,
    PageAnalysisRun,
    WebsitePage,
)
from app.services.browser_compatibility import (
    CompatibilityProfile,
    run_compatibility_analysis,
)
from app.services.page_selection import select_scheduled_pages
from app.services.resource_classification import (
    ResourceClassification,
    classify_resource,
)
from celery import chain
from celery.exceptions import Ignore
from sqlalchemy import func, select

from worker_app.celery_app import celery_app
from worker_app.tasks.agent_platform import run_workflow_execution
from worker_app.tasks.analysis import run_analysis
from worker_app.tasks.discovery import run_discovery
from worker_app.tasks.page_analysis import run_page_analysis


def _utc_now() -> datetime:
    return datetime.now(UTC)


REAL_STAGE_NAMES = (
    "discovery",
    "page-analysis",
    "primary-analysis",
    "browser-compatibility",
    "agent-workflow",
)
REAL_BROWSER_NAVIGATION_TIMEOUT_MS: int = 15_000
TERMINAL_REAL_EXECUTION_STATUSES = frozenset(
    {"completed", "partial", "failed", "cancelled", "unavailable"}
)
# Where per-stage execution ownership is recorded inside structured_output.
STAGE_OWNERSHIP_KEY = "stage_ownership"


def real_stage_task_ids(execution_id: str, attempt: int) -> dict[str, str]:
    return {
        stage: f"real-analysis:{execution_id}:attempt:{attempt}:{stage}"
        for stage in REAL_STAGE_NAMES
    }


def _execution(execution_id: str) -> AgentExecution:
    with SessionLocal() as db:
        execution = db.scalar(
            select(AgentExecution).where(AgentExecution.execution_id == uuid.UUID(execution_id))
        )
        if execution is None:
            raise RuntimeError("Workflow execution is unavailable.")
        db.expunge(execution)
        return execution


def _skip_terminal_stage(execution_id: str, stage: str) -> dict[str, Any] | None:
    execution = _execution(execution_id)
    if execution.status not in TERMINAL_REAL_EXECUTION_STATUSES:
        return None
    return {
        "status": execution.status,
        "stage": stage,
        "skipped": True,
    }


class DuplicateStageDelivery(Exception):
    """Raised when a stage delivery is not the owner of (execution, attempt, stage)."""


def _claim_stage(execution_id: str, stage: str) -> dict[str, Any] | None:
    """Atomically take exclusive ownership of one (execution, attempt, stage).

    Celery task ids do not guarantee single execution: a broker redelivery, a
    worker reconnect or a prefetch race can deliver the identical stage message
    while the first delivery is still running, and both copies would then
    perform side effects. Ownership is recorded in the execution row itself and
    claimed under ``SELECT ... FOR UPDATE``, so Postgres — not Redis — is the
    coordination authority and concurrent claimants are serialised.

    Returns a skip payload when the execution is already terminal (existing
    behaviour), ``None`` when this delivery owns the stage, and raises
    ``DuplicateStageDelivery`` when another delivery already owns it.

    Ownership is scoped to ``attempt`` and is released by the attempt bump that
    ``prepare_resume`` performs, never by a timer and never by hand: a stale
    claim from a crashed worker cannot block attempt N+1, and no expiry window
    exists during which two deliveries could both consider themselves owner.
    """
    parsed_id = uuid.UUID(execution_id)
    with SessionLocal() as db:
        execution = db.scalar(
            select(AgentExecution).where(AgentExecution.execution_id == parsed_id).with_for_update()
        )
        if execution is None:
            raise RuntimeError("Workflow execution is unavailable.")
        if execution.status in TERMINAL_REAL_EXECUTION_STATUSES:
            return {
                "status": execution.status,
                "stage": stage,
                "skipped": True,
            }
        output = dict(execution.structured_output)
        ownership = dict(output.get(STAGE_OWNERSHIP_KEY, {}))
        existing = ownership.get(stage)
        if existing is not None and int(existing.get("attempt", 0)) >= execution.attempt:
            raise DuplicateStageDelivery(
                f"Stage {stage} of attempt {execution.attempt} is already owned."
            )
        ownership[stage] = {
            "owner_token": uuid.uuid4().hex,
            "attempt": execution.attempt,
            "claimed_at": _utc_now().isoformat(),
        }
        output[STAGE_OWNERSHIP_KEY] = ownership
        execution.structured_output = output
        db.commit()
    return None


def _enter_stage(execution_id: str, stage: str) -> dict[str, Any] | None:
    """Stage entry guard shared by every real-analysis stage.

    Terminal executions skip exactly as before. Otherwise this delivery must
    win the ownership claim to proceed.

    A duplicate delivery raises ``Ignore`` rather than returning: Celery
    dispatches chain continuations only on the success path, so returning
    normally would advance the chain and let the next stage start while the
    genuine owner is still working. ``Ignore`` acks the message, records no
    fabricated completion, and leaves chain progression to the real owner.
    """
    skipped = _skip_terminal_stage(execution_id, stage)
    if skipped is not None:
        return skipped
    try:
        return _claim_stage(execution_id, stage)
    except DuplicateStageDelivery:
        raise Ignore() from None


def _update_journey_stage(
    execution_id: str,
    stage: str,
    *,
    journey_status: str = "running",
    completed_stage_id: str | None = None,
    browser_compatibility: dict[str, Any] | None = None,
    additional_output: dict[str, Any] | None = None,
) -> None:
    with SessionLocal() as db:
        execution = db.scalar(
            select(AgentExecution).where(AgentExecution.execution_id == uuid.UUID(execution_id))
        )
        if execution is None:
            return
        if execution.status in TERMINAL_REAL_EXECUTION_STATUSES:
            return
        output = dict(execution.structured_output)
        output["journey_stage"] = stage
        output["journey_status"] = journey_status
        output["journey_updated_at"] = _utc_now().isoformat()
        if completed_stage_id is not None:
            output["completed_stage_ids"] = sorted(
                {
                    *output.get("completed_stage_ids", []),
                    completed_stage_id,
                }
            )
        if browser_compatibility is not None:
            output["browser_compatibility"] = browser_compatibility
        if additional_output:
            output.update(additional_output)
        execution.structured_output = output
        if journey_status == "running" and execution.status == "pending":
            execution.status = "running"
        db.commit()


def _begin_journey(execution_id: str) -> tuple[AgentExecution, bool]:
    parsed_id = uuid.UUID(execution_id)
    with SessionLocal() as db:
        execution = db.scalar(
            select(AgentExecution).where(AgentExecution.execution_id == parsed_id).with_for_update()
        )
        if execution is None:
            raise RuntimeError("Workflow execution is unavailable.")
        if execution.status in {
            "completed",
            "partial",
            "failed",
            "cancelled",
            "unavailable",
        }:
            db.expunge(execution)
            return execution, False
        output = dict(execution.structured_output)
        if execution.status == "running" and output.get("journey_status") == "running":
            db.expunge(execution)
            return execution, False
        task_ids = real_stage_task_ids(execution_id, execution.attempt)
        completed_stage_ids = set(output.get("completed_stage_ids", []))
        if execution.attempt > 1:
            completed_stage_ids.discard("browser_compatibility")
            output.pop("failed_stage_id", None)
            output.pop("agent_workflow_ready", None)
        output.update(
            {
                "journey_stage": "website_discovery",
                "journey_status": "running",
                "journey_updated_at": _utc_now().isoformat(),
                "completed_stage_ids": sorted({*completed_stage_ids, "setup"}),
                "stage_task_ids": task_ids,
                "browser_compatibility": {
                    "status": "not_started",
                    "reason": "Browser analysis starts after page evidence is retained.",
                    "engines": [
                        {
                            "engine": engine,
                            "eligible_pages": 0,
                            "queued_pages": 0,
                            "attempted_pages": 0,
                            "tested_pages": 0,
                            "passed_pages": 0,
                            "partial_pages": 0,
                            "failed_pages": 0,
                            "inconclusive_pages": 0,
                            "unavailable_pages": 0,
                        }
                        for engine in execution.structured_input.get("browser_engines", [])
                    ],
                },
            }
        )
        metadata = dict(execution.provider_version_metadata)
        metadata["stage_task_ids"] = task_ids
        execution.provider_version_metadata = metadata
        execution.structured_output = output
        execution.status = "running"
        execution.completed_at = None
        db.commit()
        db.refresh(execution)
        db.expunge(execution)
        return execution, True


def _mark_stage_failed(
    execution_id: str,
    stage: str,
    code: str,
    message: str,
    *,
    transient: bool,
) -> None:
    with SessionLocal() as db:
        execution = db.scalar(
            select(AgentExecution).where(AgentExecution.execution_id == uuid.UUID(execution_id))
        )
        if execution is None or execution.status in TERMINAL_REAL_EXECUTION_STATUSES:
            return
        output = dict(execution.structured_output)
        output.update(
            {
                "journey_stage": stage,
                "journey_status": "failed",
                "journey_updated_at": _utc_now().isoformat(),
                "failed_stage_id": stage,
            }
        )
        if stage != "browser_compatibility":
            browser = dict(output.get("browser_compatibility", {}))
            if browser.get("status") in {None, "not_started", "queued"}:
                browser.update(
                    {
                        "status": "not_started",
                        "reason": "A required earlier stage did not complete.",
                    }
                )
                output["browser_compatibility"] = browser
        execution.structured_output = output
        execution.status = "failed"
        execution.failure_details = {
            "code": code,
            "message": message,
            "transient": transient,
            "failed_stage": stage,
        }
        execution.completed_at = _utc_now()
        db.commit()


def _usable_page_count(discovery_run_id: str, execution_id: str) -> int:
    with SessionLocal() as db:
        execution = db.scalar(
            select(AgentExecution).where(AgentExecution.execution_id == uuid.UUID(execution_id))
        )
        if execution is None:
            return 0
        page_execution_id = uuid.UUID(str(execution.structured_input["page_analysis_execution_id"]))
        return (
            db.query(PageAnalysisRun)
            .filter(
                PageAnalysisRun.discovery_run_id == uuid.UUID(discovery_run_id),
                PageAnalysisRun.page_analysis_execution_id == page_execution_id,
                PageAnalysisRun.analysis_level == 1,
                PageAnalysisRun.status.in_(("completed", "partial")),
            )
            .count()
        )


def _require_discovery(discovery_run_id: str) -> None:
    with SessionLocal() as db:
        discovery = db.get(DiscoveryRun, uuid.UUID(discovery_run_id))
        status = (
            discovery.status.value
            if discovery is not None and hasattr(discovery.status, "value")
            else str(discovery.status)
            if discovery is not None
            else "missing"
        )
        if status not in {"completed", "partial"}:
            message = (
                discovery.failure_message
                if discovery and discovery.failure_message
                else "Website discovery did not produce usable evidence."
            )
            raise RuntimeError(message)


def _browser_engine_progress(
    result: dict[str, Any],
    engines: tuple[str, ...],
    eligible_page_count: int,
) -> list[dict[str, Any]]:
    observations = list(result.get("observations", []))
    matrix = list(result.get("matrix", []))
    summaries: list[dict[str, Any]] = []
    for engine in engines:
        attempted_urls = {
            str(item["page_url"]) for item in observations if item.get("engine") == engine
        }
        tested_urls = {
            str(item["page_url"])
            for item in observations
            if item.get("engine") == engine
            and item.get("state") not in {"not_tested", "unavailable"}
        }
        states = [str(item.get("engines", {}).get(engine, "not_tested")) for item in matrix]
        summaries.append(
            {
                "engine": engine,
                "eligible_pages": eligible_page_count,
                "queued_pages": max(0, eligible_page_count - len(attempted_urls)),
                "attempted_pages": len(attempted_urls),
                "tested_pages": len(tested_urls),
                "passed_pages": states.count("compatible"),
                "partial_pages": states.count("partially_compatible"),
                "failed_pages": states.count("incompatible"),
                "inconclusive_pages": states.count("inconclusive") + states.count("not_tested"),
                "unavailable_pages": states.count("unavailable"),
            }
        )
    return summaries


def collect_real_browser_compatibility(
    discovery_run_id: str,
    execution_id: str,
) -> dict[str, Any]:
    parsed_execution_id = uuid.UUID(execution_id)
    parsed_discovery_id = uuid.UUID(discovery_run_id)
    with SessionLocal() as db:
        execution = db.scalar(
            select(AgentExecution).where(AgentExecution.execution_id == parsed_execution_id)
        )
        if execution is None:
            raise RuntimeError("Workflow execution is unavailable.")
        existing = db.scalar(
            select(AgentArtifact).where(
                AgentArtifact.execution_id == execution.id,
                AgentArtifact.artifact_type == "browser_compatibility_evidence",
            )
        )
        if existing is not None:
            return dict(existing.artifact_metadata)
        page_execution_id = uuid.UUID(str(execution.structured_input["page_analysis_execution_id"]))
        page_runs = list(
            db.scalars(
                select(PageAnalysisRun).where(
                    PageAnalysisRun.discovery_run_id == parsed_discovery_id,
                    PageAnalysisRun.page_analysis_execution_id == page_execution_id,
                    PageAnalysisRun.analysis_level == 1,
                )
            )
        )
        runs_by_page_id = {item.website_page_id: item for item in page_runs}
        selected_ids = {
            uuid.UUID(str(item))
            for item in execution.structured_output.get("page_analysis_summary", {}).get(
                "selected_page_ids", []
            )
        } or set(runs_by_page_id)
        website_uuid = uuid.UUID(str(execution.structured_input["website_id"]))
        # ``selected_ids`` is derived from this run's own page-analysis records
        # (PageAnalysisRun scoped by discovery_run_id + page_analysis_execution_id)
        # and is therefore run-safe. Select those pages by id WITHOUT filtering on
        # the shared ``last_discovery_run_id`` pointer, which a concurrent
        # same-website run overwrites. When no run-scoped selection exists, fall
        # back to this run's discovery membership (still run-scoped).
        if selected_ids:
            pages = list(
                db.scalars(
                    select(WebsitePage)
                    .where(
                        WebsitePage.website_id == website_uuid,
                        WebsitePage.id.in_(selected_ids),
                    )
                    .order_by(WebsitePage.crawl_depth, WebsitePage.normalized_url)
                )
            )
        else:
            member_count = (
                db.scalar(
                    select(func.count())
                    .select_from(DiscoveryRunPage)
                    .where(DiscoveryRunPage.discovery_run_id == parsed_discovery_id)
                )
                or 0
            )
            if member_count > 0:
                eligible_stmt = (
                    select(WebsitePage)
                    .join(DiscoveryRunPage, DiscoveryRunPage.website_page_id == WebsitePage.id)
                    .where(
                        DiscoveryRunPage.discovery_run_id == parsed_discovery_id,
                        DiscoveryRunPage.eligibility_status == "eligible",
                    )
                    .order_by(WebsitePage.crawl_depth, WebsitePage.normalized_url)
                )
            else:
                eligible_stmt = (
                    select(WebsitePage)
                    .where(
                        WebsitePage.website_id == website_uuid,
                        WebsitePage.last_discovery_run_id == parsed_discovery_id,
                        WebsitePage.eligibility_status == "eligible",
                    )
                    .order_by(WebsitePage.crawl_depth, WebsitePage.normalized_url)
                )
            pages = select_scheduled_pages(
                list(db.scalars(eligible_stmt)),
                execution.structured_input.get("maximum_pages"),
            )
        pages = [
            page
            for page in pages
            if (
                classify_resource(
                    page.normalized_url,
                    final_url=(
                        runs_by_page_id[page.id].final_url
                        if page.id in runs_by_page_id
                        else page.final_url
                    ),
                    content_type=(
                        runs_by_page_id[page.id].content_type
                        if page.id in runs_by_page_id
                        else None
                    ),
                    failure_code=(
                        runs_by_page_id[page.id].failure_reason_code
                        if page.id in runs_by_page_id
                        else None
                    ),
                    eligibility_status=page.eligibility_status,
                    exclusion_reason=page.exclusion_reason,
                    skip_reason=page.skip_reason,
                    origin_relation=page.origin_relation,
                ).classification
                == ResourceClassification.ELIGIBLE_HTML_PAGE
            )
        ]
        page_records = [
            {
                "url": (
                    runs_by_page_id[page.id].final_url
                    if page.id in runs_by_page_id and runs_by_page_id[page.id].final_url
                    else page.final_url or page.normalized_url
                ),
                "title": page.page_title,
                "page_type": page.page_type,
                "analysis_status": (
                    runs_by_page_id[page.id].status
                    if page.id in runs_by_page_id
                    else page.page_analysis_level_1_status
                ),
                "critical": page.crawl_depth == 0,
            }
            for page in pages
        ]
        engine_values = tuple(execution.structured_input.get("browser_engines") or ())
        browser_eligible_count = len(page_records)
        browser_page_limit = browser_eligible_count
        profile = CompatibilityProfile(
            profile_id="real_website_cross_browser",
            engines=engine_values or ("chromium", "firefox", "webkit"),
            include_mobile=bool(execution.structured_input.get("include_mobile", True)),
            all_pages_limit=browser_page_limit,
            representative_sample_size=browser_page_limit,
            navigation_timeout_ms=REAL_BROWSER_NAVIGATION_TIMEOUT_MS,
        )
        pending = {
            "status": "running",
            "profile_id": profile.profile_id,
            "profile_version": profile.version,
            "eligible_page_count": browser_eligible_count,
            "engines": [
                {
                    "engine": engine,
                    "eligible_pages": browser_eligible_count,
                    "queued_pages": browser_eligible_count,
                    "attempted_pages": 0,
                    "tested_pages": 0,
                    "passed_pages": 0,
                    "partial_pages": 0,
                    "failed_pages": 0,
                    "inconclusive_pages": 0,
                    "unavailable_pages": 0,
                }
                for engine in profile.engines
            ],
        }
    _update_journey_stage(
        execution_id,
        "browser_engine_analysis",
        browser_compatibility=pending,
    )

    def progress(observations: list[dict[str, Any]]) -> None:
        progress_result = {"observations": observations, "matrix": []}
        by_engine = _browser_engine_progress(
            progress_result,
            profile.engines,
            browser_eligible_count,
        )
        _update_journey_stage(
            execution_id,
            "browser_engine_analysis",
            browser_compatibility={
                **pending,
                "engines": by_engine,
                "observation_count": len(observations),
            },
        )

    result = run_compatibility_analysis(
        page_records,
        profile=profile,
        observation_callback=progress,
    )
    result["status"] = (
        "completed"
        if result["observations"]
        and any(item.get("state") == "tested" for item in result["observations"])
        else "unavailable"
    )
    result["engine_coverage"] = _browser_engine_progress(
        result,
        profile.engines,
        int(result["eligible_page_count"]),
    )
    result["engines"] = result["engine_coverage"]
    encoded = json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    with SessionLocal() as db:
        execution = db.scalar(
            select(AgentExecution).where(AgentExecution.execution_id == parsed_execution_id)
        )
        if execution is None:
            raise RuntimeError("Workflow execution is unavailable.")
        if execution.status in TERMINAL_REAL_EXECUTION_STATUSES:
            return {
                "status": execution.status,
                "skipped": True,
                "reason": "execution_terminal",
            }
        artifact = AgentArtifact(
            artifact_id=uuid.uuid5(
                parsed_execution_id,
                "artifact:browser-compatibility:1",
            ),
            execution_id=execution.id,
            artifact_type="browser_compatibility_evidence",
            name="Cross-browser compatibility evidence",
            storage_reference=(
                f"database://agent-artifacts/{parsed_execution_id}/browser-compatibility"
            ),
            content_hash=hashlib.sha256(encoded).hexdigest(),
            media_type="application/json",
            artifact_metadata=result,
            evidence_references=[
                {
                    "evidence_type": "browser_compatibility_evidence",
                    "evidence_id": str(parsed_execution_id),
                    "source": "playwright_browser_engines",
                }
            ],
        )
        db.add(artifact)
        output = dict(execution.structured_output)
        output["journey_stage"] = "multi_agent_analysis"
        output["browser_compatibility"] = result
        execution.structured_output = output
        db.commit()
    return result


@celery_app.task(name="worker.run_real_discovery_stage", acks_late=True)
def run_real_discovery_stage(
    discovery_run_id: str,
    workflow_execution_id: str,
) -> dict[str, Any]:
    skipped = _enter_stage(workflow_execution_id, "website_discovery")
    if skipped is not None:
        return skipped
    _update_journey_stage(workflow_execution_id, "website_discovery")
    try:
        run_discovery.run(discovery_run_id)
        _require_discovery(discovery_run_id)
    except Exception as exception:
        _mark_stage_failed(
            workflow_execution_id,
            "website_discovery",
            "DISCOVERY_PREREQUISITE_FAILED",
            str(exception)[:500] or "Website discovery did not produce usable evidence.",
            transient=False,
        )
        raise
    _update_journey_stage(
        workflow_execution_id,
        "page_analysis",
        completed_stage_id="website_discovery",
    )
    return {"status": "completed", "stage": "website_discovery"}


@celery_app.task(name="worker.run_real_page_analysis_stage", acks_late=True)
def run_real_page_analysis_stage(
    discovery_run_id: str,
    page_analysis_execution_id: str,
    workflow_execution_id: str,
) -> dict[str, Any]:
    skipped = _enter_stage(workflow_execution_id, "page_analysis")
    if skipped is not None:
        return skipped
    _update_journey_stage(workflow_execution_id, "page_analysis")
    try:
        result = run_page_analysis.run(
            discovery_run_id,
            page_analysis_execution_id,
        )
        if _usable_page_count(discovery_run_id, workflow_execution_id) == 0:
            raise RuntimeError("No scheduled page produced usable analysis evidence.")
    except Exception as exception:
        _mark_stage_failed(
            workflow_execution_id,
            "page_analysis",
            "PAGE_ANALYSIS_FAILED",
            str(exception)[:500] or "Scheduled pages could not be analysed.",
            transient=True,
        )
        raise
    _update_journey_stage(
        workflow_execution_id,
        "primary_page_analysis",
        completed_stage_id="page_analysis",
        additional_output={"page_analysis_summary": result},
    )
    return result


@celery_app.task(name="worker.run_real_primary_analysis_stage", acks_late=True)
def run_real_primary_analysis_stage(
    analysis_run_id: str,
    discovery_run_id: str,
    workflow_execution_id: str,
) -> dict[str, Any]:
    skipped = _enter_stage(workflow_execution_id, "primary_page_analysis")
    if skipped is not None:
        return skipped
    execution = _execution(workflow_execution_id)
    retained_status = str(execution.structured_output.get("primary_analysis_status") or "")
    if (
        execution.attempt > 1
        and retained_status in TERMINAL_REAL_EXECUTION_STATUSES
        and _usable_page_count(discovery_run_id, workflow_execution_id) > 0
    ):
        _update_journey_stage(
            workflow_execution_id,
            "browser_compatibility",
            additional_output={
                "primary_analysis_status": retained_status,
                "primary_analysis_retry_skipped": True,
            },
        )
        return {
            "status": retained_status,
            "continued_with_page_evidence": retained_status != "completed",
            "retry_skipped": True,
        }
    _update_journey_stage(workflow_execution_id, "primary_page_analysis")
    result = run_analysis.run(analysis_run_id)
    with SessionLocal() as db:
        run = db.get(AnalysisRun, uuid.UUID(analysis_run_id))
        status = (
            run.status.value
            if run is not None and hasattr(run.status, "value")
            else str(run.status)
            if run is not None
            else "missing"
        )
        safe_error = (
            run.error_message
            if run is not None and run.error_message
            else "Primary deep-analysis evidence is unavailable."
        )
    if (
        status != "completed"
        and _usable_page_count(
            discovery_run_id,
            workflow_execution_id,
        )
        == 0
    ):
        _mark_stage_failed(
            workflow_execution_id,
            "diagnostics_scoring",
            "PRIMARY_ANALYSIS_PREREQUISITE_FAILED",
            safe_error,
            transient=True,
        )
        raise RuntimeError(safe_error)
    _update_journey_stage(
        workflow_execution_id,
        "browser_compatibility",
        additional_output={
            "primary_analysis_status": status,
            "primary_analysis_message": None if status == "completed" else safe_error,
        },
    )
    return {
        **result,
        "status": status,
        "continued_with_page_evidence": status != "completed",
    }


@celery_app.task(name="worker.run_real_browser_stage", acks_late=True)
def run_real_browser_stage(
    discovery_run_id: str,
    workflow_execution_id: str,
) -> dict[str, Any]:
    skipped = _enter_stage(workflow_execution_id, "browser_compatibility")
    if skipped is not None:
        return skipped
    _update_journey_stage(workflow_execution_id, "browser_compatibility")
    try:
        result = collect_real_browser_compatibility(
            discovery_run_id,
            workflow_execution_id,
        )
    except Exception as exception:
        execution = _execution(workflow_execution_id)
        engines = execution.structured_input.get("browser_engines", [])
        eligible_count = _usable_page_count(
            discovery_run_id,
            workflow_execution_id,
        )
        result = {
            "status": "failed_to_start",
            "reason": (
                "Browser-engine analysis could not start. Retained page evidence remains available."
            ),
            "failure_type": type(exception).__name__,
            "eligible_page_count": eligible_count,
            "engines": [
                {
                    "engine": engine,
                    "eligible_pages": eligible_count,
                    "queued_pages": 0,
                    "attempted_pages": 0,
                    "tested_pages": 0,
                    "passed_pages": 0,
                    "partial_pages": 0,
                    "failed_pages": 0,
                    "inconclusive_pages": 0,
                    "unavailable_pages": eligible_count,
                }
                for engine in engines
            ],
        }
    _update_journey_stage(
        workflow_execution_id,
        "multi_agent_analysis",
        completed_stage_id="browser_compatibility",
        browser_compatibility=result,
    )
    return result


@celery_app.task(name="worker.run_real_agent_stage", acks_late=True)
def run_real_agent_stage(workflow_execution_id: str) -> dict[str, Any]:
    skipped = _enter_stage(workflow_execution_id, "multi_agent_analysis")
    if skipped is not None:
        return skipped
    _update_journey_stage(
        workflow_execution_id,
        "multi_agent_analysis",
        additional_output={"agent_workflow_ready": True},
    )
    try:
        return run_workflow_execution.run(workflow_execution_id)
    except Exception as exception:
        _mark_stage_failed(
            workflow_execution_id,
            "multi_agent_analysis",
            "AGENT_WORKFLOW_FAILED",
            "The specialist-agent workflow stopped before report generation.",
            transient=True,
        )
        raise RuntimeError("The specialist-agent workflow failed.") from exception


@celery_app.task(
    bind=True,
    name="worker.run_real_analysis_journey",
    acks_late=True,
    soft_time_limit=3600,
    time_limit=3660,
)
def run_real_analysis_journey(
    self: Any,
    analysis_run_id: str,
    discovery_run_id: str,
    page_analysis_execution_id: str,
    workflow_execution_id: str,
) -> dict[str, str]:
    execution, started = _begin_journey(workflow_execution_id)
    if not started:
        return {
            "execution_id": workflow_execution_id,
            "status": execution.status,
        }
    task_ids = real_stage_task_ids(workflow_execution_id, execution.attempt)
    pipeline = chain(
        celery_app.signature(
            "worker.run_real_discovery_stage",
            args=[discovery_run_id, workflow_execution_id],
            immutable=True,
            task_id=task_ids["discovery"],
        ),
        celery_app.signature(
            "worker.run_real_page_analysis_stage",
            args=[
                discovery_run_id,
                page_analysis_execution_id,
                workflow_execution_id,
            ],
            immutable=True,
            task_id=task_ids["page-analysis"],
        ),
        celery_app.signature(
            "worker.run_real_primary_analysis_stage",
            args=[analysis_run_id, discovery_run_id, workflow_execution_id],
            immutable=True,
            task_id=task_ids["primary-analysis"],
        ),
        celery_app.signature(
            "worker.run_real_browser_stage",
            args=[discovery_run_id, workflow_execution_id],
            immutable=True,
            task_id=task_ids["browser-compatibility"],
        ),
        celery_app.signature(
            "worker.run_real_agent_stage",
            args=[workflow_execution_id],
            immutable=True,
            task_id=task_ids["agent-workflow"],
        ),
    )
    return self.replace(pipeline)
