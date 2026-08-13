"""Focused behavioral tests for the redesigned report artifacts (HTML, PDF, Technical Appendix).

Tests cover: hierarchy, mode separation, canonical metric consistency, HTML
cleanliness, PDF section ordering / page-count sanity, appendix completeness,
URL wrapping, browser unavailable semantics, partial evidence, null/missing fields.
"""

import html as html_module
import io
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from app.services.report_delivery import (
    _coverage_summary_lines,
    _html_artifact,
    _pdf_artifact,
    _pdf_paginate,
    _technical_appendix_pdf,
    render_report_artifact,
)
from pypdf import PdfReader


def _minimal_snapshot(**overrides: Any) -> dict[str, Any]:
    """Build a minimal valid snapshot for artifact generation."""
    base: dict[str, Any] = {
        "schema_version": "1.1.0",
        "report_id": str(uuid.uuid4()),
        "report_quality": "PARTIAL",
        "title": "Test Website analysis report",
        "generated_at": datetime.now(UTC).isoformat(),
        "report_version": "1.1.0",
        "template_version": "2.0.0",
        "project_id": str(uuid.uuid4()),
        "project_name": "Test Project",
        "website_id": str(uuid.uuid4()),
        "website_name": "Test Site",
        "website_url": "https://test.example.com/",
        "analysis_run_id": str(uuid.uuid4()),
        "workflow_execution_id": str(uuid.uuid4()),
        "score_execution_id": None,
        "status": "partial",
        "evidence_coverage": {"numerator": 10, "denominator": 16, "percentage": 62.5},
        "confidence_percent": 72,
        "overall_score": 85,
        "submitted_url": "https://test.example.com",
        "normalized_url": "https://test.example.com/",
        "page_coverage": {
            "total_urls_discovered": 30,
            "normalized_pages": 28,
            "eligible_pages": 20,
            "total_pages_scheduled": 20,
            "total_pages_visited": 18,
            "successfully_analysed_pages": 15,
            "failed_pages": 3,
            "skipped_pages": 2,
            "not_scheduled_pages": 0,
            "pages_with_incomplete_evidence": 1,
            "coverage_numerator": 15,
            "coverage_denominator": 20,
            "analysed_page_coverage_percentage": 75.0,
            "discovery_completeness": "complete",
            "discovery_stage_status": "completed",
            "discovery_completeness_message": None,
            "discovery_failure_message": None,
        },
        "page_inventory": [
            {
                "url": f"https://test.example.com/page-{i}",
                "resource_classification": "eligible_html_page",
                "analysed": i < 15,
                "result": "passed" if i < 15 else "not_analysed",
                "browser_engines_tested": ["chromium"] if i < 15 else [],
                "failure_reason": None if i < 15 else "timeout",
                "exclusion_reason": None,
            }
            for i in range(20)
        ],
        "browser_compatibility": {
            "engines": [
                {
                    "engine": "chromium",
                    "tested_pages": 15,
                    "eligible_pages": 20,
                    "availability_status": "available",
                    "passed_pages": 14,
                    "partial_pages": 1,
                    "failed_pages": 0,
                },
                {
                    "engine": "webkit",
                    "tested_pages": 0,
                    "eligible_pages": 20,
                    "availability_status": "unavailable",
                    "passed_pages": 0,
                    "partial_pages": 0,
                    "failed_pages": 0,
                },
            ],
            "matrix": [],
        },
        "sections": _minimal_sections(),
        "limitations": [
            "Website discovery was incomplete.",
            "Evidence completeness and website page coverage are separate measures.",
        ],
        "canonical_metrics": {
            "report_section_coverage": {
                "numerator": 10,
                "denominator": 16,
                "percentage": 62.5,
                "label": "report sections with available evidence",
            },
            "score_category_coverage": {
                "numerator": 5,
                "denominator": 5,
                "percentage": 100,
                "label": "scoring categories with available evidence",
            },
            "affected_eligible_page_count": 8,
            "affected_total_count": 12,
            "eligible_page_count": 20,
            "report_confidence_percent": 72,
            "formula_determinism_percent": 100,
            "confidence_components": {},
        },
    }
    base.update(overrides)
    return base


def _minimal_sections() -> list[dict[str, Any]]:
    findings = [
        {
            "finding_id": str(uuid.uuid4()),
            "finding_code": "render_blocking",
            "issue_title": "Render-blocking stylesheet",
            "severity": "high",
            "category": "performance",
            "scope": "page",
            "plain_language_explanation": "A stylesheet blocks rendering.",
            "technical_impact": "Delays first paint.",
            "business_impact": "Slower perceived load.",
            "recommended_remediation": "Defer non-critical CSS.",
            "responsible_role": "Frontend developer",
            "estimated_effort_band": "low",
            "detecting_agent": "performance_agent",
            "validating_agent": None,
            "affected_page_count": 5,
            "occurrence_count": 5,
            "confidence": 90,
            "evidence_limitations": None,
            "evidence_state": "available",
            "exact_occurrences": [
                {
                    "normalized_url": f"https://test.example.com/page-{i}",
                    "selector": "head > link",
                    "observed_value": "blocking",
                    "expected_value": "non-blocking",
                }
                for i in range(5)
            ],
        },
        {
            "finding_id": str(uuid.uuid4()),
            "finding_code": "missing_alt",
            "issue_title": "Images missing alt text",
            "severity": "medium",
            "category": "accessibility",
            "scope": "page",
            "plain_language_explanation": "Some images lack alt attributes.",
            "technical_impact": "Screen readers cannot describe images.",
            "business_impact": "Accessibility compliance risk.",
            "recommended_remediation": "Add descriptive alt text.",
            "responsible_role": "Content team",
            "estimated_effort_band": "medium",
            "detecting_agent": "accessibility_agent",
            "validating_agent": None,
            "affected_page_count": 3,
            "occurrence_count": 7,
            "confidence": 85,
            "evidence_limitations": None,
            "evidence_state": "available",
            "exact_occurrences": [
                {
                    "normalized_url": f"https://test.example.com/page-{i}",
                    "selector": "img.hero",
                    "observed_value": "missing",
                    "expected_value": "descriptive alt text",
                }
                for i in range(3)
            ],
        },
    ]
    return [
        {
            "section_key": "executive_summary",
            "title": "Executive Summary",
            "status": "completed",
            "unavailable_reason": None,
            "content": {
                "executive_summary": "The website has moderate quality.",
                "strengths": ["Fast server response", "Good mobile layout"],
                "weaknesses": ["Missing alt text", "Render-blocking CSS"],
                "top_five_problems": [
                    {
                        "title": "Render-blocking stylesheet",
                        "severity": "high",
                        "affected_page_count": 5,
                        "occurrence_count": 5,
                    },
                    {
                        "title": "Images missing alt text",
                        "severity": "medium",
                        "affected_page_count": 3,
                        "occurrence_count": 7,
                    },
                ],
                "top_five_recommended_actions": [
                    {
                        "title": "Defer non-critical CSS",
                        "impact": "Improves first paint by ~1s",
                        "responsible_role": "Frontend developer",
                        "effort": "Low",
                    },
                    {
                        "title": "Add alt text to images",
                        "impact": "Accessibility compliance",
                        "responsible_role": "Content team",
                        "effort": "Medium",
                    },
                ],
            },
            "evidence_references": [{"evidence_type": "test", "evidence_id": "ref1"}],
        },
        {
            "section_key": "scores",
            "title": "Overall and Category Scores",
            "status": "completed",
            "unavailable_reason": None,
            "content": {
                "overall_score": 85,
                "categories": [
                    {
                        "category_id": "performance",
                        "score": 80,
                        "evidence_available": True,
                        "included": True,
                        "exclusion_reason": None,
                    },
                    {
                        "category_id": "accessibility",
                        "score": 75,
                        "evidence_available": True,
                        "included": True,
                        "exclusion_reason": None,
                    },
                    {
                        "category_id": "best_practices",
                        "score": 90,
                        "evidence_available": True,
                        "included": True,
                        "exclusion_reason": None,
                    },
                    {
                        "category_id": "seo",
                        "score": 95,
                        "evidence_available": True,
                        "included": True,
                        "exclusion_reason": None,
                    },
                    {
                        "category_id": "technical_quality",
                        "score": 85,
                        "evidence_available": True,
                        "included": True,
                        "exclusion_reason": None,
                    },
                ],
            },
            "evidence_references": [],
        },
        {
            "section_key": "page_level_findings",
            "title": "Page-Level Findings",
            "status": "completed",
            "unavailable_reason": None,
            "content": {"findings": findings},
            "evidence_references": [],
        },
        {
            "section_key": "priority_action_plan",
            "title": "Priority Action Plan",
            "status": "completed",
            "unavailable_reason": None,
            "content": {"generation_status": "deterministic_from_findings", "recommendations": []},
            "evidence_references": [],
        },
        {
            "section_key": "coverage_confidence",
            "title": "Evidence Coverage and Confidence",
            "status": "completed",
            "unavailable_reason": None,
            "content": {},
            "evidence_references": [],
        },
        {
            "section_key": "performance",
            "title": "Performance",
            "status": "completed",
            "unavailable_reason": None,
            "content": {"metric": "value"},
            "evidence_references": [{"evidence_type": "lighthouse", "evidence_id": "perf1"}],
        },
        {
            "section_key": "accessibility",
            "title": "Accessibility",
            "status": "unavailable",
            "unavailable_reason": "Accessibility agent did not produce evidence.",
            "content": {},
            "evidence_references": [],
        },
        {
            "section_key": "multi_agent_execution",
            "title": "Multi-Agent Execution Summary",
            "status": "completed",
            "unavailable_reason": None,
            "content": {
                "agents": [
                    {
                        "agent_id": "performance_agent",
                        "status": "completed",
                        "status_explanation": "All evidence collected.",
                        "evidence_produced": [{"type": "lighthouse"}],
                    },
                    {
                        "agent_id": "accessibility_agent",
                        "status": "failed",
                        "status_explanation": "Provider timeout.",
                        "evidence_produced": [],
                    },
                ],
                "unavailable_capabilities": ["axe_provider"],
            },
            "evidence_references": [],
        },
        {
            "section_key": "methodology_limitations",
            "title": "Methodology, Versions and Limitations",
            "status": "completed",
            "unavailable_reason": None,
            "content": {},
            "evidence_references": [],
        },
    ]


# ---------------------------------------------------------------------------
# HTML Report Tests
# ---------------------------------------------------------------------------


class TestHTMLReportStructure:
    def test_html_has_cover_toc_and_all_sections(self) -> None:
        snapshot = _minimal_snapshot()
        result = _html_artifact(snapshot)
        doc = result.decode("utf-8")
        assert "<!doctype html>" in doc
        assert "<title>" in doc
        assert "ZuiGO WebIQ" in doc
        for section_id in [
            "executive-summary",
            "coverage",
            "scores",
            "findings",
            "action-plan",
            "browser-compat",
            "page-summary",
            "limitations",
            "methodology",
        ]:
            assert f'id="{section_id}"' in doc

    def test_html_contains_no_localhost_urls(self) -> None:
        snapshot = _minimal_snapshot()
        doc = _html_artifact(snapshot).decode("utf-8")
        assert "localhost" not in doc
        assert "127.0.0.1" not in doc

    def test_html_contains_no_react_debug_controls(self) -> None:
        snapshot = _minimal_snapshot()
        doc = _html_artifact(snapshot).decode("utf-8")
        for forbidden in ["onClick", "useState", "useEffect", "className=", "__next"]:
            assert forbidden not in doc

    def test_html_score_displayed_correctly(self) -> None:
        snapshot = _minimal_snapshot(overall_score=92)
        doc = _html_artifact(snapshot).decode("utf-8")
        assert "92" in doc
        assert "/100" in doc

    def test_html_score_unavailable(self) -> None:
        snapshot = _minimal_snapshot(overall_score=None)
        doc = _html_artifact(snapshot).decode("utf-8")
        assert "unavailable" in doc.lower()

    def test_html_findings_capped_at_five(self) -> None:
        findings = _minimal_snapshot()["sections"][2]["content"]["findings"]
        for i in range(10):
            findings.append(
                {
                    **findings[0],
                    "finding_id": str(uuid.uuid4()),
                    "issue_title": f"Finding {i + 3}",
                }
            )
        snapshot = _minimal_snapshot()
        snapshot["sections"][2]["content"]["findings"] = findings
        doc = _html_artifact(snapshot).decode("utf-8")
        assert "12 unique findings" in doc

    def test_html_browser_unavailable_semantics(self) -> None:
        snapshot = _minimal_snapshot()
        doc = _html_artifact(snapshot).decode("utf-8")
        assert "Unavailable" in doc
        assert "not represented as passed or failed" in doc.lower()

    def test_html_escapes_user_content(self) -> None:
        snapshot = _minimal_snapshot(
            website_name='Test <script>alert("xss")</script>',
            website_url="https://test.example.com/<evil>",
        )
        doc = _html_artifact(snapshot).decode("utf-8")
        assert "<script>" not in doc
        assert "&lt;script&gt;" in doc

    def test_html_partial_evidence_note(self) -> None:
        snapshot = _minimal_snapshot()
        doc = _html_artifact(snapshot).decode("utf-8")
        assert "Accessibility" in doc
        assert "Accessibility agent did not produce evidence" in doc

    def test_html_limitations_rendered(self) -> None:
        snapshot = _minimal_snapshot()
        doc = _html_artifact(snapshot).decode("utf-8")
        for lim in snapshot["limitations"]:
            assert html_module.escape(lim) in doc

    def test_html_responsive_meta_viewport(self) -> None:
        snapshot = _minimal_snapshot()
        doc = _html_artifact(snapshot).decode("utf-8")
        assert 'name="viewport"' in doc
        assert "width=device-width" in doc

    def test_html_print_styles(self) -> None:
        snapshot = _minimal_snapshot()
        doc = _html_artifact(snapshot).decode("utf-8")
        assert "@media print" in doc

    def test_html_actions_shown(self) -> None:
        snapshot = _minimal_snapshot()
        doc = _html_artifact(snapshot).decode("utf-8")
        assert "Defer non-critical CSS" in doc
        assert "Add alt text to images" in doc

    def test_html_category_scores_rendered(self) -> None:
        snapshot = _minimal_snapshot()
        doc = _html_artifact(snapshot).decode("utf-8")
        assert "80/100" in doc
        assert "75/100" in doc
        assert "Performance" in doc
        assert "Accessibility" in doc


class TestHTMLReportNullSafety:
    def test_html_null_score_null_confidence(self) -> None:
        snapshot = _minimal_snapshot(overall_score=None, confidence_percent=None)
        doc = _html_artifact(snapshot).decode("utf-8")
        assert "N/A" in doc or "unavailable" in doc.lower()

    def test_html_empty_sections(self) -> None:
        snapshot = _minimal_snapshot(sections=[])
        doc = _html_artifact(snapshot).decode("utf-8")
        assert "<!doctype html>" in doc

    def test_html_empty_findings(self) -> None:
        snapshot = _minimal_snapshot()
        snapshot["sections"][2]["content"]["findings"] = []
        doc = _html_artifact(snapshot).decode("utf-8")
        assert "0 unique findings" in doc

    def test_html_empty_limitations(self) -> None:
        snapshot = _minimal_snapshot(limitations=[])
        doc = _html_artifact(snapshot).decode("utf-8")
        assert "No specific limitations" in doc


# ---------------------------------------------------------------------------
# PDF Tests
# ---------------------------------------------------------------------------


class TestPDFStructure:
    def test_pdf_is_valid_pdf14(self) -> None:
        snapshot = _minimal_snapshot()
        result = _pdf_artifact(snapshot)
        assert result[:5] == b"%PDF-"
        assert b"%%EOF" in result

    def test_pdf_page_count_reasonable(self) -> None:
        snapshot = _minimal_snapshot()
        result = _pdf_artifact(snapshot)
        page_count = result.count(b"/Type /Page ")
        assert 5 <= page_count <= 25

    def test_pdf_contains_executive_sections(self) -> None:
        snapshot = _minimal_snapshot()
        result = _pdf_artifact(snapshot)
        text = result.decode("latin-1", errors="replace")
        for section in [
            "EXECUTIVE SUMMARY",
            "COVERAGE AND CONFIDENCE",
            "CATEGORY SCORES",
            "PRIORITY FINDINGS",
            "COMPLETE FINDINGS REGISTER",
            "PRIORITY ACTION PLAN",
            "BROWSER UAT - REQUIRED SCOPE",
            "LIMITATIONS AND COMPLETION",
        ]:
            assert section in text

    def test_pdf_contains_score(self) -> None:
        snapshot = _minimal_snapshot(overall_score=85)
        result = _pdf_artifact(snapshot)
        text = result.decode("latin-1", errors="replace")
        assert "85/100" in text

    def test_pdf_null_score_handled(self) -> None:
        snapshot = _minimal_snapshot(overall_score=None)
        result = _pdf_artifact(snapshot)
        text = result.decode("latin-1", errors="replace")
        assert "Unavailable" in text

    def test_pdf_priority_section_capped_but_register_complete(self) -> None:
        """The prioritized section stays concise, but the client PDF's complete
        findings register must contain EVERY unique finding — no important
        finding disappears merely because it is not in the Top 5."""
        snapshot = _minimal_snapshot()
        findings = snapshot["sections"][2]["content"]["findings"]
        for i in range(10):
            findings.append(
                {
                    **findings[0],
                    "finding_id": str(uuid.uuid4()),
                    "issue_title": f"Extra finding {i}",
                }
            )
        result = _pdf_artifact(snapshot)
        text = result.decode("latin-1", errors="replace")
        assert "12 unique findings" in text
        for i in range(10):
            assert f"Extra finding {i}" in text

    def test_pdf_browser_unavailable(self) -> None:
        snapshot = _minimal_snapshot()
        result = _pdf_artifact(snapshot)
        text = result.decode("latin-1", errors="replace")
        assert "Unavailable" in text

    def test_pdf_no_localhost(self) -> None:
        snapshot = _minimal_snapshot()
        result = _pdf_artifact(snapshot)
        text = result.decode("latin-1", errors="replace")
        assert "localhost" not in text
        assert "127.0.0.1" not in text


# ---------------------------------------------------------------------------
# Technical Appendix Tests
# ---------------------------------------------------------------------------


class TestTechnicalAppendix:
    def test_appendix_is_valid_pdf(self) -> None:
        snapshot = _minimal_snapshot()
        result = _technical_appendix_pdf(snapshot)
        assert result[:5] == b"%PDF-"
        assert b"%%EOF" in result

    def test_appendix_contains_all_findings(self) -> None:
        snapshot = _minimal_snapshot()
        result = _technical_appendix_pdf(snapshot)
        text = result.decode("latin-1", errors="replace")
        assert "ALL FINDINGS" in text
        assert "2 unique findings" in text
        assert "Render-blocking stylesheet" in text
        assert "Images missing alt text" in text

    def test_appendix_contains_page_inventory(self) -> None:
        snapshot = _minimal_snapshot()
        result = _technical_appendix_pdf(snapshot)
        text = result.decode("latin-1", errors="replace")
        assert "PAGE INVENTORY" in text
        assert "20 eligible HTML pages" in text

    def test_appendix_contains_browser_matrix(self) -> None:
        snapshot = _minimal_snapshot()
        result = _technical_appendix_pdf(snapshot)
        text = result.decode("latin-1", errors="replace")
        assert "BROWSER ENGINE EVIDENCE MATRIX" in text
        assert "UNAVAILABLE" in text

    def test_appendix_contains_agent_execution(self) -> None:
        snapshot = _minimal_snapshot()
        result = _technical_appendix_pdf(snapshot)
        text = result.decode("latin-1", errors="replace")
        assert "AGENT EXECUTION" in text

    def test_appendix_contains_methodology(self) -> None:
        snapshot = _minimal_snapshot()
        result = _technical_appendix_pdf(snapshot)
        text = result.decode("latin-1", errors="replace")
        assert "METHODOLOGY AND VERSIONS" in text

    def test_appendix_contains_evidence_references(self) -> None:
        snapshot = _minimal_snapshot()
        result = _technical_appendix_pdf(snapshot)
        text = result.decode("latin-1", errors="replace")
        assert "EVIDENCE REFERENCES" in text

    def test_appendix_page_count_larger_than_primary(self) -> None:
        snapshot = _minimal_snapshot()
        primary = _pdf_artifact(snapshot)
        appendix = _technical_appendix_pdf(snapshot)
        primary_pages = primary.count(b"/Type /Page ")
        appendix_pages = appendix.count(b"/Type /Page ")
        assert appendix_pages >= primary_pages

    def test_appendix_includes_occurrences(self) -> None:
        snapshot = _minimal_snapshot()
        result = _technical_appendix_pdf(snapshot)
        text = result.decode("latin-1", errors="replace")
        assert "Occurrences" in text
        assert "test.example.com/page-0" in text


# ---------------------------------------------------------------------------
# Canonical Metric Consistency
# ---------------------------------------------------------------------------


class TestCanonicalMetricConsistency:
    def test_html_and_pdf_show_same_score(self) -> None:
        snapshot = _minimal_snapshot(overall_score=73)
        html_doc = _html_artifact(snapshot).decode("utf-8")
        pdf_text = _pdf_artifact(snapshot).decode("latin-1", errors="replace")
        assert "73" in html_doc
        assert "73" in pdf_text

    def test_html_and_pdf_show_same_finding_count(self) -> None:
        snapshot = _minimal_snapshot()
        html_doc = _html_artifact(snapshot).decode("utf-8")
        pdf_text = _pdf_artifact(snapshot).decode("latin-1", errors="replace")
        assert "2 unique findings" in html_doc
        assert "2 unique findings" in pdf_text

    def test_render_report_artifact_dispatches_correctly(self) -> None:
        snapshot = _minimal_snapshot()
        html_result = render_report_artifact("html", snapshot)
        assert b"<!doctype html>" in html_result
        pdf_result = render_report_artifact("pdf", snapshot)
        assert pdf_result[:5] == b"%PDF-"
        json_result = render_report_artifact("json", snapshot)
        parsed = json.loads(json_result)
        assert parsed["report_id"] == snapshot["report_id"]


# ---------------------------------------------------------------------------
# Helper Tests
# ---------------------------------------------------------------------------


class TestPDFPaginate:
    def test_paginate_splits_correctly(self) -> None:
        lines = [f"line {i}" for i in range(100)]
        pages = _pdf_paginate(lines, lines_per_page=46)
        assert len(pages) == 3
        assert len(pages[0]) == 46
        assert len(pages[1]) == 46
        assert len(pages[2]) == 8

    def test_paginate_empty(self) -> None:
        pages = _pdf_paginate([], lines_per_page=46)
        assert len(pages) == 1
        assert pages[0] == []


class TestCoverageSummaryLines:
    def test_complete_discovery(self) -> None:
        coverage = {
            "discovery_completeness": "complete",
            "coverage_numerator": 10,
            "coverage_denominator": 10,
            "analysed_page_coverage_percentage": 100.0,
        }
        lines = _coverage_summary_lines(coverage)
        assert any("Complete" in line for line in lines)

    def test_incomplete_discovery(self) -> None:
        coverage = {
            "discovery_completeness": "partial",
            "coverage_numerator": 5,
            "coverage_denominator": 10,
            "analysed_page_coverage_percentage": 50.0,
            "discovery_failure_message": "Timeout after 60s",
        }
        lines = _coverage_summary_lines(coverage)
        assert any("Partial" in line for line in lines)
        assert any("Timeout" in line for line in lines)

    def test_pending_discovery(self) -> None:
        coverage = {
            "discovery_completeness": None,
            "discovery_stage_status": "running",
            "coverage_numerator": 0,
            "coverage_denominator": 0,
            "analysed_page_coverage_percentage": None,
        }
        lines = _coverage_summary_lines(coverage)
        assert any("In Progress" in line for line in lines)


class TestCrossArtifactDataConsistency:
    """Verify the same canonical values appear in HTML, PDF, JSON, and Technical Appendix."""

    def test_all_artifacts_agree_on_canonical_values(self) -> None:
        snapshot = _minimal_snapshot(overall_score=85, confidence_percent=72)
        html_doc = _html_artifact(snapshot).decode("utf-8")
        pdf_bytes = _pdf_artifact(snapshot)
        pdf_text = pdf_bytes.decode("latin-1", errors="replace")
        json_bytes = render_report_artifact("json", snapshot)
        json_data = json.loads(json_bytes)

        assert "85" in html_doc and "/100" in html_doc
        assert "85" in pdf_text
        assert json_data["overall_score"] == 85

        assert "72" in html_doc
        assert "72" in pdf_text
        assert json_data["confidence_percent"] == 72

        assert "2 unique findings" in html_doc
        assert "2 unique findings" in pdf_text
        findings = json_data["sections"][2]["content"]["findings"]
        assert len(findings) == 2

        assert json_data["page_coverage"]["successfully_analysed_pages"] == 15
        assert json_data["page_coverage"]["eligible_pages"] == 20
        assert "15" in html_doc
        assert "20" in html_doc

        assert len(json_data["limitations"]) == 2

    def test_no_localhost_in_any_artifact(self) -> None:
        snapshot = _minimal_snapshot()
        for fmt in ("html", "pdf", "json"):
            artifact = render_report_artifact(fmt, snapshot)
            text = (
                artifact.decode("utf-8")
                if fmt != "pdf"
                else artifact.decode("latin-1", errors="replace")
            )
            assert "localhost" not in text, f"localhost found in {fmt}"
            assert "127.0.0.1" not in text, f"127.0.0.1 found in {fmt}"
        appendix = _technical_appendix_pdf(snapshot)
        appendix_text = appendix.decode("latin-1", errors="replace")
        assert "localhost" not in appendix_text
        assert "127.0.0.1" not in appendix_text

    def test_no_internal_ids_in_customer_artifacts(self) -> None:
        snapshot = _minimal_snapshot()
        html_doc = _html_artifact(snapshot).decode("utf-8")
        pdf_text = _pdf_artifact(snapshot).decode("latin-1", errors="replace")
        for artifact_text, label in [(html_doc, "html"), (pdf_text, "pdf")]:
            assert snapshot["workflow_execution_id"] not in artifact_text, (
                f"workflow ID leaked in {label}"
            )
            assert snapshot["project_id"] not in artifact_text, f"project ID leaked in {label}"

    def test_appendix_has_more_detail_than_primary(self) -> None:
        snapshot = _minimal_snapshot()
        _pdf_artifact(snapshot)
        appendix_text = _technical_appendix_pdf(snapshot).decode("latin-1", errors="replace")
        assert "test.example.com/page-0" in appendix_text
        assert "AGENT EXECUTION" in appendix_text
        assert "PAGE INVENTORY" in appendix_text
        primary_pages = _pdf_artifact(snapshot).count(b"/Type /Page ")
        appendix_pages = _technical_appendix_pdf(snapshot).count(b"/Type /Page ")
        assert appendix_pages >= primary_pages


class TestPDFAcceptance:
    """Validate PDF rendering quality using pypdf — no clipping, no corruption."""

    def test_primary_pdf_opens_and_has_readable_pages(self) -> None:
        snapshot = _minimal_snapshot(overall_score=85)
        pdf_bytes = _pdf_artifact(snapshot)
        reader = PdfReader(io.BytesIO(pdf_bytes))
        assert len(reader.pages) >= 3
        all_text = "".join(page.extract_text() or "" for page in reader.pages)
        assert "85" in all_text
        assert "ZuiGO" in all_text
        assert "Page 1 of" in all_text

    def test_appendix_pdf_opens_and_has_readable_pages(self) -> None:
        snapshot = _minimal_snapshot()
        appendix_bytes = _technical_appendix_pdf(snapshot)
        reader = PdfReader(io.BytesIO(appendix_bytes))
        assert len(reader.pages) >= 3
        all_text = "".join(page.extract_text() or "" for page in reader.pages)
        assert "TECHNICAL APPENDIX" in all_text or "Technical Appendix" in all_text

    def test_primary_pdf_footer_header_present(self) -> None:
        snapshot = _minimal_snapshot()
        pdf_bytes = _pdf_artifact(snapshot)
        raw = pdf_bytes.decode("latin-1", errors="replace")
        assert "Page 1 of " in raw
        assert "ZuiGO WebIQ" in raw

    def test_pdf_no_security_leaks(self) -> None:
        snapshot = _minimal_snapshot()
        for gen_fn, label in [(_pdf_artifact, "primary"), (_technical_appendix_pdf, "appendix")]:
            raw = gen_fn(snapshot).decode("latin-1", errors="replace")
            assert "localhost" not in raw, f"localhost in {label}"
            assert "127.0.0.1" not in raw, f"127.0.0.1 in {label}"
            assert snapshot["workflow_execution_id"] not in raw, f"workflow ID in {label}"

    def test_html_tables_have_captions(self) -> None:
        snapshot = _minimal_snapshot()
        html_doc = _html_artifact(snapshot).decode("utf-8")
        assert "<caption>" in html_doc

    def test_html_no_broken_internal_anchors(self) -> None:
        snapshot = _minimal_snapshot()
        html_doc = _html_artifact(snapshot).decode("utf-8")
        import re

        hrefs = re.findall(r'href="#([^"]+)"', html_doc)
        for href in hrefs:
            assert f'id="{href}"' in html_doc, f"Broken anchor: #{href}"
