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


def _latest_usable_tier0_execution(
    db: Session,
    *,
    analysis_run_id: uuid.UUID,
    lane: str,
) -> BrowserUatTier0Execution | None:
    """Shared selection rule for both fetch_latest_tier0_* functions below:
    the MOST RECENT terminal-with-evidence Tier 0 execution for this
    analysis run, not a merge across every execution ever run -- an
    analysis run may have zero, one, or several Tier 0 executions (retries,
    explicit re-checks, or a manual Lane C run recorded after an automatic
    Lane A/B one), and merging them could mix stale and fresh evidence or
    double-count pages. Returns None when no usable execution exists.
    """
    return db.scalar(
        select(BrowserUatTier0Execution)
        .where(
            BrowserUatTier0Execution.analysis_run_id == analysis_run_id,
            BrowserUatTier0Execution.lane == lane,
            BrowserUatTier0Execution.status.in_(_USABLE_TIER0_STATUSES),
        )
        .order_by(BrowserUatTier0Execution.completed_at.desc())
        .limit(1)
    )


def fetch_latest_tier0_page_results(
    db: Session,
    *,
    analysis_run_id: uuid.UUID,
    lane: str = DEFAULT_LANE,
) -> list[dict[str, Any]]:
    """Real evidence for M5's evidence-state mapping, as plain dicts (matches
    browser_compatibility.py's dict-based interface, not ORM objects).

    Returns [] when no usable execution exists, which is the correct, honest
    input for apply_tier0_evidence (rows stay exactly as built from engine
    data -- an unavailable Tier 0 lane never blocks or alters the rest of
    the report).
    """
    latest_execution = _latest_usable_tier0_execution(
        db, analysis_run_id=analysis_run_id, lane=lane
    )
    if latest_execution is None:
        return []

    page_results = db.scalars(
        select(BrowserUatTier0PageResult).where(
            BrowserUatTier0PageResult.execution_id == latest_execution.id
        )
    ).all()
    return [
        {
            "browser_channel": page_result.browser_channel,
            "platform": page_result.platform,
            "browser_version": page_result.browser_version,
            "status": page_result.status,
        }
        for page_result in page_results
    ]


def fetch_latest_tier0_structural_results(
    db: Session,
    *,
    analysis_run_id: uuid.UUID,
    lane: str = DEFAULT_LANE,
) -> list[dict[str, Any]]:
    """Real per-page, per-viewport M3 structural evidence (horizontal
    overflow, clipped/overlapping elements, small tap targets) for the SAME
    execution fetch_latest_tier0_page_results would select, as plain dicts.

    Unlike fetch_latest_tier0_page_results' lightweight per-page summary,
    this carries the viewport-level detail report_delivery.py needs to build
    Complete Findings Register entries -- kept as a separate function rather
    than growing that one's return shape, since M5's evidence-state mapping
    and the Findings Register are different, independently-testable
    consumers of the same underlying rows.
    """
    latest_execution = _latest_usable_tier0_execution(
        db, analysis_run_id=analysis_run_id, lane=lane
    )
    if latest_execution is None:
        return []

    page_results = db.scalars(
        select(BrowserUatTier0PageResult).where(
            BrowserUatTier0PageResult.execution_id == latest_execution.id
        )
    ).all()
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
