from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRESENTATION = (
    ROOT / "apps" / "web" / "src" / "components" / "presentation" / "PresentationDemo.tsx"
)
API_CLIENT = ROOT / "apps" / "web" / "src" / "lib" / "presentation-demo-api.ts"
HOME = ROOT / "apps" / "web" / "src" / "app" / "page.tsx"

EXPECTED_AGENTS = {
    "discovery_agent",
    "performance_agent",
    "accessibility_agent",
    "site_diagnostics_agent",
    "evidence_validation_agent",
    "repository_intelligence_agent",
    "remediation_agent",
    "report_agent",
}


def test_presentation_entry_actions_and_api_contract() -> None:
    component = PRESENTATION.read_text(encoding="utf-8")
    client = API_CLIENT.read_text(encoding="utf-8")
    home = HOME.read_text(encoding="utf-8")
    assert "Open presentation mode" in home
    assert 'href="/presentation"' in home
    for label in (
        "Run Demo Analysis",
        "Open Prepared Demo Report",
        "Reset Demo",
    ):
        assert label in component
    for endpoint in (
        "/api/v1/demo",
        "/api/v1/demo/prepare",
        "/api/v1/demo/run",
        "/api/v1/demo/reset",
    ):
        assert endpoint in client
    assert "IDEMPOTENCY_STORAGE_KEY" in component
    assert "localStorage" in component


def test_presentation_shows_parallel_workflow_and_all_eight_agents() -> None:
    component = PRESENTATION.read_text(encoding="utf-8")
    assert all(agent_id in component for agent_id in EXPECTED_AGENTS)
    assert "Parallel agent group" in component
    assert "Performance, accessibility, and site diagnostics" in component
    assert "Eight-agent summary" in component
    assert "Priority Action Plan" in component
    assert "Export Presentation PDF" in component
    assert "Open Full Report" in component


def test_presentation_has_explicit_states_fallback_and_coverage() -> None:
    component = PRESENTATION.read_text(encoding="utf-8")
    for state in (
        '"loading"',
        '"running"',
        '"completed"',
        '"partial"',
        '"failed"',
        '"fallback"',
        '"resetting"',
        '"error"',
    ):
        assert state in component
    assert "Prepared fallback report" in component
    assert "last verified prepared fallback report" in component
    assert "No execution is being shown as completed" in component
    assert "coverage_numerator" in component
    assert "coverage_denominator" in component
    assert "score_confidence_percent" in component


def test_presentation_accessibility_and_safe_rendering_contract() -> None:
    component = PRESENTATION.read_text(encoding="utf-8")
    assert 'aria-live="polite"' in component
    assert 'aria-atomic="true"' in component
    assert 'aria-label="Demo controls"' in component
    assert 'aria-label="Analysis stages"' in component
    assert "focus-visible:outline" in component
    assert "<main" in component
    assert "<header" in component
    assert "<section" in component
    assert "<h1" in component
    assert "<h2" in component
    assert "dangerouslySetInnerHTML" not in component
    assert "innerHTML" not in component


def test_progressive_disclosure_inventory_browser_matrix_and_plain_labels() -> None:
    component = PRESENTATION.read_text(encoding="utf-8")
    for tab in (
        "Overview",
        "Pages",
        "Browser Compatibility",
        "Findings",
        "Action Plan",
        "Scores",
        "Agents",
        "Technical Details",
    ):
        assert f'"{tab}"' in component
    assert 'role="tablist"' in component
    assert 'role="tabpanel"' in component
    assert "Page Inventory" in component
    assert "Filter pages" in component
    assert "Analysis status" in component
    assert "View page-level details" in component
    assert all(label in component for label in ("Chromium", "Firefox", "WebKit"))
    assert "View All Affected Pages" in component
    assert ".slice(0, 5)" in component
    assert ".slice(0, 10)" in component


def test_normal_presentation_does_not_render_internal_contract_fields() -> None:
    component = PRESENTATION.read_text(encoding="utf-8")
    forbidden_rendered_labels = (
        "Finding ID",
        "Rule ID",
        "Tool IDs",
        "Provider metadata",
        "Execution logs",
        "Raw JSON",
        "Stack trace",
    )
    assert all(label not in component for label in forbidden_rendered_labels)
    assert "dangerouslySetInnerHTML" not in component
