from pathlib import Path


def test_page_analysis_panel_has_required_sections() -> None:
    source = Path("apps/web/src/app/projects/[projectId]/PageAnalysisPanel.tsx").read_text(
        encoding="utf-8"
    )
    assert "Level 1" in source
    assert "Level 2" in source
    assert "coverage" in source
    assert "scores" in source
    assert "recommendations" in source
    assert "failed" in source
    assert "InfoIcon" in source
    assert "ScoreDisplay" in source
    assert "StatusBadge" in source
    assert "AnalysisLevelBadge" in source
    assert "/page-analysis/summary" in source
    assert "/page-analysis/coverage" in source
    assert "/page-analysis/scores" in source
    assert "/page-analysis/recommendations" in source
    assert "/page-analysis/failed-skipped" in source
    assert "/page-analysis/run" in source


def test_score_format_x_out_of_100() -> None:
    source = Path("apps/web/src/app/projects/[projectId]/PageAnalysisPanel.tsx").read_text(
        encoding="utf-8"
    )
    assert "/100" in source


def test_confidence_displayed_separately() -> None:
    source = Path("apps/web/src/app/projects/[projectId]/PageAnalysisPanel.tsx").read_text(
        encoding="utf-8"
    )
    assert "confidence" in source.lower()


def test_action_location_rendered() -> None:
    source = Path("apps/web/src/app/projects/[projectId]/PageAnalysisPanel.tsx").read_text(
        encoding="utf-8"
    )
    assert "action_location" in source
    assert "Action location" in source


def test_remediation_and_verification_method() -> None:
    source = Path("apps/web/src/app/projects/[projectId]/PageAnalysisPanel.tsx").read_text(
        encoding="utf-8"
    )
    assert "Remediation" in source
    assert "Verification" in source


def test_information_icon_accessibility() -> None:
    source = Path("apps/web/src/app/projects/[projectId]/PageAnalysisPanel.tsx").read_text(
        encoding="utf-8"
    )
    assert "aria-label" in source
    assert "Escape" in source


def test_page_url_attribution_in_table() -> None:
    source = Path("apps/web/src/app/projects/[projectId]/PageAnalysisPanel.tsx").read_text(
        encoding="utf-8"
    )
    assert "page_url" in source
    assert "Page URL" in source or "Page" in source


def test_status_filters_rendered() -> None:
    source = Path("apps/web/src/app/projects/[projectId]/PageAnalysisPanel.tsx").read_text(
        encoding="utf-8"
    )
    assert "StatusBadge" in source
    assert "status" in source


def test_page_analysis_included_in_project_page() -> None:
    source = Path("apps/web/src/app/projects/[projectId]/page.tsx").read_text(encoding="utf-8")
    assert "PageAnalysisPanel" in source
