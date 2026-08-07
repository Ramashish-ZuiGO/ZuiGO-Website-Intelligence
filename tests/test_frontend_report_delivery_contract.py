from pathlib import Path

ROOT = Path("apps/web/src")
COMPONENT = ROOT / "components/reports/ReportDeliveryPanel.tsx"
API = ROOT / "lib/report-delivery-api.ts"
TYPES = ROOT / "components/reports/types.ts"
WEBSITE = ROOT / "app/projects/[projectId]/WebsiteAnalysisPanel.tsx"
REPORT_PAGE = ROOT / "app/analysis-runs/[analysisRunId]/page.tsx"
ACTION_PLAN = ROOT / "app/projects/[projectId]/ActionPlanPanel.tsx"
AGENTS = ROOT / "components/agents/AgentExecutionPanel.tsx"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_exact_report_delivery_frontend_api_contract() -> None:
    api = _text(API)
    for path in (
        "/analysis/start",
        "/progress",
        "/reports/generate",
        "/reports/history",
        "/reports/${encodeURIComponent(reportId)}",
        "/download/${encodeURIComponent(format)}",
    ):
        assert path in api
    assert "idempotency_key" in api
    assert "workflow_execution_id" in api
    types = _text(TYPES)
    for name in (
        "AnalysisJourneyStart",
        "WorkflowProgress",
        "DeliveredReport",
        "ReportSection",
        "ReportArtifact",
        "ReportOccurrence",
        "DetailedReportFinding",
        "SectionAgentAttribution",
        "PaginatedReports",
    ):
        assert f"interface {name}" in types


def test_primary_journey_progress_history_and_export_states() -> None:
    component = _text(COMPONENT)
    for text in (
        "Start full analysis",
        "Generate immutable report",
        "Report history",
        "Export report",
        "Download",
        "Loading immutable report history",
        "No report has been generated",
        "Partial evidence",
        "Unavailable",
        "retry_available",
        "resume_available",
        "unavailable_tools",
        "unavailable_providers",
        "safe_error_summaries",
    ):
        assert text in component
    assert "window.setTimeout" in component
    assert "Math.min(15_000" in component
    assert "window.clearTimeout" in component
    assert "PAGE_SIZE" in component


def test_report_accessibility_safe_rendering_and_non_colour_status() -> None:
    component = _text(COMPONENT)
    for contract in (
        'role="progressbar"',
        'aria-live="polite"',
        'role="alert"',
        'aria-label="Report sections"',
        "<nav",
        "<article",
        "<section",
        "<h2",
        "<h3",
        "focus-visible:outline",
        "formatHumanTimestamp",
        "statusLabel",
        "Evidence references",
        "Technical evidence references",
    ):
        assert contract in component
    assert "dangerouslySetInnerHTML" not in component
    assert "No report has been generated. This does not mean that no issues exist." in component


def test_report_finding_filters_navigation_and_agent_attribution() -> None:
    component = _text(COMPONENT)
    for contract in (
        "Finding explorer",
        "Search findings",
        "Page or URL",
        'label="Severity"',
        'label="Category"',
        'label="Agent"',
        'label="Scope"',
        'label="Evidence state"',
        "Exact affected locations",
        "Affected browser",
        "Technical explanation",
        "Business impact",
        "Recommended remediation",
        "Responsible role",
        "Estimated effort",
        "Verification",
        "Section agent attribution",
        "Agents and evidence production",
        "Unavailable tools/providers",
        "finding-${finding.finding_id}",
        "friendlyAgentName",
    ):
        assert contract in component
    assert ".slice(0, 50)" not in component
    assert ".slice(0,50)" not in component


def test_report_delivery_integrates_required_frontend_surfaces() -> None:
    website = _text(WEBSITE)
    report_page = _text(REPORT_PAGE)
    action_plan = _text(ACTION_PLAN)
    agents = _text(AGENTS)
    assert ".startAnalysis(" in website
    assert 'aria-label="Start a complete website analysis"' in website
    assert "<ReportDeliveryPanel" in website
    assert "<ReportDeliveryPanel" in report_page
    assert "Final reports and exports" in report_page
    assert "Report evidence references" in action_plan
    assert "Open immutable report history and exports" in agents
