from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_browser_uat_panel_exists_with_required_structure() -> None:
    """Verify the BrowserUatPanel component contains all required UI elements."""
    panel = read("apps/web/src/components/browser-uat/BrowserUatPanel.tsx")

    # Trigger button
    assert "Run real browser check" in panel
    assert "Rerun browser check" in panel
    assert "crypto.randomUUID()" in panel
    assert "idempotencyKey" in panel or "idempotency_key" in panel

    # Polling
    assert "POLL_INTERVAL_MS" in panel
    assert "setInterval" in panel
    assert "clearInterval" in panel

    # Status handling for all terminal states
    for status in ("completed", "partial", "failed", "cancelled", "unavailable"):
        assert f'"{status}"' in panel

    # Pending/running states
    assert '"pending"' in panel
    assert '"running"' in panel

    # Results display
    assert "viewport_results" in panel
    assert "horizontal_overflow" in panel
    assert "overlapping_elements" in panel
    assert "small_tap_targets" in panel
    assert "tap_target_samples" in panel
    assert "critical_elements_outside_viewport" in panel

    # Android lane — no trigger button, informational badge
    assert "Verified by our team on a real device" in panel
    assert "android" in panel.lower()

    # 409 conflict handling
    assert "409" in panel

    # Accessibility
    assert 'role="alert"' in panel
    assert "aria-label" in panel
    assert "aria-expanded" in panel


def test_browser_uat_api_client_covers_all_endpoints() -> None:
    """Verify the API client covers POST, GET status, and GET results."""
    api = read("apps/web/src/lib/browser-uat-api.ts")

    # POST endpoint for starting a check
    assert 'method: "POST"' in api
    assert "idempotency_key" in api

    # GET status endpoint
    assert "status" in api

    # GET results endpoint
    assert "/results" in api

    # Uses the correct base path
    assert "browser-uat/tier0" in api

    # Uses the shared apiRequest function
    assert "apiRequest" in api
    assert "ApiError" in api


def test_browser_uat_types_match_api_contract() -> None:
    """Verify TypeScript types define all required interfaces."""
    types = read("apps/web/src/components/browser-uat/types.ts")

    # Core execution interface
    assert "BrowserUatExecution" in types
    assert "execution_id" in types
    assert "website_id" in types
    assert "analysis_run_id" in types
    assert "lane" in types
    assert "attempt" in types
    assert "requested_at" in types
    assert "started_at" in types
    assert "completed_at" in types

    # Status type
    assert "BrowserUatTier0Status" in types
    for status in (
        "pending",
        "running",
        "completed",
        "partial",
        "failed",
        "cancelled",
        "unavailable",
    ):
        assert f'"{status}"' in types

    # Viewport result interface
    assert "BrowserUatViewportResult" in types
    assert "viewport_name" in types
    assert "viewport_width" in types
    assert "viewport_height" in types
    assert "horizontal_overflow" in types
    assert "critical_elements_outside_viewport" in types
    assert "overlapping_elements" in types
    assert "small_tap_targets" in types
    assert "tap_target_samples" in types

    # Tap target sample interface
    assert "BrowserUatTapTargetSample" in types
    assert "element_type" in types
    assert "accessible_label" in types
    assert "spacing_exception" in types

    # Page result interface
    assert "BrowserUatPageResult" in types
    assert "page_result_id" in types
    assert "browser_channel" in types
    assert "platform" in types
    assert "browser_version" in types
    assert "error_message" in types

    # Results envelope
    assert "BrowserUatResults" in types
    assert "page_results" in types


def test_browser_uat_integrated_in_browser_tab() -> None:
    """Verify BrowserUatPanel is imported and rendered in the browser tab."""
    page = read("apps/web/src/app/analysis-runs/[analysisRunId]/page.tsx")

    # Import exists
    assert "BrowserUatPanel" in page
    assert "browser-uat/BrowserUatPanel" in page

    # Rendered inside SectionErrorBoundary
    assert 'sectionName="Real Browser Verification"' in page

    # Uses the analysisRunId prop
    uat_lines = [
        line for line in page.splitlines() if "BrowserUatPanel" in line and "analysisRunId" in line
    ]
    assert len(uat_lines) >= 1, "BrowserUatPanel must be rendered with analysisRunId prop"
