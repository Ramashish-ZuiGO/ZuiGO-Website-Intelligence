import hashlib
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

BrowserEngine = Literal["chromium", "firefox", "webkit"]
CompatibilityState = Literal[
    "compatible",
    "partially_compatible",
    "incompatible",
    "not_tested",
    "inconclusive",
    "unavailable",
]

DESKTOP_VIEWPORT = {"name": "Desktop", "width": 1440, "height": 900}
MOBILE_VIEWPORT = {"name": "Mobile", "width": 390, "height": 844}
ENGINE_LABELS: dict[BrowserEngine, str] = {
    "chromium": "Chromium engine",
    "firefox": "Firefox engine",
    "webkit": "WebKit engine",
}


@dataclass(frozen=True)
class CompatibilityProfile:
    profile_id: str = "presentation_cross_browser"
    version: str = "1.0.0"
    engines: tuple[BrowserEngine, ...] = ("chromium", "firefox", "webkit")
    include_mobile: bool = True
    all_pages_limit: int = 50
    representative_sample_size: int = 20
    navigation_timeout_ms: int = 30_000
    performance_difference_threshold: float = 0.35

    @property
    def viewports(self) -> tuple[dict[str, int | str], ...]:
        return (DESKTOP_VIEWPORT, MOBILE_VIEWPORT) if self.include_mobile else (DESKTOP_VIEWPORT,)


class PageRunner(Protocol):
    def __call__(
        self,
        engine: BrowserEngine,
        page: dict[str, Any],
        viewport: dict[str, int | str],
        profile: CompatibilityProfile,
    ) -> dict[str, Any]: ...


def select_compatibility_pages(
    pages: Iterable[dict[str, Any]],
    profile: CompatibilityProfile,
) -> list[dict[str, Any]]:
    eligible = [
        page
        for page in pages
        if page.get("analysis_status")
        not in {"excluded", "skipped", "duplicate_normalized", "redirected"}
    ]
    ordered = sorted(eligible, key=lambda page: str(page["url"]))
    if len(ordered) <= profile.all_pages_limit:
        return ordered
    critical = [
        page
        for page in ordered
        if page.get("page_type") in {"home", "product", "checkout", "contact"}
        or page.get("critical")
    ]
    target = max(1, profile.representative_sample_size)
    selected: dict[str, dict[str, Any]] = {}
    for page in critical:
        if len(selected) >= target:
            break
        selected[str(page["url"])] = page
    remaining = sorted(
        (page for page in ordered if str(page["url"]) not in selected),
        key=lambda page: hashlib.sha256(str(page["url"]).encode()).hexdigest(),
    )
    for page in remaining:
        if len(selected) >= target:
            break
        selected[str(page["url"])] = page
    return [selected[url] for url in sorted(selected)]


def classify_compatibility(
    engine_results: Iterable[dict[str, Any]],
    *,
    performance_difference_threshold: float = 0.35,
) -> CompatibilityState:
    results = list(engine_results)
    if not results:
        return "not_tested"
    if all(item.get("state") == "unavailable" for item in results):
        return "unavailable"
    tested = [item for item in results if item.get("state") not in {"not_tested", "unavailable"}]
    if not tested:
        return "not_tested"
    if any(item.get("state") == "inconclusive" for item in tested):
        return "inconclusive"
    deterministic_failures = [
        item
        for item in tested
        if (
            item.get("navigation_success") is False
            or item.get("render_success") is False
            or item.get("critical_element_available") is False
            or item.get("interaction_failures")
            or item.get("layout_overflow") is True
        )
    ]
    working = [
        item
        for item in tested
        if item.get("navigation_success")
        and item.get("render_success")
        and item.get("critical_element_available", True)
        and not item.get("interaction_failures")
        and item.get("layout_overflow") is not True
    ]
    if deterministic_failures and working:
        return "incompatible"
    if deterministic_failures:
        return "inconclusive"
    durations = [
        float(item["duration_ms"])
        for item in tested
        if isinstance(item.get("duration_ms"), (int, float))
    ]
    performance_variation = False
    if len(durations) > 1 and min(durations) > 0:
        performance_variation = (max(durations) - min(durations)) / min(
            durations
        ) > performance_difference_threshold
    warnings = any(
        item.get("console_errors")
        or item.get("javascript_errors")
        or item.get("failed_resources")
        or item.get("viewport_problems")
        or item.get("accessibility_differences")
        for item in tested
    )
    return "partially_compatible" if warnings or performance_variation else "compatible"


def run_compatibility_analysis(
    pages: Iterable[dict[str, Any]],
    *,
    profile: CompatibilityProfile | None = None,
    runner: PageRunner | None = None,
    observation_callback: Callable[[list[dict[str, Any]]], None] | None = None,
) -> dict[str, Any]:
    selected_profile = profile or CompatibilityProfile()
    selected_pages = select_compatibility_pages(pages, selected_profile)
    managed_runner = _ReusablePlaywrightPageRunner() if runner is None else None
    execute = runner or managed_runner
    assert execute is not None
    observations: list[dict[str, Any]] = []
    try:
        for page in selected_pages:
            for engine in selected_profile.engines:
                for viewport in selected_profile.viewports:
                    observation = execute(engine, page, viewport, selected_profile)
                    observations.append(
                        {
                            "page_url": page["url"],
                            "page_title": page.get("title"),
                            "engine": engine,
                            "engine_label": ENGINE_LABELS[engine],
                            "viewport": dict(viewport),
                            **observation,
                        }
                    )
                    if observation_callback is not None:
                        observation_callback(observations)
    finally:
        if managed_runner is not None:
            managed_runner.close()
    matrix = []
    for page in selected_pages:
        by_engine: dict[str, str] = {}
        page_observations = [item for item in observations if item["page_url"] == page["url"]]
        for engine in selected_profile.engines:
            engine_observations = [item for item in page_observations if item["engine"] == engine]
            state = classify_compatibility(
                engine_observations,
                performance_difference_threshold=selected_profile.performance_difference_threshold,
            )
            deterministic_engine_failure = any(
                item.get("navigation_success") is False
                or item.get("render_success") is False
                or item.get("critical_element_available") is False
                or item.get("interaction_failures")
                or item.get("layout_overflow") is True
                for item in engine_observations
            )
            another_engine_works = any(
                item["engine"] != engine
                and item.get("navigation_success")
                and item.get("render_success")
                and item.get("critical_element_available", True)
                and not item.get("interaction_failures")
                and item.get("layout_overflow") is not True
                for item in page_observations
            )
            if state == "inconclusive" and deterministic_engine_failure and another_engine_works:
                state = "incompatible"
            by_engine[engine] = state
        overall = classify_compatibility(
            page_observations,
            performance_difference_threshold=selected_profile.performance_difference_threshold,
        )
        matrix.append(
            {
                "page_url": page["url"],
                "page_title": page.get("title"),
                "engines": by_engine,
                "result": overall,
                "issue_count": sum(
                    bool(
                        item.get("console_errors")
                        or item.get("javascript_errors")
                        or item.get("failed_resources")
                        or item.get("layout_overflow")
                        or item.get("interaction_failures")
                    )
                    for item in page_observations
                ),
            }
        )
    return {
        "profile_id": selected_profile.profile_id,
        "profile_version": selected_profile.version,
        "browser_engine_tests": True,
        "engines": [
            {"engine": engine, "label": ENGINE_LABELS[engine]}
            for engine in selected_profile.engines
        ],
        "viewports": [dict(viewport) for viewport in selected_profile.viewports],
        "eligible_page_count": len(selected_pages),
        "observations": observations,
        "matrix": matrix,
        "limitations": [
            "Results describe Playwright browser engines, not every branded browser version.",
            "Only pages and viewports explicitly listed as tested are covered.",
            "Performance variation is not incompatibility unless an approved threshold is crossed.",
        ],
    }


class _ReusablePlaywrightPageRunner:
    def __init__(self) -> None:
        self._playwright: Any | None = None
        self._browsers: dict[BrowserEngine, Any] = {}

    def __call__(
        self,
        engine: BrowserEngine,
        page_record: dict[str, Any],
        viewport: dict[str, int | str],
        profile: CompatibilityProfile,
    ) -> dict[str, Any]:
        from playwright.sync_api import Error

        if self._playwright is None:
            from playwright.sync_api import sync_playwright

            self._playwright = sync_playwright().start()
        try:
            browser = self._browsers.get(engine)
            if browser is None:
                browser = getattr(self._playwright, engine).launch(
                    headless=True,
                    timeout=profile.navigation_timeout_ms,
                )
                self._browsers[engine] = browser
            return _run_playwright_observation(
                browser,
                page_record,
                viewport,
                profile,
            )
        except Error:
            return {
                "state": "unavailable",
                "navigation_success": False,
                "timeout": False,
                "duration_ms": 0,
            }

    def close(self) -> None:
        for browser in self._browsers.values():
            try:
                browser.close()
            except Exception:
                pass
        self._browsers.clear()
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                pass
            self._playwright = None


def _run_playwright_observation(
    browser: Any,
    page_record: dict[str, Any],
    viewport: dict[str, int | str],
    profile: CompatibilityProfile,
) -> dict[str, Any]:
    from playwright.sync_api import Error, TimeoutError

    from app.services.public_url_safety import (
        PublicURLSafetyError,
        validate_and_normalize_public_url,
    )

    console_errors: list[str] = []
    javascript_errors: list[str] = []
    failed_resources: list[str] = []
    started = time.monotonic()
    try:
        context = browser.new_context(
            viewport={
                "width": int(viewport["width"]),
                "height": int(viewport["height"]),
            }
        )
        try:
            page = context.new_page()
            validated_targets: set[str] = set()
            validated_origins: set[tuple[str, str, int | None]] = set()

            def validate_route(route: Any) -> None:
                requested_url = route.request.url
                if requested_url.startswith(("about:", "blob:", "data:")):
                    route.continue_()
                    return
                parsed = urlsplit(requested_url)
                origin = (
                    parsed.scheme.lower(),
                    (parsed.hostname or "").lower(),
                    parsed.port,
                )
                if origin in validated_origins:
                    validated_targets.add(requested_url)
                    route.continue_()
                    return
                try:
                    normalized = validate_and_normalize_public_url(requested_url)
                except PublicURLSafetyError:
                    route.abort("blockedbyclient")
                    return
                validated_origins.add(origin)
                validated_targets.add(normalized)
                route.continue_()

            page.route("**/*", validate_route)
            page.on(
                "console",
                lambda message: (
                    console_errors.append(message.text[:500])
                    if message.type == "error" and len(console_errors) < 20
                    else None
                ),
            )
            page.on(
                "pageerror",
                lambda error: (
                    javascript_errors.append(str(error)[:500])
                    if len(javascript_errors) < 20
                    else None
                ),
            )
            page.on(
                "requestfailed",
                lambda request: (
                    failed_resources.append(request.url[:2048])
                    if len(failed_resources) < 20
                    else None
                ),
            )
            response = page.goto(
                str(page_record["url"]),
                wait_until="domcontentloaded",
                timeout=profile.navigation_timeout_ms,
            )
            title = page.title()
            render_success = bool(page.locator("body").count())
            critical_selector = str(page_record.get("critical_selector") or "main, h1")
            critical_available = bool(page.locator(critical_selector).count())
            overflow = bool(
                page.evaluate(
                    "() => document.documentElement.scrollWidth > "
                    "document.documentElement.clientWidth"
                )
            )
            final_url = page.url
            validate_and_normalize_public_url(final_url)
            status = response.status if response else None
            return {
                "state": "tested",
                "navigation_success": True,
                "final_url": final_url,
                "status": status,
                "render_success": render_success,
                "page_title": title,
                "critical_element_available": critical_available,
                "console_errors": console_errors,
                "javascript_errors": javascript_errors,
                "failed_resources": failed_resources,
                "layout_overflow": overflow,
                "viewport_problems": [],
                "interaction_failures": [],
                "accessibility_differences": [],
                "duration_ms": round((time.monotonic() - started) * 1000, 2),
                "screenshot_artifact_reference": None,
                "validated_network_target_count": len(validated_targets),
            }
        finally:
            context.close()
    except TimeoutError:
        return {
            "state": "inconclusive",
            "navigation_success": False,
            "timeout": True,
            "duration_ms": round((time.monotonic() - started) * 1000, 2),
        }
    except PublicURLSafetyError:
        return {
            "state": "unavailable",
            "navigation_success": False,
            "timeout": False,
            "unsafe_redirect_blocked": True,
            "duration_ms": round((time.monotonic() - started) * 1000, 2),
        }
    except Error:
        return {
            "state": "unavailable",
            "navigation_success": False,
            "timeout": False,
            "duration_ms": round((time.monotonic() - started) * 1000, 2),
        }


def _playwright_page_runner(
    engine: BrowserEngine,
    page_record: dict[str, Any],
    viewport: dict[str, int | str],
    profile: CompatibilityProfile,
) -> dict[str, Any]:
    runner = _ReusablePlaywrightPageRunner()
    try:
        return runner(engine, page_record, viewport, profile)
    finally:
        runner.close()
