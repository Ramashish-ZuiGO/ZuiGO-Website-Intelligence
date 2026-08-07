from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_completed_analysis_exposes_confirmed_reanalysis_flow() -> None:
    panel = read("apps/web/src/components/comparisons/ReanalysisComparisonPanel.tsx")
    report_page = read("apps/web/src/app/analysis-runs/[analysisRunId]/page.tsx")
    assert "Re-analyse website" in panel
    assert "Baseline analysis" in panel
    assert "Browser engines" in panel
    assert "confirmed: true" in panel
    assert "baseline remains" in panel
    assert "ReanalysisComparisonPanel" in report_page
    assert "baselineRunId" in report_page
    assert "Reanalysis in progress" in report_page
    assert "Preparing comparison evidence" in report_page
    assert "comparisonTerminal" in report_page
    assert "currentReportAvailable" in report_page
    assert "baselineAvailable" in report_page
    assert "comparisonDataAvailable" in report_page
    assert "analysisComparisonApi.generate" in report_page
    assert "{comparisonReady && (" in report_page


def test_comparison_page_uses_business_language_and_accessible_evidence() -> None:
    page = read("apps/web/src/app/analysis-runs/[analysisRunId]/compare/[baselineRunId]/page.tsx")
    for heading in (
        "Overall improvement summary",
        "Score comparison",
        "Page coverage comparison",
        "Browser compatibility comparison",
        "Resolved findings",
        "Persistent findings",
        "New findings",
        "Regressions",
        "Action Plan progress",
        "Evidence limitations",
        "Export comparison",
    ):
        assert heading in page
    assert 'aria-label="Comparison sections"' in page
    assert "<details" in page
    assert "raw JSON" not in page
    assert "agent_id" not in page
    assert "finding_code" not in page
    assert "comparison_id}" not in page


def test_history_limits_selection_to_same_website_and_two_completed_runs() -> None:
    history = read("apps/web/src/app/projects/[projectId]/WebsiteAnalysisPanel.tsx")
    assert "Select any two completed analyses of this website to compare." in history
    assert "selectedComparisonRuns.length >= 2" in history
    assert 'run.status !== "completed"' in history
    assert "Compare selected analyses" in history
