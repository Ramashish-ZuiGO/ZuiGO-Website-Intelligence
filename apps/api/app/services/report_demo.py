import argparse
import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

# The demonstration imports the production renderer but never opens a database or
# broker connection. These explicit local placeholders satisfy import-time settings
# without overriding a configured environment.
os.environ.setdefault("POSTGRES_PASSWORD", "local-demo-unused")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6379/0")

from app.services.report_delivery import (
    AGENT_IDS,
    REPORT_VERSION,
    SECTION_AGENT_IDS,
    SECTION_DEFINITIONS,
    TEMPLATE_ID,
    TEMPLATE_VERSION,
    render_report_artifact,
)

DEMO_REPORT_ID = uuid.UUID("00000000-0000-4000-8000-000000000029")
DEMO_GENERATED_AT = "2026-07-28T09:00:00+00:00"


def _occurrence(
    url: str,
    *,
    page_type: str,
    selector: str | None,
    observed: str,
    expected: str,
    provider: str,
) -> dict[str, Any]:
    return {
        "normalized_url": url,
        "status_code": 200,
        "page_title": f"Demo {page_type.title()}",
        "page_type": page_type,
        "section": url.rstrip("/").rsplit("/", 1)[-1] or "root",
        "selector": selector,
        "resource_url": None,
        "location": selector or "document",
        "observed_value": observed,
        "expected_value": expected,
        "evidence_timestamp": DEMO_GENERATED_AT,
        "analysis_provider": provider,
        "analysis_provider_version": "1.0.0-demo",
        "artifact_reference": "demo-artifact:screenshot-001",
        "scope": "page",
    }


def _finding(
    code: str,
    title: str,
    *,
    category: str,
    severity: str,
    scope: str,
    agent_id: str,
    occurrences: list[dict[str, Any]],
    evidence_state: str = "available",
) -> dict[str, Any]:
    finding_id = str(uuid.uuid5(DEMO_REPORT_ID, f"finding:{code}"))
    return {
        "finding_id": finding_id,
        "finding_code": code,
        "finding_type": "demonstration",
        "issue_title": title,
        "plain_language_explanation": (
            f"Synthetic local evidence demonstrates how {title.casefold()} is explained."
        ),
        "technical_explanation": (
            "The deterministic fixture retains the observed and expected values for every "
            "affected location."
        ),
        "category": category,
        "severity": severity,
        "confidence": {"classification": "high", "percent": 92},
        "affected_pages": occurrences,
        "exact_occurrences": occurrences,
        "affected_page_count": len({item["normalized_url"] for item in occurrences}),
        "occurrence_count": len(occurrences),
        "evidence_references": [
            {
                "evidence_type": "demo_fixture",
                "evidence_id": code,
                "source": "local_synthetic",
            }
        ],
        "evidence_source": {
            "source": "local_synthetic",
            "provider": "zuigo_demo_fixture",
            "provider_version": "1.0.0",
        },
        "detecting_agent": agent_id,
        "validating_agent": "evidence_validation_agent",
        "likely_cause": (
            "A synthetic shared implementation condition is retained for demonstration."
        ),
        "technical_impact": "The demonstrated condition creates a measurable technical mismatch.",
        "business_impact": (
            "This fixture illustrates impact wording only; it does not claim real business loss."
        ),
        "recommended_remediation": "Correct the demonstrated source condition at its owner.",
        "responsible_role": "Frontend engineering",
        "estimated_effort_band": "small",
        "verification_procedure": (
            "Repeat the deterministic local check and confirm every occurrence matches the "
            "expected value."
        ),
        "related_finding_ids": [],
        "evidence_limitations": (
            "This is synthetic demonstration evidence and is not a real website conclusion."
        ),
        "evidence_state": evidence_state,
        "scope": scope,
    }


def _attribution(section_key: str) -> dict[str, Any]:
    agents = [
        {
            "agent_id": agent_id,
            "agent_version": "1.0.0",
            "execution_status": "completed",
            "tools_used": [f"{agent_id.removesuffix('_agent')}_demo_tool"],
            "allowed_tool_ids": [],
            "evidence_reference_count": 1,
            "limitations": "Synthetic demonstration execution only.",
        }
        for agent_id in SECTION_AGENT_IDS[section_key]
    ]
    return {
        "agents_involved": agents,
        "tools_used": sorted({tool for agent in agents for tool in agent["tools_used"]}),
        "execution_status": "completed",
        "evidence_produced": [
            {
                "evidence_type": "demo_fixture",
                "evidence_id": section_key,
                "source": "local_synthetic",
            }
        ],
        "unavailable_tools": ["approved_llm_completion"],
        "unavailable_providers": ["approved_llm_provider"],
        "fallback_behavior": "Deterministic local fixture content is used without an LLM.",
        "private_reasoning_included": False,
    }


def build_demonstration_snapshot() -> dict[str, Any]:
    home_occurrence = _occurrence(
        "https://demo.local/",
        page_type="home",
        selector="main img.hero",
        observed="Image has no alternative text",
        expected="Concise alternative text",
        provider="axe",
    )
    product_occurrences = [
        _occurrence(
            f"https://demo.local/products/{index}",
            page_type="product",
            selector="head > title",
            observed="Demo product",
            expected=f"Product {index} | Demo",
            provider="site_diagnostics",
        )
        for index in range(1, 4)
    ]
    findings = [
        _finding(
            "mixed_content_resource",
            "Secure page loads an insecure resource",
            category="security",
            severity="critical",
            scope="page",
            agent_id="performance_agent",
            occurrences=[home_occurrence],
        ),
        _finding(
            "image_alt_missing",
            "Meaningful image lacks alternative text",
            category="accessibility",
            severity="high",
            scope="page",
            agent_id="accessibility_agent",
            occurrences=[home_occurrence],
        ),
        _finding(
            "duplicate_title_group",
            "Product template repeats the same title",
            category="metadata_content",
            severity="medium",
            scope="template",
            agent_id="site_diagnostics_agent",
            occurrences=product_occurrences,
        ),
        _finding(
            "unavailable_field_performance",
            "Field performance evidence is unavailable",
            category="performance",
            severity="informational",
            scope="site",
            agent_id="performance_agent",
            occurrences=[home_occurrence],
            evidence_state="unavailable",
        ),
    ]
    finding_ids = [item["finding_id"] for item in findings]
    action = {
        "action_id": str(uuid.uuid5(DEMO_REPORT_ID, "action:1")),
        "priority_rank": 1,
        "title": "Remove the insecure resource reference",
        "severity": "critical",
        "priority_score": 94,
        "priority_formula_version": "1.0.0",
        "score_contribution": 4.5,
        "impact": "Removes the demonstrated transport-security mismatch.",
        "effort": "small",
        "responsible_role": "Frontend engineering",
        "affected_scope": {"page_count": 1, "final_url": "https://demo.local/"},
        "dependencies": [],
        "recommended_sequence": 1,
        "expected_measurable_outcome": (
            "No insecure resource requests in retained browser evidence."
        ),
        "verification_method": "Repeat browser analysis and inspect the same resource request.",
        "evidence_references": findings[0]["evidence_references"],
        "related_agents": ["performance_agent", "evidence_validation_agent", "remediation_agent"],
        "related_finding_ids": [findings[0]["finding_id"]],
        "status": "open",
    }
    agent_summary = [
        {
            "agent_id": agent_id,
            "agent_version": "1.0.0",
            "status": "completed",
            "tools_used": [f"{agent_id.removesuffix('_agent')}_demo_tool"],
            "evidence_produced": [
                {
                    "evidence_type": "demo_fixture",
                    "evidence_id": agent_id,
                    "source": "local_synthetic",
                }
            ],
            "fallback_behavior": "Deterministic local evidence; no provider call.",
        }
        for agent_id in AGENT_IDS
    ]
    content_by_section: dict[str, dict[str, Any]] = {
        "executive_summary": {
            "overall_health": "76/100",
            "strongest_areas": [{"category": "seo", "score": 91, "band": "strong"}],
            "most_serious_weaknesses": [
                {
                    "finding_id": findings[0]["finding_id"],
                    "title": findings[0]["issue_title"],
                    "severity": "critical",
                }
            ],
            "top_business_risks": [
                {
                    "finding_id": findings[1]["finding_id"],
                    "impact": findings[1]["business_impact"],
                }
            ],
            "top_technical_risks": [
                {
                    "finding_id": findings[0]["finding_id"],
                    "impact": findings[0]["technical_impact"],
                }
            ],
            "evidence_coverage": {"numerator": 15, "denominator": 16, "percentage": 93.75},
            "score_confidence_percent": 88,
            "five_most_important_actions": [action],
            "quick_wins": [action],
            "strategic_fixes": [],
            "unavailable_evidence": ["crux_field_evidence"],
            "multi_agent_execution_summary": agent_summary,
        },
        "scores": {
            "overall_score": 76,
            "categories": [
                {
                    "category_id": "performance",
                    "score": 68,
                    "contribution": 17.0,
                    "related_finding_ids": [findings[0]["finding_id"], findings[3]["finding_id"]],
                }
            ],
            "formula_id": "overall_score",
            "formula_version": "1.0.0",
            "calculated_by_llm": False,
        },
        "performance": {"findings": [findings[0], findings[3]], "field_and_lab_are_distinct": True},
        "accessibility": {
            "findings": [findings[1]],
            "automated_checks_establish_compliance": False,
            "manual_review_required": True,
        },
        "site_diagnostics": {
            "findings": [findings[2]],
            "coverage": {"processed_pages": 4, "total_pages": 4, "failed_pages": 0},
        },
        "internal_link_graph": {
            "findings": [],
            "limitations": "Synthetic graph covers four local pages only.",
        },
        "canonical_indexability": {
            "findings": [],
            "actual_search_engine_indexing_claimed": False,
        },
        "security_technical": {"findings": [findings[0]]},
        "content_seo": {"findings": [findings[2]]},
        "page_level_findings": {
            "finding_count": len(findings),
            "occurrence_count": sum(item["occurrence_count"] for item in findings),
            "findings": findings,
            "occurrences_are_capped": False,
        },
        "repeated_template_problems": {
            "findings": [findings[2]],
            "template_certainty_limited": True,
        },
        "priority_action_plan": {
            "actions": [action],
            "ordering": "priority_score_descending_then_stable_id",
            "priority_formula_version": "1.0.0",
        },
        "remediation": {
            "guidance": [
                {
                    "action_id": action["action_id"],
                    "recommended_remediation": findings[0]["recommended_remediation"],
                    "verification": findings[0]["verification_procedure"],
                    "responsible_role": findings[0]["responsible_role"],
                }
            ]
        },
        "coverage_confidence": {
            "report_coverage": {"numerator": 15, "denominator": 16, "percentage": 93.75},
            "score_confidence_percent": 88,
            "unavailable_findings": [findings[3]],
        },
        "multi_agent_execution": {
            "agent_count": 8,
            "expected_agent_ids": list(AGENT_IDS),
            "agents": agent_summary,
            "private_reasoning_included": False,
        },
        "methodology_limitations": {
            "overall_score_formula": {"version": "1.0.0", "unchanged": True},
            "priority_formula": {"version": "1.0.0", "unchanged": True},
            "report_version": REPORT_VERSION,
            "template_id": TEMPLATE_ID,
            "template_version": TEMPLATE_VERSION,
            "business_impact_policy": "Synthetic impacts are labelled and never claimed as fact.",
            "private_reasoning_included": False,
        },
    }
    sections = []
    for position, (section_key, title) in enumerate(SECTION_DEFINITIONS, 1):
        attribution = _attribution(section_key)
        sections.append(
            {
                "section_key": section_key,
                "title": title,
                "status": ("incomplete" if section_key == "performance" else "available"),
                "content": {
                    **content_by_section[section_key],
                    "agent_attribution": attribution,
                },
                "evidence_references": [
                    {
                        "evidence_type": "demo_fixture",
                        "evidence_id": section_key,
                        "source": "local_synthetic",
                    }
                ],
                "agent_attribution": attribution,
                "unavailable_reason": (
                    "CrUX field evidence is intentionally unavailable in this local fixture."
                    if section_key == "performance"
                    else None
                ),
                "position": position,
                "section_id": str(uuid.uuid5(DEMO_REPORT_ID, f"section:{section_key}")),
            }
        )
    return {
        "schema_version": REPORT_VERSION,
        "report_id": str(DEMO_REPORT_ID),
        "title": "ZuiGO deterministic demonstration report",
        "generated_at": DEMO_GENERATED_AT,
        "report_version": REPORT_VERSION,
        "template_version": TEMPLATE_VERSION,
        "project_id": str(uuid.uuid5(DEMO_REPORT_ID, "project")),
        "project_name": "Local presentation demonstration",
        "website_id": str(uuid.uuid5(DEMO_REPORT_ID, "website")),
        "website_name": "ZuiGO Demo",
        "website_url": "https://demo.local/",
        "analysis_run_id": str(uuid.uuid5(DEMO_REPORT_ID, "analysis")),
        "workflow_execution_id": str(uuid.uuid5(DEMO_REPORT_ID, "workflow")),
        "score_execution_id": str(uuid.uuid5(DEMO_REPORT_ID, "score")),
        "status": "partial",
        "overall_score": 76,
        "evidence_coverage": {"numerator": 15, "denominator": 16, "percentage": 93.75},
        "confidence_percent": 88,
        "sections": sections,
        "limitations": [
            "All evidence is synthetic and local.",
            "The approved LLM provider is intentionally unavailable.",
            "No private reasoning, secrets, or internal file paths are included.",
        ],
        "finding_ids": finding_ids,
    }


def write_demonstration_report(output_dir: Path) -> dict[str, dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    snapshot = build_demonstration_snapshot()
    manifest: dict[str, dict[str, Any]] = {}
    for artifact_format in ("html", "pdf", "json"):
        content = render_report_artifact(artifact_format, snapshot)
        path = output_dir / f"zuigo-demo-report.{artifact_format}"
        path.write_bytes(content)
        manifest[artifact_format] = {
            "path": str(path),
            "size_bytes": len(content),
            "checksum_sha256": hashlib.sha256(content).hexdigest(),
        }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate the deterministic local ZuiGO demonstration report."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".local-reports/task-029-demo"),
    )
    args = parser.parse_args()
    manifest = write_demonstration_report(args.output_dir)
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
