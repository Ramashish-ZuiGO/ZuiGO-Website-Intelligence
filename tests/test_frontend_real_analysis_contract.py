from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "apps" / "web" / "src"


def test_homepage_is_real_analysis_product_and_demo_is_secondary() -> None:
    homepage = (ROOT / "app/page.tsx").read_text(encoding="utf-8")
    client = (ROOT / "lib/report-delivery-api.ts").read_text(encoding="utf-8")
    assert "Start Website Analysis" in homepage
    assert "Advanced settings" in homepage
    assert "chromium" in homepage and "firefox" in homepage and "webkit" in homepage
    assert "Recent real analyses" in homepage
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
    assert 'searchParams.get("workflowExecutionId")' in report_page
    assert "Website analysis in progress" in report_page
    assert "prepared" in report_page and "demo evidence is used" in report_page
    for value in (
        "discovered_pages",
        "scheduled_pages",
        "not_scheduled_pages",
        "visited_pages",
        "successfully_analysed_pages",
        "failed_pages",
        "skipped_pages",
        "incomplete_pages",
        "browser_engine_progress",
        "agent_states",
        "Presentation PDF",
        "Technical Appendix",
        "Page Inventory JSON",
    ):
        assert value in panel
    assert 'performWorkflowAction("cancel")' in panel
    assert 'performWorkflowAction("resume")' in panel


def test_progress_uses_friendly_agents_and_honest_failure_states() -> None:
    panel = (ROOT / "components/reports/ReportDeliveryPanel.tsx").read_text(encoding="utf-8")
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
        "Not scheduled",
        "Download Page Inventory",
        "Last progress update",
        "Latest successful status check",
        "Connection interrupted — retrying",
        "Failed stage:",
        "Failed page URLs and reasons",
        "timed_out_pages",
        "Normalized",
        "Eligible",
        "Discovery completeness",
        "Analysed-page coverage",
        "Full-site coverage",
        "Website discovery was incomplete",
        "Full-site coverage is not established",
        "Browser coverage",
        "Evidence completeness",
    ):
        assert label in panel
    assert "Completed agents:" not in panel
    assert '["Analysed", progress.page_coverage.analysed_pages]' not in panel
    assert "report_generation_available" in panel
    assert '["completed", "partial"].includes(progress.status)' in panel
    assert "setInterval" not in panel
    assert "setProgress(current)" in panel


def test_auxiliary_failures_retry_without_console_errors() -> None:
    report_page = (ROOT / "app/analysis-runs/[analysisRunId]/page.tsx").read_text(encoding="utf-8")
    assert "/metric-interpretations" in report_page
    assert "startRetriedRequest" in report_page
    assert "RETRY_DELAYS_MS" in report_page
    assert "interpretationsInterrupted" in report_page
    assert "Metric interpretation help is temporarily unavailable" in report_page
    assert 'setResourceInterrupted("metric-interpretations"' not in report_page
    assert 'interruptedResources.includes("analysis-report")' in report_page
    assert "Connection interrupted — retrying" in report_page
    assert "console.error" not in report_page


def test_report_separates_coverage_groups_and_uses_business_readable_structure() -> None:
    panel = (ROOT / "components/reports/ReportDeliveryPanel.tsx").read_text(encoding="utf-8")
    assert "Analysed-page coverage" in panel
    assert "Full-site coverage" in panel
    assert "Evidence completeness" in panel
    assert "This is not website" in panel
    for number, heading in enumerate(
        (
            "Executive Summary",
            "Website Coverage",
            "Overall and Category Scores",
            "Top Findings",
            "Browser Compatibility",
            "Page-by-Page Results",
            "Action Plan",
            "Evidence Limitations",
        ),
        start=1,
    ):
        assert f"number={{{number}}}" in panel
        assert f'title="{heading}"' in panel
    assert "Technical Details" in panel
    assert "All Findings" in panel
    for page_filter in (
        "Analysed",
        "Not analysed",
        "Failed",
        "Not scheduled",
        "Browser incomplete",
    ):
        assert page_filter in panel
    assert "Report ID:" not in panel
    assert "All retained occurrences" not in panel


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
