from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "apps" / "web" / "src"


def test_homepage_is_real_analysis_product_and_demo_is_secondary() -> None:
    homepage = (ROOT / "app/page.tsx").read_text(encoding="utf-8")
    client = (ROOT / "lib/report-delivery-api.ts").read_text(encoding="utf-8")
    assert "Start Website Analysis" in homepage
    assert "Maximum pages" in homepage
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
        "Failed stage:",
    ):
        assert label in panel
    assert "Completed agents:" not in panel
    assert '["Analysed", progress.page_coverage.analysed_pages]' not in panel
    assert "report_generation_available" in panel
