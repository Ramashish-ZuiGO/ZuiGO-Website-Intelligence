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
ENGINE_UAT_LABELS: dict[BrowserEngine, str] = {
    "chromium": "Chromium engine",
    "firefox": "Firefox engine",
    "webkit": "WebKit engine (internal signal only)",
}

# --- LOCKED customer-facing Browser UAT contract -----------------------------
# The customer UAT scope is exactly these three branded browser families.
# Engine execution (chromium/webkit/firefox) is an internal engineering signal
# and must never be promoted to branded verification without actual branded
# browser/platform evidence.

# Canonical machine-readable verification states (locked).
UAT_VERIFICATION_STATES: tuple[str, ...] = (
    "VERIFIED",
    "PARTIALLY_VERIFIED",
    "NOT_VERIFIED",
    "UNAVAILABLE_IN_CURRENT_ENVIRONMENT",
    "NOT_TESTED",
)
UAT_VERIFICATION_STATE_LABELS: dict[str, str] = {
    "VERIFIED": "Verified",
    "PARTIALLY_VERIFIED": "Partially verified",
    "NOT_VERIFIED": "Not verified in current environment",
    "UNAVAILABLE_IN_CURRENT_ENVIRONMENT": "Unavailable in current environment",
    "NOT_TESTED": "Not tested",
}

VERSION_POLICY_LIMITATION = (
    "This environment cannot prove that a tested browser satisfies the "
    "latest-2-stable version policy; the policy is recorded against the UAT date."
)

BRANDED_BROWSER_SCOPE: list[dict[str, Any]] = [
    {
        "browser": "Google Chrome",
        "required_version_policy": "Latest 2 stable versions at the UAT date",
        "required_scope": "Latest 2 stable versions at the UAT date",
        "required_platforms": ["Windows 10/11", "macOS 13+", "Android 12+"],
        "platforms": "Windows 10/11, macOS 13+, Android 12+",
        "verification_state": "NOT_VERIFIED",
        "verification_state_label": "Not verified in current environment",
        "actual_tested_browser_version": None,
        "actual_tested_platform": None,
        "actual_verified_environments": [],
        "evidence_source": "none",
        "engineering_signals": [
            "Chromium engine evidence available as an engineering relationship",
        ],
        "limitations": [
            "Chromium engine evidence is not equivalent to branded Chrome UAT",
            "Desktop Chromium emulation does not equal real Android Chrome verification",
            VERSION_POLICY_LIMITATION,
        ],
        "related_engine": "chromium",
    },
    {
        "browser": "Microsoft Edge",
        "required_version_policy": "Latest 2 stable versions at the UAT date",
        "required_scope": "Latest 2 stable versions at the UAT date",
        "required_platforms": ["Windows 10/11"],
        "platforms": "Windows 10/11",
        "verification_state": "NOT_VERIFIED",
        "verification_state_label": "Not verified in current environment",
        "actual_tested_browser_version": None,
        "actual_tested_platform": None,
        "actual_verified_environments": [],
        "evidence_source": "none",
        "engineering_signals": [
            "Shared Chromium ancestry is an engineering relationship only",
        ],
        "limitations": [
            "Chromium engine evidence does not verify branded Edge",
            VERSION_POLICY_LIMITATION,
        ],
        "related_engine": "chromium",
    },
    {
        "browser": "Apple Safari",
        "required_version_policy": "Safari 16.4 and above",
        "required_scope": "Safari 16.4 and above",
        "required_platforms": ["macOS 13+", "iOS 16+"],
        "platforms": "macOS 13+, iOS 16+",
        "verification_state": "NOT_VERIFIED",
        "verification_state_label": "Not verified in current environment",
        "actual_tested_browser_version": None,
        "actual_tested_platform": None,
        "actual_verified_environments": [],
        "evidence_source": "none",
        "engineering_signals": [
            "WebKit engine evidence available as an engineering relationship",
        ],
        "limitations": [
            "WebKit engine evidence does not verify real Safari",
            "Requires real Safari on macOS or iOS for verification",
        ],
        "related_engine": "webkit",
    },
]

VERIFICATION_STATE_LABELS: dict[CompatibilityState, str] = {
    "compatible": "Engine compatible",
    "partially_compatible": "Partially verified",
    "incompatible": "Incompatible",
    "not_tested": "Not verified in current environment",
    "inconclusive": "Inconclusive",
    "unavailable": "Not verified in current environment",
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
    status_labels = {state: VERIFICATION_STATE_LABELS[state] for state in VERIFICATION_STATE_LABELS}
    engine_coverage = []
    for engine in selected_profile.engines:
        engine_pages = [row for row in matrix if row["engines"].get(engine) not in (None,)]
        tested_count = sum(1 for row in engine_pages if row["engines"][engine] != "not_tested")
        engine_coverage.append(
            {
                "engine": engine,
                "label": ENGINE_LABELS[engine],
                "uat_label": ENGINE_UAT_LABELS[engine],
                "tested_pages": tested_count,
                "eligible_pages": len(selected_pages),
                "percentage": (
                    round(tested_count / len(selected_pages) * 100, 1) if selected_pages else 0
                ),
            }
        )
    overall_tested = sum(1 for row in matrix if row["result"] != "not_tested")
    overall_percentage = round(overall_tested / len(matrix) * 100, 1) if matrix else 0

    uat_date = time.strftime("%Y-%m-%d", time.gmtime())
    browser_uat_matrix = _build_browser_uat_matrix(engine_coverage, uat_date=uat_date)

    return {
        "profile_id": selected_profile.profile_id,
        "profile_version": selected_profile.version,
        "browser_engine_tests": True,
        "engines": [
            {
                "engine": engine,
                "label": ENGINE_LABELS[engine],
                "uat_label": ENGINE_UAT_LABELS[engine],
            }
            for engine in selected_profile.engines
        ],
        "viewports": [dict(viewport) for viewport in selected_profile.viewports],
        "eligible_page_count": len(selected_pages),
        "observations": observations,
        "matrix": matrix,
        "status_labels": status_labels,
        "engine_coverage": engine_coverage,
        "browser_uat_matrix": browser_uat_matrix,
        "browser_uat": {
            "scope_locked": True,
            "uat_date": uat_date,
            "verification_state_labels": dict(UAT_VERIFICATION_STATE_LABELS),
            "matrix": browser_uat_matrix,
            "completion": browser_uat_completion(browser_uat_matrix),
        },
        "summary": {
            "tested_page_count": overall_tested,
            "eligible_page_count": len(matrix),
            "compatibility_percentage": overall_percentage,
        },
        "limitations": [
            ("Results reflect Playwright engine-level evidence, not branded browser verification."),
            (
                "Chromium engine evidence is indicative of Chrome/Edge "
                "compatibility but is not a substitute for branded "
                "Chrome or Edge channel testing."
            ),
            (
                "WebKit engine evidence is an internal engineering "
                "signal only — it does not constitute Safari "
                "verification without real Safari/macOS/iOS "
                "infrastructure."
            ),
            (
                "Firefox engine evidence reflects the Playwright "
                "Firefox build, not an end-user Firefox installation."
            ),
            ("Only pages and viewports explicitly listed as tested are covered."),
            (
                "Performance variation is not incompatibility "
                "unless an approved threshold is crossed."
            ),
        ],
    }


def _build_browser_uat_matrix(
    engine_coverage: list[dict[str, Any]],
    *,
    uat_date: str | None = None,
) -> list[dict[str, Any]]:
    """Build the customer-facing branded Browser UAT matrix.

    Branded page counts stay at zero unless an actual branded browser/platform
    was tested: engine execution is recorded only as an engineering signal and
    is never promoted to branded verification.
    """
    engine_map = {item["engine"]: item for item in engine_coverage}
    result = []
    for entry in BRANDED_BROWSER_SCOPE:
        engine = entry["related_engine"]
        eng = engine_map.get(engine)
        has_engine_evidence = bool(eng and eng["tested_pages"] > 0)
        eligible = int(eng["eligible_pages"]) if eng else 0
        state = str(entry["verification_state"])
        result.append(
            {
                "browser": entry["browser"],
                "required_version_policy": entry["required_version_policy"],
                "required_scope": entry["required_scope"],
                "required_platforms": list(entry["required_platforms"]),
                "platforms": entry["platforms"],
                "uat_date": uat_date,
                "actual_tested_browser_version": entry["actual_tested_browser_version"],
                "actual_tested_platform": entry["actual_tested_platform"],
                "verification_state": state,
                "verification_state_label": UAT_VERIFICATION_STATE_LABELS.get(state, state),
                "actual_verified_environments": list(entry["actual_verified_environments"]),
                # Branded page accounting: nothing is counted as passed unless a
                # branded browser actually ran; the required scope stays not-tested.
                "page_coverage": {
                    "eligible_pages": eligible,
                    "passed_pages": 0,
                    "partial_pages": 0,
                    "failed_pages": 0,
                    "unavailable_pages": 0,
                    "not_tested_pages": eligible,
                },
                "evidence_source": ("engineering_engine_signal" if has_engine_evidence else "none"),
                "engineering_signals": (
                    list(entry["engineering_signals"]) if has_engine_evidence else []
                ),
                "limitations": list(entry["limitations"]),
                "related_engine": engine,
                "engine_tested_pages": (eng["tested_pages"] if eng else 0),
                "engine_eligible_pages": eligible,
            }
        )
    return result


def browser_uat_completion(matrix: list[dict[str, Any]]) -> dict[str, Any]:
    """Independent Browser-UAT completeness status for the locked branded scope.

    Browser UAT completeness is reported separately from website-analysis
    completeness: an unavailable branded environment never blocks report
    delivery, and an unverified mandatory environment is never counted as
    passed or hidden.
    """
    states = [str(item.get("verification_state")) for item in matrix]
    verified = sum(state == "VERIFIED" for state in states)
    partially = sum(state == "PARTIALLY_VERIFIED" for state in states)
    if matrix and verified == len(matrix):
        status = "complete"
    elif verified or partially:
        status = "partially_verified"
    else:
        status = "not_verified"
    return {
        "status": status,
        "required_browser_count": len(matrix),
        "verified_browser_count": verified,
        "partially_verified_browser_count": partially,
        "unverified_browsers": [
            item["browser"]
            for item in matrix
            if str(item.get("verification_state")) not in {"VERIFIED"}
        ],
        "statement": (
            "All mandatory branded browsers were verified."
            if status == "complete"
            else (
                "Mandatory branded-browser UAT environments were not verified in "
                "the current environment. Engine evidence is retained as an "
                "engineering signal only."
            )
        ),
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
