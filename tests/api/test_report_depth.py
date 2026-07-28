import hashlib
import json
from pathlib import Path

from app.services.priority import PRIORITY_FORMULA_VERSION
from app.services.report_delivery import (
    AGENT_IDS,
    REPORT_VERSION,
    SECTION_DEFINITIONS,
    render_report_artifact,
)
from app.services.report_demo import (
    build_demonstration_snapshot,
    write_demonstration_report,
)
from app.services.scoring_formula import CATEGORY_WEIGHTS, FORMULA_VERSION


def _demo_findings(snapshot: dict[str, object]) -> list[dict[str, object]]:
    sections = {
        section["section_key"]: section
        for section in snapshot["sections"]  # type: ignore[index]
    }
    return sections["page_level_findings"]["content"]["findings"]


def test_demonstration_fixture_finding_depth_occurrences_and_attribution() -> None:
    snapshot = build_demonstration_snapshot()
    assert snapshot["schema_version"] == REPORT_VERSION
    assert [section["section_key"] for section in snapshot["sections"]] == [
        key for key, _title in SECTION_DEFINITIONS
    ]
    findings = _demo_findings(snapshot)
    assert {finding["severity"] for finding in findings} == {
        "critical",
        "high",
        "medium",
        "informational",
    }
    required = {
        "issue_title",
        "plain_language_explanation",
        "technical_explanation",
        "category",
        "severity",
        "confidence",
        "affected_pages",
        "exact_occurrences",
        "evidence_references",
        "evidence_source",
        "detecting_agent",
        "validating_agent",
        "likely_cause",
        "technical_impact",
        "business_impact",
        "recommended_remediation",
        "responsible_role",
        "estimated_effort_band",
        "verification_procedure",
        "related_finding_ids",
        "evidence_limitations",
        "evidence_state",
        "scope",
    }
    assert all(required <= set(finding) for finding in findings)
    assert sum(len(finding["exact_occurrences"]) for finding in findings) == 6
    duplicate = next(
        finding for finding in findings if finding["finding_code"] == "duplicate_title_group"
    )
    assert len(duplicate["exact_occurrences"]) == 3
    assert all(
        {
            "normalized_url",
            "status_code",
            "page_title",
            "page_type",
            "section",
            "selector",
            "observed_value",
            "expected_value",
            "evidence_timestamp",
            "analysis_provider",
            "analysis_provider_version",
            "artifact_reference",
            "scope",
        }
        <= set(occurrence)
        for finding in findings
        for occurrence in finding["exact_occurrences"]
    )
    for section in snapshot["sections"]:
        attribution = section["content"]["agent_attribution"]
        assert attribution["fallback_behavior"]
        assert attribution["private_reasoning_included"] is False
        assert attribution["agents_involved"]
    multi_agent = next(
        section
        for section in snapshot["sections"]
        if section["section_key"] == "multi_agent_execution"
    )
    assert set(multi_agent["content"]["expected_agent_ids"]) == set(AGENT_IDS)
    assert len(AGENT_IDS) == 8


def test_executive_action_plan_score_links_and_formula_preservation() -> None:
    snapshot = build_demonstration_snapshot()
    sections = {section["section_key"]: section["content"] for section in snapshot["sections"]}
    executive = sections["executive_summary"]
    assert {
        "overall_health",
        "strongest_areas",
        "most_serious_weaknesses",
        "top_business_risks",
        "top_technical_risks",
        "evidence_coverage",
        "score_confidence_percent",
        "five_most_important_actions",
        "quick_wins",
        "strategic_fixes",
        "unavailable_evidence",
        "multi_agent_execution_summary",
    } <= set(executive)
    actions = sections["priority_action_plan"]["actions"]
    assert [action["priority_rank"] for action in actions] == list(range(1, len(actions) + 1))
    assert all(
        {
            "severity",
            "score_contribution",
            "impact",
            "effort",
            "responsible_role",
            "affected_scope",
            "dependencies",
            "recommended_sequence",
            "expected_measurable_outcome",
            "verification_method",
            "evidence_references",
            "related_agents",
            "related_finding_ids",
        }
        <= set(action)
        for action in actions
    )
    score_links = {
        finding_id
        for category in sections["scores"]["categories"]
        for finding_id in category["related_finding_ids"]
    }
    action_links = {
        finding_id for action in actions for finding_id in action["related_finding_ids"]
    }
    assert score_links
    assert action_links
    assert FORMULA_VERSION == PRIORITY_FORMULA_VERSION == "1.0.0"
    assert CATEGORY_WEIGHTS == {
        "performance": 25,
        "accessibility": 20,
        "best_practices": 15,
        "seo": 20,
        "technical_quality": 20,
    }


def test_accessible_html_pdf_metadata_order_safety_and_determinism() -> None:
    snapshot = build_demonstration_snapshot()
    snapshot["limitations"].extend(
        [
            "password=do-not-expose",
            "chain_of_thought should never be shown",
            "C:\\Users\\private\\report.txt",
        ]
    )
    first = {
        artifact_format: render_report_artifact(artifact_format, snapshot)
        for artifact_format in ("html", "pdf", "json")
    }
    repeated = {
        artifact_format: render_report_artifact(artifact_format, snapshot)
        for artifact_format in ("html", "pdf", "json")
    }
    assert first == repeated
    html = first["html"].decode()
    assert '<html lang="en">' in html
    assert '<nav aria-label="Report sections">' in html
    assert "<main>" in html
    assert "<caption>" in html
    assert "focus{outline" in html
    assert "ZuiGO Website Intelligence" in html
    assert "Page-level occurrences" in html
    assert "do-not-expose" not in html
    assert "chain_of_thought" not in html
    assert "Users\\private" not in html
    pdf = first["pdf"]
    assert pdf.startswith(b"%PDF-1.4")
    assert b"/Author (ZuiGO Website Intelligence)" in pdf
    assert b"Report version: 1.1.0" in pdf
    assert b"Page 1 of " in pdf
    positions = [pdf.find(title.encode()) for _key, title in SECTION_DEFINITIONS]
    assert positions == sorted(positions)
    payload = json.loads(first["json"])
    assert payload["limitations"][-3:] == [
        "[REDACTED]",
        "[PRIVATE REASONING OMITTED]",
        "[INTERNAL PATH OMITTED]",
    ]


def test_demonstration_report_writer_outputs_verified_local_artifacts(
    tmp_path: Path,
) -> None:
    first = write_demonstration_report(tmp_path)
    second = write_demonstration_report(tmp_path)
    assert first == second
    assert set(first) == {"html", "pdf", "json"}
    for details in first.values():
        path = Path(details["path"])
        content = path.read_bytes()
        assert details["size_bytes"] == len(content)
        assert details["checksum_sha256"] == hashlib.sha256(content).hexdigest()
    assert json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8")) == first
