"""M3: evaluate_responsive_assertions wiring, and the 5th check --
compute_responsive_navigation_adapts.

The real-browser proof of the assertion logic itself lives in
tests/api/test_responsive_assertions.py (including a live Chromium repro of
nav_visible_item_count/has_navigation_toggle across a real adapting nav and a
real static one). This file tests the Python-side glue -- args threaded
through correctly, the failure fallback, and the cross-viewport comparison
-- with fake page objects and plain dicts, no real browser required (runs
everywhere, including CI).
"""

from app.services.browser_compatibility import (
    compute_responsive_navigation_adapts,
    evaluate_responsive_assertions,
)
from playwright.sync_api import Error
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError


class _FakePage:
    def __init__(self, *, result: dict | None = None, raises: Exception | None = None) -> None:
        self.result = result
        self.raises = raises
        self.calls: list[tuple[str, list]] = []

    def evaluate(self, source: str, arg: list) -> dict:
        self.calls.append((source, arg))
        if self.raises is not None:
            raise self.raises
        return self.result


class TestArgumentThreading:
    def test_viewport_name_width_height_are_passed_positionally(self) -> None:
        page = _FakePage(result={"horizontal_overflow": False, "viewport_problems": []})

        evaluate_responsive_assertions(page, {"name": "Mobile", "width": 390, "height": 844})

        assert len(page.calls) == 1
        _source, arg = page.calls[0]
        assert arg == ["Mobile", 390, 844]

    def test_missing_viewport_name_falls_back_to_a_default_label(self) -> None:
        page = _FakePage(result={"horizontal_overflow": False, "viewport_problems": []})

        evaluate_responsive_assertions(page, {"width": 1440, "height": 900})

        _source, arg = page.calls[0]
        assert arg[0] == "viewport"

    def test_successful_result_passes_through_unchanged(self) -> None:
        canned_result = {
            "horizontal_overflow": True,
            "viewport_problems": ["Page content overflows the viewport horizontally."],
            "small_tap_targets": 3,
        }
        page = _FakePage(result=canned_result)

        result = evaluate_responsive_assertions(
            page, {"name": "Mobile", "width": 390, "height": 844}
        )

        assert result == canned_result


class TestFailureFallback:
    def test_a_playwright_error_falls_back_to_no_fabricated_findings(self) -> None:
        # The page loaded (navigation already succeeded by this point in the
        # caller), but the assertion script itself failed. Must not fabricate
        # a false overflow=True or invent problems that were never observed.
        page = _FakePage(raises=Error("evaluate: execution context was destroyed"))

        result = evaluate_responsive_assertions(
            page, {"name": "Mobile", "width": 390, "height": 844}
        )

        assert result == {"horizontal_overflow": False, "viewport_problems": []}

    def test_a_timeout_also_falls_back_safely(self) -> None:
        page = _FakePage(raises=PlaywrightTimeoutError("Timeout 5000ms exceeded"))

        result = evaluate_responsive_assertions(
            page, {"name": "Mobile", "width": 390, "height": 844}
        )

        assert result == {"horizontal_overflow": False, "viewport_problems": []}

    def test_an_unrelated_exception_is_not_swallowed(self) -> None:
        # Only Playwright's own Error/TimeoutError are treated as an
        # assertion-script failure; anything else is a real bug and must
        # propagate, not be silently hidden behind a clean-looking fallback.
        import pytest

        page = _FakePage(raises=ValueError("something else entirely"))

        with pytest.raises(ValueError):
            evaluate_responsive_assertions(page, {"name": "Mobile", "width": 390, "height": 844})


def _observation(viewport_name: str, **fields: object) -> dict:
    return {"viewport": {"name": viewport_name}, **fields}


class TestComputeResponsiveNavigationAdapts:
    def test_a_toggle_appearing_at_mobile_counts_as_adapting(self) -> None:
        observations = [
            _observation("Desktop", nav_visible_item_count=3, has_navigation_toggle=False),
            _observation("Mobile", nav_visible_item_count=0, has_navigation_toggle=True),
        ]

        assert compute_responsive_navigation_adapts(observations) is True

    def test_fewer_visible_items_at_mobile_counts_as_adapting_even_without_a_toggle(self) -> None:
        # A collapsed accordion-style nav with no dedicated hamburger
        # control still genuinely adapts if it hides items at mobile.
        observations = [
            _observation("Desktop", nav_visible_item_count=5, has_navigation_toggle=False),
            _observation("Mobile", nav_visible_item_count=2, has_navigation_toggle=False),
        ]

        assert compute_responsive_navigation_adapts(observations) is True

    def test_identical_items_and_no_toggle_is_not_adapting(self) -> None:
        # A static nav that just overflows/shrinks visually -- the existing
        # horizontal_overflow/overlapping_elements checks already flag that
        # separately; this must not also claim it "adapted".
        observations = [
            _observation("Desktop", nav_visible_item_count=3, has_navigation_toggle=False),
            _observation("Mobile", nav_visible_item_count=3, has_navigation_toggle=False),
        ]

        assert compute_responsive_navigation_adapts(observations) is False

    def test_more_items_visible_at_mobile_than_desktop_is_not_adapting(self) -> None:
        # An unusual case (e.g. a desktop mega-menu that's collapsed by
        # default) -- more visible at mobile is not navigation "adapting"
        # in the sense this check means, only fewer/toggle counts.
        observations = [
            _observation("Desktop", nav_visible_item_count=2, has_navigation_toggle=False),
            _observation("Mobile", nav_visible_item_count=4, has_navigation_toggle=False),
        ]

        assert compute_responsive_navigation_adapts(observations) is False

    def test_missing_desktop_viewport_is_inconclusive_not_fabricated(self) -> None:
        observations = [
            _observation("Mobile", nav_visible_item_count=0, has_navigation_toggle=True)
        ]

        assert compute_responsive_navigation_adapts(observations) is None

    def test_missing_mobile_viewport_is_inconclusive_not_fabricated(self) -> None:
        observations = [
            _observation("Desktop", nav_visible_item_count=3, has_navigation_toggle=False)
        ]

        assert compute_responsive_navigation_adapts(observations) is None

    def test_a_failed_assertion_script_at_one_viewport_is_inconclusive(self) -> None:
        # evaluate_responsive_assertions's failure fallback omits
        # nav_visible_item_count/has_navigation_toggle entirely -- must
        # never be treated as "0 items" (which would look like adaptation).
        observations = [
            _observation("Desktop", nav_visible_item_count=3, has_navigation_toggle=False),
            _observation("Mobile"),  # assertion script failed at this viewport
        ]

        assert compute_responsive_navigation_adapts(observations) is None

    def test_empty_observations_is_inconclusive(self) -> None:
        assert compute_responsive_navigation_adapts([]) is None
