from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "apps" / "web" / "src"


def test_safe_array_access_patterns_in_analysis_page() -> None:
    page = (ROOT / "app/analysis-runs/[analysisRunId]/page.tsx").read_text(encoding="utf-8")
    assert "Array.isArray(report.score.available_categories)" in page
    assert "safeFindings" in page
    assert "Array.isArray(report.findings)" in page
    assert "Array.isArray(diagnostic.score?.deductions)" in page


def test_safe_array_access_patterns_in_report_delivery_panel() -> None:
    panel = (ROOT / "components/reports/ReportDeliveryPanel.tsx").read_text(encoding="utf-8")
    assert "safeSections" in panel
    assert "safeUnavailableSections" in panel
    assert "if (!Array.isArray(report.sections)) return [];" in panel
    assert "Array.isArray(finding.evidence_references)" in panel


def test_safe_array_access_in_accessibility_intelligence() -> None:
    acc = (ROOT / "components/accessibility/AccessibilityIntelligence.tsx").read_text(
        encoding="utf-8"
    )
    assert "Array.isArray(accessibilityData.findings)" in acc
    assert "Array.isArray(checklist.items)" in acc


def test_extracted_content_panel_boundary_normalization() -> None:
    panel = (ROOT / "components/content/ExtractedContentPanel.tsx").read_text(encoding="utf-8")
    assert "normalizeContent" in panel
    assert "Array.isArray(raw.sections)" in panel
    assert "Array.isArray(raw.headings)" in panel
    assert "Array.isArray(raw.paragraphs)" in panel


def test_section_error_boundary_coverage_in_project_page() -> None:
    page = (ROOT / "app/projects/[projectId]/page.tsx").read_text(encoding="utf-8")
    assert 'sectionName="Website Analysis"' in page
    assert 'sectionName="Website Coverage"' in page
    assert 'sectionName="Page Analysis"' in page
    assert 'sectionName="Action Plan"' in page
    assert 'sectionName="Repository"' in page


def test_section_error_boundary_coverage_in_analysis_panel() -> None:
    panel = (ROOT / "app/projects/[projectId]/WebsiteAnalysisPanel.tsx").read_text(encoding="utf-8")
    assert 'sectionName="Performance Intelligence"' in panel
    assert 'sectionName="Accessibility Intelligence"' in panel
    assert 'sectionName="Site Diagnostics"' in panel
    assert 'sectionName="Agent Execution"' in panel
    assert 'sectionName="Scoring Intelligence"' in panel
    assert 'sectionName="Report Delivery"' in panel


def test_section_error_boundary_coverage_in_comparison_page() -> None:
    page = (ROOT / "app/analysis-runs/[analysisRunId]/compare/[baselineRunId]/page.tsx").read_text(
        encoding="utf-8"
    )
    assert 'sectionName="Score Comparison"' in page
    assert 'sectionName="Coverage Comparison"' in page
    assert 'sectionName="Browser Compatibility Comparison"' in page
    assert 'sectionName="Finding Changes"' in page
    assert 'sectionName="Action Plan Progress"' in page
    assert 'sectionName="Evidence Limitations"' in page
    assert 'sectionName="Export Comparison"' in page


def test_section_error_boundary_coverage_in_analysis_run_page() -> None:
    page = (ROOT / "app/analysis-runs/[analysisRunId]/page.tsx").read_text(encoding="utf-8")
    assert 'sectionName="Methodology"' in page
    assert 'sectionName="All Limitations"' in page
    assert 'sectionName="Report Delivery"' in page
    assert 'sectionName="Browser Compatibility"' in page


def test_browser_uat_labels_do_not_overclaim() -> None:
    page = (ROOT / "app/analysis-runs/[analysisRunId]/page.tsx").read_text(encoding="utf-8")
    panel = (ROOT / "components/reports/ReportDeliveryPanel.tsx").read_text(encoding="utf-8")
    assert "Opera" not in page
    assert "Opera" not in panel
    assert "Google Chrome" in page
    assert "Microsoft Edge" in page
    assert "Apple Safari" in page
    assert "Chromium engine" in page
    assert "Chromium engine" in panel
    assert "internal signal" in panel


def test_verification_state_labels_in_browser_summary() -> None:
    page = (ROOT / "app/analysis-runs/[analysisRunId]/page.tsx").read_text(encoding="utf-8")
    assert '"Not verified in current environment"' in page
    assert '"Partially verified"' not in page


def test_start_analysis_timeout_in_frontend() -> None:
    panel_source = (ROOT / "app/projects/[projectId]/WebsiteAnalysisPanel.tsx").read_text(
        encoding="utf-8"
    )
    report_panel = (ROOT / "components/reports/ReportDeliveryPanel.tsx").read_text(encoding="utf-8")
    assert "AbortController" in panel_source
    assert "30_000" in panel_source
    assert "timed out" in panel_source
    assert "AbortController" in report_panel
    assert "30_000" in report_panel
    assert "timed out" in report_panel


def test_safe_array_access_in_diagnostics_panel() -> None:
    panel = (ROOT / "components/diagnostics/SiteDiagnosticsPanel.tsx").read_text(encoding="utf-8")
    assert "Array.isArray(graph.nodes)" in panel
    assert "Array.isArray(graph.edges)" in panel


def test_safe_array_access_in_agent_execution_panel() -> None:
    panel = (ROOT / "components/agents/AgentExecutionPanel.tsx").read_text(encoding="utf-8")
    assert "Array.isArray(run.tool_activity_summary)" in panel
    assert "Array.isArray(execution?.evidence_references)" in panel


def test_comparison_page_safe_array_access() -> None:
    page = (ROOT / "app/analysis-runs/[analysisRunId]/compare/[baselineRunId]/page.tsx").read_text(
        encoding="utf-8"
    )
    assert "Array.isArray(payload.scores.categories)" in page
    assert "Array.isArray(payload.action_plan)" in page
    assert "Array.isArray(payload.limitations)" in page
    assert "Array.isArray(comparison.artifacts)" in page


def test_representative_sample_size_cannot_reduce_core_page_analysis() -> None:
    from app.services.page_selection import select_scheduled_pages

    pages = [
        {"normalized_url": f"https://example.com/page-{i}", "crawl_depth": i % 3}
        for i in range(200)
    ]
    result = select_scheduled_pages(pages, maximum_pages=None)
    assert len(result) == 200

    result_limited = select_scheduled_pages(pages, maximum_pages=50)
    assert len(result_limited) == 50


def test_core_scheduled_eligible_invariant() -> None:
    from app.services.page_selection import select_scheduled_pages

    pages = [{"normalized_url": f"https://example.com/p{i}", "crawl_depth": 0} for i in range(10)]
    scheduled = select_scheduled_pages(pages, maximum_pages=None)
    assert len(scheduled) == len(pages)
    for page in pages:
        assert page in scheduled


def test_browser_sampling_separate_from_core_analysis() -> None:
    from app.services.browser_compatibility import (
        CompatibilityProfile,
        select_compatibility_pages,
    )

    pages = [
        {
            "url": f"https://example.com/p{i}",
            "analysis_status": "analysed",
            "page_type": "content",
        }
        for i in range(100)
    ]
    profile = CompatibilityProfile(representative_sample_size=5, all_pages_limit=10)
    browser_pages = select_compatibility_pages(pages, profile)
    assert len(browser_pages) == 5

    from app.services.page_selection import select_scheduled_pages

    core_pages = [{"normalized_url": p["url"], "crawl_depth": 0} for p in pages]
    core_scheduled = select_scheduled_pages(core_pages, maximum_pages=None)
    assert len(core_scheduled) == 100


# --- Blocker 1 regression: PDF vs Appendix separation ---


def test_pdf_artifact_and_appendix_produce_different_content() -> None:
    from app.services.report_delivery import _pdf_artifact, _technical_appendix_pdf

    snapshot: dict = {
        "title": "Test Report",
        "website_name": "test.example.com",
        "website_url": "https://test.example.com/",
        "generated_at": "2026-08-10T12:00:00+00:00",
        "report_id": "00000000-0000-0000-0000-000000000001",
        "executive_summary": "Test summary.",
        "overall_score": {"score": 85, "max_score": 100, "band": "good"},
        "confidence_percent": 90,
        "category_scores": [
            {"category_id": "technical_quality", "final_score": 85, "band": "good"},
        ],
        "findings": [
            {
                "title": "Test finding",
                "severity": "medium",
                "category": "seo",
                "recommendation": "Fix it",
                "exact_occurrences": [
                    {"normalized_url": "https://test.example.com/", "location": "h1"},
                ],
            },
        ],
        "action_plan": [
            {
                "priority_rank": 1,
                "title": "Fix test",
                "responsible_role": "Developer",
                "verification_method": "Manual check",
            },
        ],
        "coverage_confidence": {
            "coverage_numerator": 5,
            "coverage_denominator": 5,
            "coverage_percentage": 100.0,
        },
        "limitations": ["Test limitation"],
        "sections": [],
        "browser_compatibility": {
            "engines_tested": [],
            "matrix": [],
            "summary": {},
        },
    }
    primary = _pdf_artifact(snapshot)
    appendix = _technical_appendix_pdf(snapshot)
    assert primary != appendix
    assert b"TECHNICAL APPENDIX" in appendix
    assert b"TECHNICAL APPENDIX" not in primary
    assert b"CONTENTS" in primary


def test_pdf_download_route_renders_on_the_fly() -> None:
    source = (
        Path(__file__).resolve().parents[0].parent
        / "apps"
        / "api"
        / "app"
        / "api"
        / "routes"
        / "report_delivery.py"
    ).read_text(encoding="utf-8")
    download_fn_start = source.index("def download_report(")
    on_the_fly_block = source[download_fn_start : download_fn_start + 500]
    assert '"pdf"' in on_the_fly_block
    assert "render_additional_report_artifact" in source


def _immutability_snapshot(template_version: str = "2.0.0") -> dict:
    return {
        "title": "Immutable Report",
        "website_name": "test.example.com",
        "website_url": "https://test.example.com/",
        "generated_at": "2026-08-10T12:00:00+00:00",
        "report_id": "00000000-0000-0000-0000-000000000009",
        "template_version": template_version,
        "schema_version": "1.1.0",
        "executive_summary": "Test summary.",
        "overall_score": {"score": 85, "max_score": 100, "band": "good"},
        "confidence_percent": 90,
        "category_scores": [
            {"category_id": "technical_quality", "final_score": 85, "band": "good"},
        ],
        "findings": [],
        "action_plan": [],
        "coverage_confidence": {
            "coverage_numerator": 5,
            "coverage_denominator": 5,
            "coverage_percentage": 100.0,
        },
        "limitations": [],
        "sections": [],
        "browser_compatibility": {"engines_tested": [], "matrix": [], "summary": {}},
    }


def test_primary_pdf_render_is_deterministic() -> None:
    """Item 4A: rendering the same immutable snapshot twice yields identical
    bytes, so downloading the primary PDF twice produces the same SHA256.
    """
    import hashlib

    from app.services.report_delivery import _pdf_artifact

    snapshot = _immutability_snapshot()
    first = _pdf_artifact(snapshot)
    second = _pdf_artifact(snapshot)
    assert first == second
    assert hashlib.sha256(first).hexdigest() == hashlib.sha256(second).hexdigest()


def test_primary_pdf_stamps_recorded_template_version_not_module_constant() -> None:
    """Item 4B/4C: the PDF stamps the template version recorded in the immutable
    snapshot, so a historical report renders faithfully even after the code's
    TEMPLATE_VERSION advances.
    """
    from app.services import report_delivery

    historical = report_delivery._pdf_artifact(_immutability_snapshot("1.5.0"))
    assert b"ZuiGO report template 1.5.0" in historical
    assert f"ZuiGO report template {report_delivery.TEMPLATE_VERSION}".encode() not in historical


def test_download_route_has_version_aware_immutability_guard() -> None:
    source = (
        Path(__file__).resolve().parents[0].parent
        / "apps"
        / "api"
        / "app"
        / "api"
        / "routes"
        / "report_delivery.py"
    ).read_text(encoding="utf-8")
    assert "_STORED_ARTIFACT_FORMATS" in source
    assert "report.template_version != TEMPLATE_VERSION" in source


# --- Blocker 5 regression: branded scope schema ---


def test_branded_browser_scope_uses_separated_schema() -> None:
    from app.services.browser_compatibility import (
        BRANDED_BROWSER_SCOPE,
        UAT_VERIFICATION_STATES,
    )

    assert [entry["browser"] for entry in BRANDED_BROWSER_SCOPE] == [
        "Google Chrome",
        "Microsoft Edge",
        "Apple Safari",
    ]
    for entry in BRANDED_BROWSER_SCOPE:
        assert "verification_state" in entry
        assert "verification_state_label" in entry
        assert "required_version_policy" in entry
        assert "required_platforms" in entry
        assert "actual_tested_browser_version" in entry
        assert "actual_tested_platform" in entry
        assert "actual_verified_environments" in entry
        assert "engineering_signals" in entry
        assert "limitations" in entry
        assert "related_engine" in entry
        assert entry["verification_state"] in UAT_VERIFICATION_STATES
        # No branded infrastructure exists in this environment: nothing may
        # claim verification, and engine evidence stays an engineering signal.
        assert entry["verification_state"] == "NOT_VERIFIED"
        assert entry["actual_verified_environments"] == []
        assert entry["actual_tested_browser_version"] is None
        assert "engine" not in entry or entry.get("engine") is None
        assert "verification_note" not in entry


# --- Blocker 4 regression: stale threshold ---


def test_stale_threshold_is_900_seconds() -> None:
    from app.services.workflow_execution import REAL_EXECUTION_STALE_AFTER_SECONDS

    assert REAL_EXECUTION_STALE_AFTER_SECONDS == 900
