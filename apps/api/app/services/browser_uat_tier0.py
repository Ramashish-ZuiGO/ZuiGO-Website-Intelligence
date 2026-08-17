"""M2 Tier 0 desktop lane: API-side creation of on-demand Chrome/Edge
real-browser verification executions, and M4's ingestion of their real
per-page, per-viewport results. See docs/DEVICE_OS_BROWSER_QA_PLAN.md M2/M4
and worker_app/tasks/browser_uat_tier0.py for the dispatch/poll execution
logic.
"""

import uuid
from typing import Any, TypedDict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors.exceptions import ApplicationError
from app.models import (
    TERMINAL_BROWSER_UAT_TIER0_STATUSES,
    AnalysisRun,
    BrowserUatTier0Execution,
    BrowserUatTier0PageResult,
    BrowserUatTier0ViewportResult,
    Website,
)

# Terminal statuses that carry usable evidence -- excludes "cancelled" and
# "unavailable", which reached a terminal state without producing real
# results.
_USABLE_TIER0_STATUSES = TERMINAL_BROWSER_UAT_TIER0_STATUSES - {"cancelled", "unavailable"}

DEFAULT_LANE = "github_actions_chrome_edge"


class ViewportResultPayload(TypedDict, total=False):
    """Shape produced by responsive_assertions.js -- verified live against
    real Chrome/Edge, see the M3 plan-doc entry. total=False because the
    "failed" (evaluate threw) shape omits most structural fields."""

    name: str
    width: int
    height: int
    status: str
    horizontal_overflow: bool
    critical_elements_outside_viewport: int
    overlapping_elements: int
    small_tap_targets: int
    responsive_navigation: bool
    viewport_problems: list[str]
    tap_target_samples: list[dict[str, Any]]
    error: str


class PageResultPayload(TypedDict, total=False):
    """One entry in browser_uat_tier0_check.mjs's `pages` array."""

    url: str
    status: str
    http_status: int | None
    console_error_count: int
    error: str
    viewport_results: list[ViewportResultPayload]


class JobResultPayload(TypedDict):
    """The exact JSON one Tier 0 GitHub Actions job artifact contains --
    verified live against real Chrome 151 and real Edge 151, 2026-08-14."""

    channel: str
    platform: str
    browser_version: str
    overall_status: str
    pages: list[PageResultPayload]


def build_correlation_id(execution_id: uuid.UUID) -> str:
    """Short, embeddable id for the workflow run-name -- not the full UUID,
    which GitHub's run-name/search matching handles fine but which is nicer
    to read in the Actions UI."""
    return f"tier0-{execution_id.hex[:8]}"


_IN_FLIGHT_TIER0_STATUSES = frozenset(
    {"pending", "running"}
)  # everything NOT in TERMINAL_BROWSER_UAT_TIER0_STATUSES


def create_browser_uat_tier0_execution(
    db: Session,
    *,
    website_id: uuid.UUID,
    analysis_run_id: uuid.UUID,
    idempotency_key: str,
    lane: str = DEFAULT_LANE,
) -> tuple[BrowserUatTier0Execution, bool]:
    """Idempotent creation: replaying the same (analysis_run, lane, key)
    returns the existing execution rather than duplicating it, matching the
    idempotency convention used throughout this codebase. Returns
    (execution, created).

    M8 admission control: at most one in-flight (pending/running) Tier 0
    execution per WEBSITE at a time, regardless of which analysis run or
    idempotency key requests it -- each execution dispatches 3 real GitHub
    Actions jobs, and nothing else in this pipeline bounds how many a
    website could accumulate. Mirrors this codebase's own existing rule for
    the main pipeline ("don't launch parallel same-site acceptance runs",
    see CLAUDE.md). Replaying the SAME idempotency key still succeeds even
    while in flight -- only a genuinely NEW request is refused.

    The website row is locked for the duration of this check-then-insert so
    two truly concurrent requests for the same website can't both observe
    "nothing in flight" and both create an execution -- the same
    SELECT ... FOR UPDATE discipline already used for stage ownership in
    worker_app/tasks/real_analysis.py.
    """
    website = db.scalar(select(Website).where(Website.id == website_id).with_for_update())
    if website is None:
        raise ValueError("Website is unavailable.")

    existing = db.scalar(
        select(BrowserUatTier0Execution).where(
            BrowserUatTier0Execution.analysis_run_id == analysis_run_id,
            BrowserUatTier0Execution.lane == lane,
            BrowserUatTier0Execution.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        return existing, False

    in_flight = db.scalar(
        select(BrowserUatTier0Execution).where(
            BrowserUatTier0Execution.website_id == website_id,
            BrowserUatTier0Execution.lane == lane,
            BrowserUatTier0Execution.status.in_(_IN_FLIGHT_TIER0_STATUSES),
        )
    )
    if in_flight is not None:
        raise ApplicationError(
            code="BROWSER_UAT_TIER0_ALREADY_IN_FLIGHT",
            message=(
                "A Tier 0 browser UAT check is already running for this website. "
                "Wait for it to finish before starting another."
            ),
            status_code=409,
            details={"in_flight_execution_id": str(in_flight.execution_id)},
        )

    analysis_run = db.get(AnalysisRun, analysis_run_id)
    if analysis_run is None:
        raise ValueError("Analysis run is unavailable.")

    execution_id = uuid.uuid4()
    execution = BrowserUatTier0Execution(
        execution_id=execution_id,
        website_id=website_id,
        analysis_run_id=analysis_run_id,
        lane=lane,
        idempotency_key=idempotency_key,
        correlation_id=build_correlation_id(execution_id),
    )
    db.add(execution)
    db.commit()
    db.refresh(execution)
    return execution, True


def ingest_browser_uat_tier0_job_result(
    db: Session,
    *,
    execution_id: uuid.UUID,
    job_result: JobResultPayload,
) -> list[BrowserUatTier0PageResult]:
    """Write one GitHub Actions job's real-browser results into the M4
    normalized tables.

    One execution legitimately produces multiple calls to this function --
    the Tier 0 workflow runs 3 separate jobs (chrome/windows, msedge/windows,
    chrome/macos), each its own artifact. Idempotent per (execution,
    channel, platform, url): re-ingesting the same job's artifact (e.g. after
    a retried poll) updates the existing rows in place rather than
    duplicating them, matching the unique constraint.

    NOT YET WIRED into the dispatch/poll task -- GitHubActionsTier0DispatchClient's
    artifact fetch is still a documented follow-up (docs/DEVICE_OS_BROWSER_QA_PLAN.md
    M2). This function is ready to be called once that lands.
    """
    channel = job_result["channel"]
    platform = job_result["platform"]
    browser_version = job_result.get("browser_version")

    page_results: list[BrowserUatTier0PageResult] = []
    for page in job_result["pages"]:
        page_result = db.scalar(
            select(BrowserUatTier0PageResult).where(
                BrowserUatTier0PageResult.execution_id == execution_id,
                BrowserUatTier0PageResult.browser_channel == channel,
                BrowserUatTier0PageResult.platform == platform,
                BrowserUatTier0PageResult.url == page["url"],
            )
        )
        if page_result is None:
            page_result = BrowserUatTier0PageResult(
                execution_id=execution_id,
                browser_channel=channel,
                platform=platform,
                url=page["url"],
            )
            db.add(page_result)

        page_result.browser_version = browser_version
        page_result.http_status = page.get("http_status")
        page_result.console_error_count = page.get("console_error_count", 0)
        page_result.status = page["status"]
        page_result.error_message = page.get("error")
        db.flush()  # assigns page_result.id for the viewport rows below

        # Idempotent re-ingestion of viewport rows: replace rather than
        # accumulate duplicates, since there's no natural per-viewport
        # unique key finer than (page_result, viewport_name) and a page is
        # always re-checked as a whole unit, never one viewport at a time.
        db.query(BrowserUatTier0ViewportResult).filter(
            BrowserUatTier0ViewportResult.page_result_id == page_result.id
        ).delete()
        for viewport in page.get("viewport_results", []):
            db.add(
                BrowserUatTier0ViewportResult(
                    page_result_id=page_result.id,
                    viewport_name=viewport["name"],
                    viewport_width=viewport["width"],
                    viewport_height=viewport["height"],
                    status=viewport["status"],
                    horizontal_overflow=viewport.get("horizontal_overflow"),
                    critical_elements_outside_viewport=viewport.get(
                        "critical_elements_outside_viewport", 0
                    ),
                    overlapping_elements=viewport.get("overlapping_elements", 0),
                    small_tap_targets=viewport.get("small_tap_targets", 0),
                    responsive_navigation=viewport.get("responsive_navigation"),
                    viewport_problems=list(viewport.get("viewport_problems") or []),
                    tap_target_samples=list(viewport.get("tap_target_samples") or []),
                )
            )
        page_results.append(page_result)

    db.commit()
    for page_result in page_results:
        db.refresh(page_result)
    return page_results


def _usable_tier0_executions(
    db: Session,
    *,
    analysis_run_id: uuid.UUID,
    lane: str,
) -> list[BrowserUatTier0Execution]:
    """Every terminal-with-evidence Tier 0 execution for this analysis run,
    newest-completed first. An analysis run's real coverage often comes from
    MULTIPLE separate executions -- e.g. Lane A/B's automatic GitHub Actions
    dispatch (desktop Chrome/Edge/Safari) and Lane C's manual Android CLI
    run are always separate executions, since Lane C has no way to be
    dispatched together with the others (see
    docs/DEVICE_OS_BROWSER_QA_PLAN.md's Lane C entry). Returns [] when no
    usable execution exists.
    """
    return list(
        db.scalars(
            select(BrowserUatTier0Execution)
            .where(
                BrowserUatTier0Execution.analysis_run_id == analysis_run_id,
                BrowserUatTier0Execution.lane == lane,
                BrowserUatTier0Execution.status.in_(_USABLE_TIER0_STATUSES),
            )
            .order_by(BrowserUatTier0Execution.completed_at.desc())
        )
    )


def _merged_usable_page_results(
    db: Session,
    *,
    analysis_run_id: uuid.UUID,
    lane: str,
) -> list[BrowserUatTier0PageResult]:
    """Real page results across EVERY usable Tier 0 execution for this
    analysis run, deduplicated by (browser_channel, platform, url) -- the
    most-recently-COMPLETED execution's row wins per combination, but an
    older execution still contributes any combination the newer one doesn't
    cover.

    This fixes a real bug found via live verification, not a hypothetical:
    selecting only the single most recent execution meant that ingesting a
    later, narrower Lane C Android-only result made the analysis run's
    earlier, still-valid Lane A/B desktop Chrome/Edge/Safari evidence
    disappear entirely from the customer-facing Browser Compatibility
    matrix and Complete Findings Register -- reverting those rows to "Not
    verified in current environment" even though real evidence for them
    still existed in the database, just in an execution that was no longer
    "the latest." Real, separate Tier 0 lanes must accumulate, not replace
    each other.
    """
    executions = _usable_tier0_executions(db, analysis_run_id=analysis_run_id, lane=lane)
    if not executions:
        return []

    page_results = db.scalars(
        select(BrowserUatTier0PageResult).where(
            BrowserUatTier0PageResult.execution_id.in_([execution.id for execution in executions])
        )
    ).all()
    # executions is already newest-completed-first; sort page results the
    # same way so the loop below naturally keeps the freshest row per
    # combination and only fills in gaps from older executions.
    execution_rank = {execution.id: index for index, execution in enumerate(executions)}
    page_results_newest_first = sorted(
        page_results, key=lambda page_result: execution_rank[page_result.execution_id]
    )

    merged: list[BrowserUatTier0PageResult] = []
    seen_combinations: set[tuple[str, str, str]] = set()
    for page_result in page_results_newest_first:
        combination = (page_result.browser_channel, page_result.platform, page_result.url)
        if combination in seen_combinations:
            continue
        seen_combinations.add(combination)
        merged.append(page_result)
    return merged


def fetch_latest_tier0_page_results(
    db: Session,
    *,
    analysis_run_id: uuid.UUID,
    lane: str = DEFAULT_LANE,
) -> list[dict[str, Any]]:
    """Real evidence for M5's evidence-state mapping, as plain dicts (matches
    browser_compatibility.py's dict-based interface, not ORM objects).

    Returns [] when no usable evidence exists, which is the correct, honest
    input for apply_tier0_evidence (rows stay exactly as built from engine
    data -- an unavailable Tier 0 lane never blocks or alters the rest of
    the report).
    """
    return [
        {
            "browser_channel": page_result.browser_channel,
            "platform": page_result.platform,
            "browser_version": page_result.browser_version,
            "status": page_result.status,
        }
        for page_result in _merged_usable_page_results(
            db, analysis_run_id=analysis_run_id, lane=lane
        )
    ]


def fetch_latest_tier0_structural_results(
    db: Session,
    *,
    analysis_run_id: uuid.UUID,
    lane: str = DEFAULT_LANE,
) -> list[dict[str, Any]]:
    """Real per-page, per-viewport M3 structural evidence (horizontal
    overflow, clipped/overlapping elements, small tap targets) for the SAME
    merged page results fetch_latest_tier0_page_results would select, as
    plain dicts.

    Unlike fetch_latest_tier0_page_results' lightweight per-page summary,
    this carries the viewport-level detail report_delivery.py needs to build
    Complete Findings Register entries -- kept as a separate function rather
    than growing that one's return shape, since M5's evidence-state mapping
    and the Findings Register are different, independently-testable
    consumers of the same underlying rows.
    """
    page_results = _merged_usable_page_results(db, analysis_run_id=analysis_run_id, lane=lane)
    if not page_results:
        return []

    viewport_results = db.scalars(
        select(BrowserUatTier0ViewportResult).where(
            BrowserUatTier0ViewportResult.page_result_id.in_(
                [page_result.id for page_result in page_results]
            )
        )
    ).all()
    viewports_by_page: dict[uuid.UUID, list[BrowserUatTier0ViewportResult]] = {}
    for viewport in viewport_results:
        viewports_by_page.setdefault(viewport.page_result_id, []).append(viewport)

    return [
        {
            "page_result_id": str(page_result.id),
            "url": page_result.url,
            "browser_channel": page_result.browser_channel,
            "platform": page_result.platform,
            "browser_version": page_result.browser_version,
            "status": page_result.status,
            "error_message": page_result.error_message,
            "viewport_results": [
                {
                    "viewport_name": viewport.viewport_name,
                    "viewport_width": viewport.viewport_width,
                    "viewport_height": viewport.viewport_height,
                    "horizontal_overflow": viewport.horizontal_overflow,
                    "critical_elements_outside_viewport": (
                        viewport.critical_elements_outside_viewport
                    ),
                    "overlapping_elements": viewport.overlapping_elements,
                    "small_tap_targets": viewport.small_tap_targets,
                    "tap_target_samples": list(viewport.tap_target_samples),
                }
                for viewport in viewports_by_page.get(page_result.id, [])
            ],
        }
        for page_result in page_results
    ]


def fetch_latest_tier0_execution(
    db: Session,
    *,
    analysis_run_id: uuid.UUID,
    lane: str = DEFAULT_LANE,
) -> BrowserUatTier0Execution | None:
    """The single most recent Tier 0 execution for this analysis run,
    REGARDLESS of status -- unlike _usable_tier0_executions (which only
    returns terminal-with-evidence executions, correct for M5/the Findings
    Register), a status-polling consumer needs to see "pending" and
    "running" executions too, so it knows to keep polling rather than
    concluding no check was ever started. Returns None only when this
    analysis run has never had a Tier 0 execution in this lane at all.
    """
    return db.scalar(
        select(BrowserUatTier0Execution)
        .where(
            BrowserUatTier0Execution.analysis_run_id == analysis_run_id,
            BrowserUatTier0Execution.lane == lane,
        )
        .order_by(BrowserUatTier0Execution.requested_at.desc())
        .limit(1)
    )
