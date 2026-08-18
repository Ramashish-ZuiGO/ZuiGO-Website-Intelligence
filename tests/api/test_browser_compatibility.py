import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from app.services import browser_compatibility
from app.services.browser_compatibility import (
    BRANDED_BROWSER_SCOPE,
    DESKTOP_VIEWPORT,
    ENGINE_UAT_LABELS,
    VERIFICATION_STATE_LABELS,
    CompatibilityProfile,
    _build_browser_uat_matrix,
    browser_uat_completion,
    classify_compatibility,
    run_compatibility_analysis,
    select_compatibility_pages,
)
from app.services.report_delivery import _browser_finding_payload


def _pages(count: int) -> list[dict[str, object]]:
    return [
        {
            "url": f"https://fixture.test/page-{index}",
            "title": f"Page {index}",
            "page_type": "home" if index == 0 else "content",
            "analysis_status": "analysed",
            "http_status": 200,
        }
        for index in range(count)
    ]


def test_all_pages_at_or_below_fifty_and_deterministic_large_sample() -> None:
    profile = CompatibilityProfile(representative_sample_size=12)
    assert len(select_compatibility_pages(_pages(50), profile)) == 50
    first = select_compatibility_pages(_pages(80), profile)
    second = select_compatibility_pages(reversed(_pages(80)), profile)
    assert [item["url"] for item in first] == [item["url"] for item in second]
    assert len(first) == 12
    assert first[0]["url"] == "https://fixture.test/page-0"


def test_critical_pages_never_overflow_the_declared_sample_size() -> None:
    pages = _pages(5)
    for page in pages:
        page["critical"] = True
    selected = select_compatibility_pages(
        pages,
        CompatibilityProfile(
            all_pages_limit=1,
            representative_sample_size=1,
        ),
    )
    assert [item["url"] for item in selected] == ["https://fixture.test/page-0"]


def test_all_three_engines_and_both_viewports_execute_without_network() -> None:
    calls: list[tuple[str, str, str]] = []

    def runner(engine, page, viewport, _profile):
        calls.append((engine, page["url"], viewport["name"]))
        incompatible = engine == "webkit" and page["url"].endswith("page-1")
        return {
            "state": "tested",
            "navigation_success": True,
            "render_success": True,
            "critical_element_available": not incompatible,
            "interaction_failures": ["Unavailable control"] if incompatible else [],
            "console_errors": [],
            "javascript_errors": [],
            "failed_resources": [],
            "layout_overflow": False,
            "viewport_problems": [],
            "accessibility_differences": [],
            "duration_ms": 100,
        }

    result = run_compatibility_analysis(_pages(2), runner=runner)
    assert len(calls) == 12
    assert {item[0] for item in calls} == {"chromium", "firefox", "webkit"}
    assert {item[2] for item in calls} == {"Desktop", "Mobile"}
    incompatible = next(item for item in result["matrix"] if item["page_url"].endswith("page-1"))
    assert incompatible["engines"]["webkit"] == "incompatible"
    assert incompatible["result"] == "incompatible"


def test_responsive_navigation_adapts_is_computed_per_engine_in_the_matrix() -> None:
    # The 5th M3 check (docs/DEVICE_OS_BROWSER_QA_PLAN.md M3): wired through
    # run_compatibility_analysis's real per-page-per-engine matrix, not just
    # unit-tested in isolation. chromium's nav collapses at Mobile; firefox's
    # doesn't -- must be tracked independently per engine, matching how
    # `engines` state already is.
    def runner(engine, _page, viewport, _profile):
        adapting = engine == "chromium"
        if viewport["name"] == "Desktop":
            nav_count, toggle = 3, False
        else:
            nav_count, toggle = (0, True) if adapting else (3, False)
        return {
            "state": "tested",
            "navigation_success": True,
            "render_success": True,
            "critical_element_available": True,
            "interaction_failures": [],
            "console_errors": [],
            "javascript_errors": [],
            "failed_resources": [],
            "layout_overflow": False,
            "viewport_problems": [],
            "nav_visible_item_count": nav_count,
            "has_navigation_toggle": toggle,
            "accessibility_differences": [],
            "duration_ms": 100,
        }

    result = run_compatibility_analysis(_pages(1), runner=runner)

    adapts = result["matrix"][0]["responsive_navigation_adapts"]
    assert adapts["chromium"] is True
    assert adapts["firefox"] is False
    assert adapts["webkit"] is False


def test_default_runner_reuses_one_playwright_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, str]] = []
    closed: list[bool] = []

    class LocalReusableRunner:
        def __call__(self, engine, page, viewport, _profile):
            calls.append((engine, page["url"], viewport["name"]))
            return {
                "state": "tested",
                "navigation_success": True,
                "render_success": True,
                "critical_element_available": True,
                "duration_ms": 10,
            }

        def close(self) -> None:
            closed.append(True)

    monkeypatch.setattr(
        browser_compatibility,
        "_ReusablePlaywrightPageRunner",
        LocalReusableRunner,
    )
    result = run_compatibility_analysis(_pages(2))
    assert len(calls) == 12
    assert len(result["observations"]) == 12
    assert closed == [True]


def test_reusable_runner_bounds_each_engine_launch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launch_options: list[dict[str, object]] = []

    class LocalBrowser:
        def close(self) -> None:
            return None

    class LocalBrowserType:
        def launch(self, **kwargs):
            launch_options.append(kwargs)
            return LocalBrowser()

    runner = browser_compatibility._ReusablePlaywrightPageRunner()
    runner._playwright = SimpleNamespace(chromium=LocalBrowserType())
    monkeypatch.setattr(
        browser_compatibility,
        "_run_playwright_observation",
        lambda *_args: {"state": "tested"},
    )
    profile = CompatibilityProfile(navigation_timeout_ms=12_345)
    try:
        assert runner("chromium", _pages(1)[0], DESKTOP_VIEWPORT, profile) == {"state": "tested"}
    finally:
        runner.close()
    assert launch_options == [{"headless": True, "timeout": 12_345}]


def test_compatibility_claims_require_deterministic_failure_and_working_comparison() -> None:
    working = {
        "state": "tested",
        "navigation_success": True,
        "render_success": True,
        "critical_element_available": True,
        "duration_ms": 100,
    }
    failed = {
        "state": "tested",
        "navigation_success": True,
        "render_success": True,
        "critical_element_available": False,
        "duration_ms": 100,
    }
    assert classify_compatibility([working, failed]) == "incompatible"
    assert classify_compatibility([failed]) == "inconclusive"
    assert classify_compatibility([{**working, "duration_ms": 140}, working]) == (
        "partially_compatible"
    )
    assert classify_compatibility([]) == "not_tested"
    assert classify_compatibility([{"state": "unavailable"}]) == "unavailable"


def test_browser_report_finding_preserves_exact_affected_url_and_engines() -> None:
    artifact_id = uuid.uuid4()
    finding = _browser_finding_payload(
        {
            "page_url": "https://fixture.test/checkout",
            "page_title": "Checkout",
            "result": "incompatible",
            "engines": {
                "chromium": "compatible",
                "firefox": "compatible",
                "webkit": "incompatible",
            },
        },
        SimpleNamespace(
            artifact_id=artifact_id,
            artifact_metadata={"profile_version": "1.0.0"},
            created_at=datetime.now(UTC),
            evidence_references=[
                {
                    "evidence_type": "browser_compatibility_evidence",
                    "evidence_id": str(artifact_id),
                }
            ],
        ),
    )
    occurrence = finding["exact_occurrences"][0]
    assert occurrence["normalized_url"] == "https://fixture.test/checkout"
    assert finding["affected_browser_engines"] == ["WebKit engine"]
    assert finding["working_browser_engines"] == [
        "Chromium engine",
        "Firefox engine",
    ]


def test_uat_labels_do_not_overclaim_branded_browsers() -> None:
    assert "Opera" not in ENGINE_UAT_LABELS["chromium"]
    assert "Safari" not in ENGINE_UAT_LABELS["webkit"]
    assert "Chrome" not in ENGINE_UAT_LABELS["chromium"]
    assert ENGINE_UAT_LABELS["chromium"] == "Chromium engine"
    assert ENGINE_UAT_LABELS["firefox"] == "Firefox engine"
    assert "internal signal" in ENGINE_UAT_LABELS["webkit"]


def test_verification_state_labels_cover_all_compatibility_states() -> None:
    assert VERIFICATION_STATE_LABELS["compatible"] == "Engine compatible"
    assert VERIFICATION_STATE_LABELS["partially_compatible"] == "Partially verified"
    assert VERIFICATION_STATE_LABELS["incompatible"] == "Incompatible"
    assert VERIFICATION_STATE_LABELS["not_tested"] == "Not verified in current environment"
    assert VERIFICATION_STATE_LABELS["inconclusive"] == "Inconclusive"
    assert VERIFICATION_STATE_LABELS["unavailable"] == "Not verified in current environment"


def test_run_compatibility_analysis_output_includes_uat_fields() -> None:
    def runner(engine, page, viewport, _profile):
        return {
            "state": "tested",
            "navigation_success": True,
            "render_success": True,
            "critical_element_available": True,
            "duration_ms": 50,
        }

    result = run_compatibility_analysis(_pages(1), runner=runner)
    assert "status_labels" in result
    assert result["status_labels"]["compatible"] == "Engine compatible"
    assert "engine_coverage" in result
    assert len(result["engine_coverage"]) == 3
    for entry in result["engine_coverage"]:
        assert "uat_label" in entry
    assert "summary" in result
    assert result["summary"]["tested_page_count"] == 1
    for engine_info in result["engines"]:
        assert "uat_label" in engine_info
    assert "browser_uat_matrix" in result
    uat_matrix = result["browser_uat_matrix"]
    assert len(uat_matrix) == 3
    browser_names = [entry["browser"] for entry in uat_matrix]
    assert "Google Chrome" in browser_names
    assert "Microsoft Edge" in browser_names
    assert "Apple Safari" in browser_names
    for entry in uat_matrix:
        assert "verification_state" in entry
        assert "limitations" in entry
        assert "engineering_signals" in entry
        assert "actual_verified_environments" in entry
        assert entry["verification_state"] == "NOT_VERIFIED"
        assert isinstance(entry["limitations"], list)
        assert isinstance(entry["engineering_signals"], list)
        assert isinstance(entry["actual_verified_environments"], list)


def test_branded_browser_scope_does_not_include_opera() -> None:
    browser_names = [entry["browser"] for entry in BRANDED_BROWSER_SCOPE]
    assert "Opera" not in browser_names
    for entry in BRANDED_BROWSER_SCOPE:
        assert "Opera" not in entry["browser"]
        assert "Opera" not in entry.get("platforms", "")


def test_webkit_never_represented_as_safari_verification() -> None:
    assert "Safari" not in ENGINE_UAT_LABELS["webkit"]
    assert "internal signal" in ENGINE_UAT_LABELS["webkit"]
    safari_entry = next(e for e in BRANDED_BROWSER_SCOPE if e["browser"] == "Apple Safari")
    assert safari_entry["verification_state"] == "NOT_VERIFIED"
    assert safari_entry["actual_verified_environments"] == []
    assert any("WebKit" in s for s in safari_entry["engineering_signals"])
    assert any("real Safari" in lim for lim in safari_entry["limitations"])


def test_tablet_form_factors_are_documented_without_growing_the_matrix() -> None:
    """iPad/Android-tablet are explicitly named (M1 decision, 2026-08-14) but
    tracked within the existing 3-browser structure, not split into separate
    verification rows -- that split is deferred to M4/M5 design."""
    assert [entry["browser"] for entry in BRANDED_BROWSER_SCOPE] == [
        "Google Chrome",
        "Microsoft Edge",
        "Apple Safari",
    ]

    safari_entry = next(e for e in BRANDED_BROWSER_SCOPE if e["browser"] == "Apple Safari")
    assert "iPadOS 16+" in safari_entry["required_platforms"]
    assert any("iPad" in lim for lim in safari_entry["limitations"])

    chrome_entry = next(e for e in BRANDED_BROWSER_SCOPE if e["browser"] == "Google Chrome")
    assert "tablet" in chrome_entry["platforms"].lower()
    assert any("tablet" in lim.lower() for lim in chrome_entry["limitations"])

    # Neither entry claims tablet verification just because it's now named.
    assert safari_entry["verification_state"] == "NOT_VERIFIED"
    assert chrome_entry["verification_state"] == "NOT_VERIFIED"


def test_chromium_does_not_automatically_verify_edge() -> None:
    assert "Edge" not in ENGINE_UAT_LABELS["chromium"]
    chrome_entry = next(e for e in BRANDED_BROWSER_SCOPE if e["browser"] == "Google Chrome")
    edge_entry = next(e for e in BRANDED_BROWSER_SCOPE if e["browser"] == "Microsoft Edge")
    assert chrome_entry["related_engine"] == "chromium"
    assert edge_entry["related_engine"] == "chromium"
    assert chrome_entry["verification_state"] == "NOT_VERIFIED"
    assert edge_entry["verification_state"] == "NOT_VERIFIED"
    assert chrome_entry["actual_verified_environments"] == []
    assert edge_entry["actual_verified_environments"] == []


# --- Blocker 5 regression tests: engine → branded UAT overclaim prevention ---


def test_chromium_engine_cannot_mark_chrome_verified() -> None:
    engine_coverage = [
        {
            "engine": "chromium",
            "tested_pages": 10,
            "eligible_pages": 10,
            "uat_label": "Chromium engine",
        },
        {
            "engine": "firefox",
            "tested_pages": 0,
            "eligible_pages": 10,
            "uat_label": "Firefox engine",
        },
        {"engine": "webkit", "tested_pages": 0, "eligible_pages": 10, "uat_label": "WebKit engine"},
    ]
    matrix = _build_browser_uat_matrix(engine_coverage)
    chrome = next(e for e in matrix if e["browser"] == "Google Chrome")
    assert chrome["verification_state"] == "NOT_VERIFIED"
    assert chrome["actual_verified_environments"] == []
    assert len(chrome["engineering_signals"]) > 0
    assert any("Chromium" in s for s in chrome["engineering_signals"])


def test_chromium_engine_cannot_mark_edge_verified() -> None:
    engine_coverage = [
        {
            "engine": "chromium",
            "tested_pages": 10,
            "eligible_pages": 10,
            "uat_label": "Chromium engine",
        },
        {
            "engine": "firefox",
            "tested_pages": 0,
            "eligible_pages": 10,
            "uat_label": "Firefox engine",
        },
        {"engine": "webkit", "tested_pages": 0, "eligible_pages": 10, "uat_label": "WebKit engine"},
    ]
    matrix = _build_browser_uat_matrix(engine_coverage)
    edge = next(e for e in matrix if e["browser"] == "Microsoft Edge")
    assert edge["verification_state"] == "NOT_VERIFIED"
    assert edge["actual_verified_environments"] == []


def test_webkit_engine_cannot_mark_safari_verified() -> None:
    engine_coverage = [
        {
            "engine": "chromium",
            "tested_pages": 0,
            "eligible_pages": 10,
            "uat_label": "Chromium engine",
        },
        {
            "engine": "firefox",
            "tested_pages": 0,
            "eligible_pages": 10,
            "uat_label": "Firefox engine",
        },
        {
            "engine": "webkit",
            "tested_pages": 10,
            "eligible_pages": 10,
            "uat_label": "WebKit engine",
        },
    ]
    matrix = _build_browser_uat_matrix(engine_coverage)
    safari = next(e for e in matrix if e["browser"] == "Apple Safari")
    assert safari["verification_state"] == "NOT_VERIFIED"
    assert safari["actual_verified_environments"] == []
    assert len(safari["engineering_signals"]) > 0
    assert any("WebKit" in s for s in safari["engineering_signals"])


def test_engine_failure_does_not_fabricate_branded_incompatibility() -> None:
    engine_coverage = [
        {
            "engine": "chromium",
            "tested_pages": 0,
            "eligible_pages": 0,
            "uat_label": "Chromium engine",
        },
        {
            "engine": "firefox",
            "tested_pages": 0,
            "eligible_pages": 0,
            "uat_label": "Firefox engine",
        },
        {"engine": "webkit", "tested_pages": 0, "eligible_pages": 0, "uat_label": "WebKit engine"},
    ]
    matrix = _build_browser_uat_matrix(engine_coverage)
    for entry in matrix:
        assert entry["verification_state"] == "NOT_VERIFIED"
        assert entry["actual_verified_environments"] == []
        assert entry["engineering_signals"] == []
        assert "incompatible" not in entry["verification_state"].lower()


def test_opera_is_absent_from_branded_scope() -> None:
    all_browsers = [e["browser"] for e in BRANDED_BROWSER_SCOPE]
    assert "Opera" not in all_browsers
    engine_coverage = [
        {
            "engine": "chromium",
            "tested_pages": 10,
            "eligible_pages": 10,
            "uat_label": "Chromium engine",
        },
        {
            "engine": "firefox",
            "tested_pages": 10,
            "eligible_pages": 10,
            "uat_label": "Firefox engine",
        },
        {
            "engine": "webkit",
            "tested_pages": 10,
            "eligible_pages": 10,
            "uat_label": "WebKit engine",
        },
    ]
    matrix = _build_browser_uat_matrix(engine_coverage)
    matrix_browsers = [e["browser"] for e in matrix]
    assert "Opera" not in matrix_browsers


def test_branded_scope_schema_has_required_separated_fields() -> None:
    required_fields = {
        "browser",
        "required_scope",
        "platforms",
        "verification_state",
        "actual_verified_environments",
        "engineering_signals",
        "limitations",
        "related_engine",
    }
    for entry in BRANDED_BROWSER_SCOPE:
        missing = required_fields - set(entry.keys())
        assert not missing, f"{entry['browser']} missing fields: {missing}"
        assert isinstance(entry["actual_verified_environments"], list)
        assert isinstance(entry["engineering_signals"], list)
        assert isinstance(entry["limitations"], list)
        assert entry["verification_state"] == "NOT_VERIFIED"


def test_uat_matrix_output_schema_matches_separated_model() -> None:
    engine_coverage = [
        {
            "engine": "chromium",
            "tested_pages": 5,
            "eligible_pages": 10,
            "uat_label": "Chromium engine",
        },
        {
            "engine": "firefox",
            "tested_pages": 5,
            "eligible_pages": 10,
            "uat_label": "Firefox engine",
        },
        {"engine": "webkit", "tested_pages": 5, "eligible_pages": 10, "uat_label": "WebKit engine"},
    ]
    matrix = _build_browser_uat_matrix(engine_coverage, uat_date="2026-08-12")
    # Locked-contract mandatory UAT result fields.
    required_output_fields = {
        "browser",
        "required_version_policy",
        "required_scope",
        "required_platforms",
        "platforms",
        "uat_date",
        "actual_tested_browser_version",
        "actual_tested_platform",
        "verification_state",
        "verification_state_label",
        "actual_verified_environments",
        "page_coverage",
        "evidence_source",
        "engineering_signals",
        "limitations",
        "related_engine",
        "engine_tested_pages",
        "engine_eligible_pages",
    }
    for entry in matrix:
        missing = required_output_fields - set(entry.keys())
        assert not missing, f"{entry['browser']} missing output fields: {missing}"
        assert "version_scope" not in entry
        assert "limitation" not in entry
        assert entry["uat_date"] == "2026-08-12"
        # Engine evidence never promotes branded page counts: nothing passes
        # while the branded browser itself was not tested.
        coverage = entry["page_coverage"]
        assert coverage["passed_pages"] == 0
        assert coverage["failed_pages"] == 0
        assert coverage["not_tested_pages"] == coverage["eligible_pages"]
        assert entry["evidence_source"] in {"engineering_engine_signal", "none"}


def test_uat_model_supports_future_real_branded_evidence_without_schema_change() -> None:
    """Safari (or Chrome/Edge) can become VERIFIED in the future by populating
    the existing provider-neutral fields with real branded evidence — no
    canonical schema redesign and no vendor hard-coded into the model."""
    matrix = _build_browser_uat_matrix([], uat_date="2027-01-15")
    for entry in matrix:
        # Fields a future real-browser provider (cloud device farm or
        # Mac/iOS worker) would populate: they exist today and are neutral.
        entry["verification_state"] = "VERIFIED"
        entry["verification_state_label"] = "Verified"
        entry["actual_tested_browser_version"] = "Safari 17.4"
        entry["actual_tested_platform"] = "macOS 14 (real device)"
        entry["actual_verified_environments"] = ["macOS 14 / Safari 17.4"]
        entry["evidence_source"] = "real_branded_browser_provider"
    completion = browser_uat_completion(matrix)
    assert completion["status"] == "complete"
    assert completion["verified_browser_count"] == 3
    assert completion["unverified_browsers"] == []


def test_uncollected_signals_are_omitted_and_disclosed_not_faked_empty() -> None:
    """M10 (docs/REPORT_QUALITY_INITIATIVE.md): interaction_failures,
    accessibility_differences, and screenshot_artifact_reference were
    hardcoded empty in every real engine result -- an empty list reads as
    "checked, nothing found" when no check ever ran. Signals the harness
    does not collect must be absent from per-page results and explicitly
    disclosed at the payload level.
    """

    def runner(engine, page, viewport, _profile):
        del engine, page, viewport
        return {
            "state": "tested",
            "navigation_success": True,
            "render_success": True,
            "critical_element_available": True,
            "console_errors": [],
            "javascript_errors": [],
            "failed_resources": [],
            "layout_overflow": False,
            "viewport_problems": [],
            "duration_ms": 100,
        }

    result = run_compatibility_analysis(_pages(1), runner=runner)

    disclosed = {item["signal"] for item in result["signals_not_collected"]}
    assert disclosed == {
        "interaction_failures",
        "accessibility_differences",
        "screenshot_artifact_reference",
    }
    for entry in result["signals_not_collected"]:
        assert entry["statement"]

    # A result with no interaction/accessibility signal keys must still
    # classify as compatible -- absence means not-checked, not failure.
    row = result["matrix"][0]
    assert row["result"] == "compatible"
