"""M3 responsive-assertion contract: real-browser proof.

Runs the actual shared JS module (app/services/responsive_assertions.js)
against real Chromium with crafted HTML fixtures that each isolate one
problem category. This is the strongest evidence the assertion logic is
correct -- Python-side wiring tests alone would only prove data threads
through correctly, not that the DOM logic detects real bugs.

Skips cleanly (does not fail) when no Chromium executable is installed --
CI does not currently install Playwright browsers for the Python suite, only
the worker Docker image has them. Run `python -m playwright install
chromium` locally to exercise this file.
"""

from pathlib import Path

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import Error, sync_playwright  # noqa: E402

JS_SOURCE = (
    Path(__file__).parent.parent.parent
    / "apps"
    / "api"
    / "app"
    / "services"
    / "responsive_assertions.js"
).read_text(encoding="utf-8")

VIEWPORT = ("mobile_portrait", 390, 844)


@pytest.fixture(scope="module")
def chromium_browser():
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True)
        except Error as exception:
            pytest.skip(f"Real Chromium is not installed locally: {exception}")
            return
        try:
            yield browser
        finally:
            browser.close()


@pytest.fixture
def evaluate_html(chromium_browser):
    def _run(html: str) -> dict:
        page = chromium_browser.new_page(viewport={"width": VIEWPORT[1], "height": VIEWPORT[2]})
        try:
            page.set_content(html)
            return page.evaluate(JS_SOURCE, list(VIEWPORT))
        finally:
            page.close()

    return _run


@pytest.fixture
def evaluate_html_at_viewports(chromium_browser):
    # For the 5th check (compute_responsive_navigation_adapts,
    # browser_compatibility.py) -- unlike every other assertion, it needs
    # the SAME page evaluated at Desktop and Mobile width to compare, not
    # one fixed viewport.
    def _run(html: str) -> dict[str, dict]:
        page = chromium_browser.new_page()
        try:
            page.set_content(html)
            results = {}
            for name, width, height in [("Desktop", 1440, 900), ("Mobile", 390, 844)]:
                page.set_viewport_size({"width": width, "height": height})
                results[name] = page.evaluate(JS_SOURCE, [name, width, height])
            return results
        finally:
            page.close()

    return _run


CLEAN_PAGE = """
<html><body style="margin:0">
  <nav aria-label="Main navigation">Home</nav>
  <main>
    <h1>Title</h1>
    <button style="width:48px;height:48px;display:block">Click</button>
  </main>
</body></html>
"""

OVERFLOW_PAGE = """
<html><body style="margin:0">
  <div style="width:3000px;height:20px">This element is much wider than the viewport.</div>
</body></html>
"""

SMALL_TAP_TARGETS_PAGE = """
<html><body style="margin:0">
  <button style="position:absolute;top:0;left:0;width:10px;height:10px;padding:0;border:0">
    A
  </button>
  <button style="position:absolute;top:0;left:15px;width:10px;height:10px;padding:0;border:0">
    B
  </button>
</body></html>
"""

OVERLAPPING_ELEMENTS_PAGE = """
<html><body style="margin:0">
  <h1 style="position:absolute;top:0;left:0;width:200px;height:50px">Title</h1>
  <button style="position:absolute;top:10px;left:10px;width:100px;height:30px">Click</button>
</body></html>
"""


class TestCleanPageHasNoFindings:
    def test_no_problems_reported(self, evaluate_html) -> None:
        result = evaluate_html(CLEAN_PAGE)

        assert result["horizontal_overflow"] is False
        assert result["critical_elements_outside_viewport"] == 0
        assert result["overlapping_elements"] == 0
        assert result["small_tap_targets"] == 0
        assert result["viewport_problems"] == []


class TestHorizontalOverflowIsDetected:
    def test_wide_content_is_flagged(self, evaluate_html) -> None:
        result = evaluate_html(OVERFLOW_PAGE)

        assert result["horizontal_overflow"] is True
        assert any("horizontal" in problem.lower() for problem in result["viewport_problems"])


class TestSmallTapTargetsAreDetected:
    def test_undersized_adjacent_buttons_are_flagged(self, evaluate_html) -> None:
        result = evaluate_html(SMALL_TAP_TARGETS_PAGE)

        assert result["small_tap_targets"] == 2
        assert len(result["tap_target_samples"]) == 2
        assert all(sample["width"] == 10 for sample in result["tap_target_samples"])
        # Close together -> no spacing exception -> a real problem.
        assert any(not sample["spacing_exception"] for sample in result["tap_target_samples"])
        assert any("tap-target" in problem.lower() for problem in result["viewport_problems"])


class TestOverlappingElementsAreDetected:
    def test_visually_colliding_elements_are_flagged(self, evaluate_html) -> None:
        result = evaluate_html(OVERLAPPING_ELEMENTS_PAGE)

        assert result["overlapping_elements"] >= 1
        assert any("overlap" in problem.lower() for problem in result["viewport_problems"])


ADAPTING_NAV_PAGE = """
<html><head><style>
  nav { display: flex; gap: 8px; }
  .hamburger { display: none; width: 32px; height: 32px; }
  @media (max-width: 500px) {
    nav a.nav-link { display: none; }
    .hamburger { display: block; }
  }
</style></head><body style="margin:0">
  <nav aria-label="Main navigation">
    <a class="nav-link" href="/">Home</a>
    <a class="nav-link" href="/about">About</a>
    <a class="nav-link" href="/contact">Contact</a>
    <button class="hamburger" aria-expanded="false" aria-label="Toggle menu">menu</button>
  </nav>
  <main><h1>Fixture</h1></main>
</body></html>
"""

STATIC_NAV_PAGE = """
<html><head><style>
  nav { display: flex; gap: 8px; white-space: nowrap; }
</style></head><body style="margin:0">
  <nav aria-label="Main navigation">
    <a class="nav-link" href="/">Home</a>
    <a class="nav-link" href="/about">About</a>
    <a class="nav-link" href="/contact">Contact</a>
  </nav>
  <main><h1>Fixture</h1></main>
</body></html>
"""


class TestNavigationAdaptsRawFields:
    """The 5th M3 check's raw per-viewport data
    (compute_responsive_navigation_adapts consumes these two fields --
    see browser_compatibility.py for the actual cross-viewport comparison,
    which is Python-side and covered by plain-dict unit tests instead)."""

    def test_an_adapting_nav_loses_items_and_gains_a_toggle_at_mobile(
        self, evaluate_html_at_viewports
    ) -> None:
        results = evaluate_html_at_viewports(ADAPTING_NAV_PAGE)

        assert results["Desktop"]["nav_visible_item_count"] == 3
        assert results["Desktop"]["has_navigation_toggle"] is False
        assert results["Mobile"]["nav_visible_item_count"] == 0
        assert results["Mobile"]["has_navigation_toggle"] is True

    def test_a_static_nav_reports_identical_items_at_both_viewports(
        self, evaluate_html_at_viewports
    ) -> None:
        results = evaluate_html_at_viewports(STATIC_NAV_PAGE)

        assert results["Desktop"]["nav_visible_item_count"] == 3
        assert results["Mobile"]["nav_visible_item_count"] == 3
        assert results["Desktop"]["has_navigation_toggle"] is False
        assert results["Mobile"]["has_navigation_toggle"] is False


class TestResultShapeMatchesTheExistingContract:
    def test_result_includes_the_load_bearing_field_names(self, evaluate_html) -> None:
        # horizontal_overflow and tap_target_samples are consumed by
        # worker_app/analysis/diagnostics.py -- renaming them would silently
        # break site-diagnostics findings.
        result = evaluate_html(CLEAN_PAGE)

        for field in (
            "name",
            "width",
            "height",
            "status",
            "horizontal_overflow",
            "tap_target_samples",
            "viewport_problems",
        ):
            assert field in result
        assert result["name"] == VIEWPORT[0]
        assert result["width"] == VIEWPORT[1]
        assert result["height"] == VIEWPORT[2]
