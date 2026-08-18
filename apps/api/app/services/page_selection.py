import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

CRITICAL_PAGE_TYPES = frozenset(
    {"home", "homepage", "navigation", "product", "service", "checkout", "contact"}
)

# M15 (docs/REPORT_QUALITY_INITIATIVE.md): the real bounded-cost ceiling for
# real Lighthouse+axe-core (Level 2) runs on the current single-worker,
# sequential-per-page infrastructure -- calibrated against the L2 stage's
# real 300-second default deadline (page_analysis.py's total_deadline) at a
# realistic ~25-30s/page (Playwright navigation + Lighthouse). Was already
# the code's own internal default (worker_app/tasks/page_analysis.py's
# `config.get("max_lighthouse_pages", 10)`) before the two real API call
# sites hardcoded 0, silently disabling it in production. Raising this
# requires either a longer L2 deadline or bounded per-page concurrency --
# see the decision log in docs/REPORT_QUALITY_INITIATIVE.md's M15 entry.
DEFAULT_MAX_LIGHTHOUSE_PAGES = 10


def _value(page: Any, key: str, default: Any = None) -> Any:
    if isinstance(page, Mapping):
        return page.get(key, default)
    return getattr(page, key, default)


def _url(page: Any) -> str:
    return str(_value(page, "normalized_url") or _value(page, "url") or "")


def _crawl_order(page: Any) -> tuple[int, str]:
    return int(_value(page, "crawl_depth", 0) or 0), _url(page)


def select_scheduled_pages[PageRecord](
    pages: Sequence[PageRecord],
    maximum_pages: int | None = None,
) -> list[PageRecord]:
    """Select all pages when no limit, otherwise a stable critical-first sample."""
    ordered = sorted(pages, key=_crawl_order)
    if maximum_pages is None:
        return ordered
    bounded_limit = max(1, int(maximum_pages))
    if len(ordered) <= bounded_limit:
        return ordered

    critical = [
        page
        for page in ordered
        if int(_value(page, "crawl_depth", 0) or 0) == 0
        or str(_value(page, "page_type", "")).casefold() in CRITICAL_PAGE_TYPES
    ]
    selected: dict[str, PageRecord] = {}
    for page in critical:
        if len(selected) >= bounded_limit:
            break
        selected[_url(page)] = page

    representative = sorted(
        (page for page in ordered if _url(page) not in selected),
        key=lambda page: (hashlib.sha256(_url(page).encode()).hexdigest(), _url(page)),
    )
    for page in representative:
        if len(selected) >= bounded_limit:
            break
        selected[_url(page)] = page
    return sorted(selected.values(), key=_crawl_order)
