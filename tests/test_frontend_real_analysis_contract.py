from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "apps" / "web" / "src"


def test_homepage_is_real_analysis_product_and_demo_is_secondary() -> None:
    homepage = (ROOT / "app/page.tsx").read_text(encoding="utf-8")
    client = (ROOT / "lib/report-delivery-api.ts").read_text(encoding="utf-8")
    assert "Analyze Website" in homepage
    assert "Advanced settings" in homepage
    assert "chromium" in homepage and "firefox" in homepage and "webkit" in homepage
    assert "Recent analyses" in homepage
    assert 'href="/presentation"' in homepage
    assert "Open Prepared Demo" in homepage
    assert "startRealAnalysis" in homepage
    assert '"/api/v1/analysis/start"' in client
    assert "/api/v1/analysis/recent" in client
    assert (
        "prepared"
        not in homepage.split("startRealAnalysis", maxsplit=1)[1].split("catch", maxsplit=1)[0]
    )


def test_real_progress_report_and_exports_are_wired() -> None:
    report_page = (ROOT / "app/analysis-runs/[analysisRunId]/page.tsx").read_text(encoding="utf-8")
    panel = (ROOT / "components/reports/ReportDeliveryPanel.tsx").read_text(encoding="utf-8")
    progress = (ROOT / "components/reports/AnalysisProgressTimeline.tsx").read_text(
        encoding="utf-8"
    )
    combined = panel + progress + report_page
    assert 'searchParams.get("workflowExecutionId")' in report_page
    assert "Website analysis in progress" in combined
    for value in (
        "discovered_pages",
        "successfully_analysed_pages",
        "agent_states",
        "Presentation PDF",
        "Technical Appendix",
        "Page Inventory JSON",
    ):
        assert value in combined


def test_progress_uses_friendly_agents_and_honest_failure_states() -> None:
    report_page = (ROOT / "app/analysis-runs/[analysisRunId]/page.tsx").read_text(encoding="utf-8")
    panel = (ROOT / "components/reports/ReportDeliveryPanel.tsx").read_text(encoding="utf-8")
    progress = (ROOT / "components/reports/AnalysisProgressTimeline.tsx").read_text(
        encoding="utf-8"
    )
    # Agent labels live in the shared lib/agent-labels.ts (FE-6 dedup); both
    # panels import from there rather than defining their own copy.
    agent_labels = (ROOT / "lib/agent-labels.ts").read_text(encoding="utf-8")
    combined = panel + progress + report_page + agent_labels
    for label in (
        "Discovery Agent",
        "Performance Agent",
        "Accessibility Agent",
        "Site Diagnostics Agent",
        "Repository Intelligence Agent",
        "Evidence Validation Agent",
        "Remediation Agent",
        "Report Agent",
        "Not applicable",
        "Failed to start",
        "Discovery completeness",
        "Browser coverage",
        "Evidence completeness",
    ):
        assert label in combined
    assert "Completed agents:" not in combined
    assert '["Analysed", progress.page_coverage.analysed_pages]' not in combined
    assert "report_generation_available" in combined
    assert '["completed", "partial"].includes(progress.status)' in combined
    assert "setInterval" not in combined
    assert "setProgress(current)" in combined


def test_auxiliary_failures_retry_without_console_errors() -> None:
    report_page = (ROOT / "app/analysis-runs/[analysisRunId]/page.tsx").read_text(encoding="utf-8")
    assert "/metric-interpretations" in report_page
    assert "startRetriedRequest" in report_page
    assert "RETRY_DELAYS_MS" in report_page
    assert "interpretationsUnavailable" in report_page
    assert "Metric interpretation help is unavailable" in report_page
    assert 'interruptedResources.includes("analysis-report")' in report_page
    assert "Connection interrupted — retrying" in report_page
    assert "console.error" not in report_page


def test_report_separates_coverage_groups_and_uses_business_readable_structure() -> None:
    report_page = (ROOT / "app/analysis-runs/[analysisRunId]/page.tsx").read_text(encoding="utf-8")
    panel = (ROOT / "components/reports/ReportDeliveryPanel.tsx").read_text(encoding="utf-8")
    progress = (ROOT / "components/reports/AnalysisProgressTimeline.tsx").read_text(
        encoding="utf-8"
    )
    combined = panel + progress + report_page
    assert "Evidence completeness" in combined
    assert "No report has been generated. This does not mean that no issues exist." in combined
    for heading in (
        "Executive Summary",
        "Website Coverage",
        "Category Scores",
        "Top Findings",
        "Browser Compatibility",
        "Page Inventory",
        "Priority Action Plan",
        "Key Limitations",
    ):
        assert heading in combined
    assert "Findings Explorer" in combined
    for page_filter in (
        "Analysed",
        "Not analysed",
        "Failed",
        "Not scheduled",
        "Browser incomplete",
    ):
        assert page_filter in combined
    assert "Report ID:" not in combined
    assert "All retained occurrences" not in combined


def test_report_hydration_pagination_and_responsive_containment_contract() -> None:
    panel = (ROOT / "components/reports/ReportDeliveryPanel.tsx").read_text(encoding="utf-8")
    explanation = (ROOT / "components/metrics/AccessibleExplanation.tsx").read_text(
        encoding="utf-8"
    )
    diagnostics = (ROOT / "components/diagnostics/SiteDiagnosticsPanel.tsx").read_text(
        encoding="utf-8"
    )
    assert "createPortal(dialog, document.body)" in explanation
    assert "useSyncExternalStore" in explanation
    assert "triggerRef.current?.focus()" in explanation
    assert (
        '<div className="flex items-center justify-between text-xs text-slate-600">' in diagnostics
    )
    assert "FINDINGS_PAGE_SIZE = 20" in panel
    assert "visibleFindings.map" in panel
    assert "Document and Asset Inventory" in panel
    assert "max-w-full overflow-x-auto overscroll-x-contain" in panel
    assert "break-all" in panel and "break-words" in panel
    assert 'status_code ?? "Unavailable"' not in panel
