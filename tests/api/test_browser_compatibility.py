import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from app.services import browser_compatibility
from app.services.browser_compatibility import (
    DESKTOP_VIEWPORT,
    CompatibilityProfile,
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
