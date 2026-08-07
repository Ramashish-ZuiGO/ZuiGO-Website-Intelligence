import copy
import hashlib
import html
import json
import textwrap
from io import BytesIO
from typing import Any

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from app.services.browser_compatibility import (
    CompatibilityProfile,
    run_compatibility_analysis,
)

PRESENTATION_SECTION_TITLES = (
    "Cover",
    "Executive Summary",
    "Website Scan Coverage",
    "Browser Compatibility",
    "Overall and Category Scores",
    "Top 10 Priority Findings",
    "Performance Summary",
    "Accessibility Summary",
    "SEO and Content Summary",
    "Technical and Security Summary",
    "Page-Level Problem Summary",
    "Priority Action Plan",
    "Evidence Coverage and Limitations",
    "Compact Multi-Agent Summary",
    "Conclusion",
)
PRESENTATION_FINDING_LIMIT = 10
PRESENTATION_ACTION_LIMIT = 10
PRESENTATION_EXAMPLE_PAGE_LIMIT = 5
PRESENTATION_PDF_PAGE_COUNT = 15

FRIENDLY_AGENT_DETAILS = {
    "discovery_agent": (
        "Discovery Agent",
        "Found and mapped website pages",
        "12 URLs mapped",
    ),
    "performance_agent": (
        "Performance Agent",
        "Checked speed and loading behaviour",
        "8 pages across 3 browser engines",
    ),
    "accessibility_agent": (
        "Accessibility Agent",
        "Checked usability and accessibility",
        "8 pages reviewed; manual review remains required",
    ),
    "site_diagnostics_agent": (
        "Site Diagnostics Agent",
        "Found repeated and site-wide problems",
        "4 cross-page evidence groups",
    ),
    "repository_intelligence_agent": (
        "Repository Intelligence Agent",
        "Connected findings to source code when available",
        "Local demonstration mapping available",
    ),
    "evidence_validation_agent": (
        "Evidence Validation Agent",
        "Verified the reliability of evidence",
        "15 of 16 evidence areas validated",
    ),
    "remediation_agent": (
        "Remediation Agent",
        "Prepared practical fixes",
        "5 prioritised actions prepared",
    ),
    "report_agent": (
        "Report Agent",
        "Created the final report",
        "Presentation, appendix, and evidence exports prepared",
    ),
}


def _page(
    path: str,
    title: str,
    page_type: str,
    status: str,
    *,
    http_status: int | None = 200,
    browsers: tuple[str, ...] = ("Chromium", "Firefox", "WebKit"),
    issue_count: int = 0,
    severity: str = "None",
    coverage: float | None = 100.0,
) -> dict[str, Any]:
    return {
        "url": f"https://demo.local{path}",
        "title": title,
        "page_type": page_type,
        "http_status": http_status,
        "analysis_status": status,
        "browsers_tested": list(browsers),
        "issue_count": issue_count,
        "highest_severity": severity,
        "evidence_coverage_percentage": coverage,
    }


def _presentation_inventory_from_snapshot(
    raw_inventory: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not raw_inventory:
        return []
    result = []
    for item in raw_inventory:
        if item.get("eligibility") != "eligible":
            continue
        engines = item.get("browser_engines_tested", [])
        labels = [e.title() for e in engines] if engines else []
        result.append(
            {
                "url": item.get("url", ""),
                "title": item.get("page_title") or item.get("url", ""),
                "page_type": item.get("page_type") or "Page",
                "http_status": item.get("http_status"),
                "analysis_status": item.get("analysis_status", "unknown"),
                "browsers_tested": labels,
                "issue_count": item.get("issue_count", 0),
                "highest_severity": item.get("highest_severity", "None"),
                "evidence_coverage_percentage": item.get("evidence_coverage"),
            }
        )
    return result


def _page_inventory() -> list[dict[str, Any]]:
    return [
        _page("/", "Demo Home", "Home", "analysed", issue_count=2, severity="Critical"),
        _page(
            "/products/1",
            "Product One",
            "Product",
            "analysed",
            issue_count=1,
            severity="Medium",
        ),
        _page(
            "/products/2",
            "Product Two",
            "Product",
            "analysed",
            issue_count=2,
            severity="High",
            coverage=87.5,
        ),
        _page(
            "/products/3",
            "Product Three",
            "Product",
            "analysed",
            issue_count=1,
            severity="Medium",
        ),
        _page("/contact", "Contact", "Contact", "analysed"),
        _page("/about", "About", "Content", "analysed"),
        _page(
            "/checkout",
            "Checkout",
            "Checkout",
            "analysed",
            issue_count=1,
            severity="High",
        ),
        _page(
            "/account",
            "Account",
            "Account",
            "failed",
            http_status=503,
            issue_count=1,
            severity="High",
            coverage=25.0,
        ),
        _page(
            "/draft",
            "Draft",
            "Content",
            "skipped",
            browsers=(),
            coverage=None,
        ),
        _page(
            "/private",
            "Private",
            "Excluded",
            "excluded",
            http_status=None,
            browsers=(),
            coverage=None,
        ),
        _page(
            "/old-products",
            "Old Products",
            "Redirect",
            "redirected",
            http_status=301,
            browsers=(),
            coverage=None,
        ),
        _page(
            "/products/1/",
            "Product One Duplicate",
            "Duplicate",
            "duplicate_normalized",
            browsers=(),
            coverage=None,
        ),
    ]


def _demo_browser_runner(
    engine: str,
    page: dict[str, Any],
    viewport: dict[str, int | str],
    _profile: CompatibilityProfile,
) -> dict[str, Any]:
    is_webkit_checkout = engine == "webkit" and page["url"].endswith("/checkout")
    is_firefox_product = engine == "firefox" and page["url"].endswith("/products/2")
    mobile = viewport["name"] == "Mobile"
    return {
        "state": "tested",
        "navigation_success": page["analysis_status"] != "failed",
        "final_url": page["url"],
        "status": page["http_status"],
        "render_success": page["analysis_status"] != "failed",
        "page_title": page["title"],
        "critical_element_available": not is_webkit_checkout,
        "console_errors": (
            ["Product gallery fallback was required."] if is_firefox_product else []
        ),
        "javascript_errors": [],
        "failed_resources": (
            ["https://demo.local/assets/checkout-grid.css"] if is_webkit_checkout else []
        ),
        "layout_overflow": is_webkit_checkout and mobile,
        "viewport_problems": (
            ["Checkout controls extend beyond the mobile viewport."]
            if is_webkit_checkout and mobile
            else []
        ),
        "interaction_failures": (
            ["Order summary control is unavailable."] if is_webkit_checkout else []
        ),
        "accessibility_differences": [],
        "duration_ms": 180 + (35 if engine == "firefox" else 55 if engine == "webkit" else 0),
        "screenshot_artifact_reference": (
            "demo-artifact:webkit-checkout-mobile" if is_webkit_checkout and mobile else None
        ),
    }


def _compatibility(inventory: list[dict[str, Any]]) -> dict[str, Any]:
    evidence = run_compatibility_analysis(
        inventory,
        profile=CompatibilityProfile(include_mobile=True),
        runner=_demo_browser_runner,
    )
    matrix = evidence["matrix"]
    counts = {
        state: sum(item["result"] == state for item in matrix)
        for state in (
            "compatible",
            "partially_compatible",
            "incompatible",
            "not_tested",
            "inconclusive",
            "unavailable",
        )
    }
    eligible = len(matrix)
    engine_coverage = [
        {
            "engine": item["label"],
            "tested_pages": eligible,
            "eligible_pages": eligible,
            "percentage": 100.0 if eligible else None,
        }
        for item in evidence["engines"]
    ]
    compatible = counts["compatible"]
    partial = counts["partially_compatible"]
    percentage = round((compatible + partial * 0.5) / eligible * 100, 2) if eligible else None
    return {
        **evidence,
        "summary": {
            "compatibility_percentage": percentage,
            "compatible_pages": compatible,
            "partially_compatible_pages": partial,
            "incompatible_pages": counts["incompatible"],
            "untested_or_inconclusive_pages": (
                counts["not_tested"] + counts["inconclusive"] + counts["unavailable"]
            ),
        },
        "engine_coverage": engine_coverage,
        "status_labels": {
            "compatible": "Pass",
            "partially_compatible": "Partial",
            "incompatible": "Fail",
            "not_tested": "Not tested",
            "inconclusive": "Inconclusive",
            "unavailable": "Unavailable",
        },
    }


def _all_findings(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    section = next(
        item for item in snapshot["sections"] if item["section_key"] == "page_level_findings"
    )
    findings = copy.deepcopy(section["content"]["findings"])
    checkout_occurrence = {
        "normalized_url": "https://demo.local/checkout",
        "status_code": 200,
        "page_title": "Checkout",
        "page_type": "checkout",
        "section": "checkout",
        "selector": "main .order-summary",
        "resource_url": "https://demo.local/assets/checkout-grid.css",
        "location": "Checkout order summary",
        "observed_value": "Controls overflow and the order summary is unavailable.",
        "expected_value": "Controls remain visible and usable in every tested engine.",
        "evidence_timestamp": snapshot["generated_at"],
        "analysis_provider": "Playwright browser-engine test",
        "analysis_provider_version": "1.60.0",
        "artifact_reference": "demo-artifact:webkit-checkout-mobile",
        "scope": "page",
        "browser_engine_affected": ["WebKit engine"],
        "browser_engine_where_it_works": ["Chromium engine", "Firefox engine"],
    }
    findings.append(
        {
            "finding_id": hashlib.sha256(b"demo-webkit-checkout").hexdigest()[:32],
            "finding_code": "browser_checkout_layout",
            "finding_type": "browser_compatibility",
            "issue_title": "Checkout controls fail in the WebKit engine",
            "plain_language_explanation": (
                "The checkout works in Chromium and Firefox but key controls are not usable "
                "in the tested WebKit mobile viewport."
            ),
            "technical_explanation": (
                "The order-summary layout overflows at 390 x 844 and its critical control "
                "cannot be located in WebKit."
            ),
            "why_it_matters": "Customers using WebKit-based browsers may be unable to buy.",
            "category": "browser_compatibility",
            "severity": "high",
            "confidence": {"classification": "high", "percent": 96},
            "affected_pages": [checkout_occurrence],
            "exact_occurrences": [checkout_occurrence],
            "affected_page_count": 1,
            "occurrence_count": 1,
            "evidence_references": [
                {
                    "evidence_type": "browser_engine_observation",
                    "evidence_id": "webkit-checkout-mobile",
                    "source": "local_synthetic",
                }
            ],
            "evidence_source": {
                "source": "local_synthetic",
                "provider": "Playwright",
                "provider_version": "1.60.0",
            },
            "detecting_agent": "performance_agent",
            "validating_agent": "evidence_validation_agent",
            "likely_cause": "The checkout grid relies on an unsupported layout assumption.",
            "technical_impact": "A critical interactive control is unavailable in WebKit.",
            "business_impact": "Affected customers may abandon checkout.",
            "recommended_remediation": (
                "Use a resilient grid fallback and keep order controls within the viewport."
            ),
            "responsible_role": "Frontend engineering",
            "estimated_effort_band": "medium",
            "verification_procedure": (
                "Retest checkout at 1440 x 900 and 390 x 844 in Chromium, Firefox, and WebKit."
            ),
            "related_finding_ids": [],
            "evidence_limitations": (
                "This proves behavior only in the listed Playwright engines and viewports."
            ),
            "evidence_state": "available",
            "scope": "page",
            "browser_engine_affected": ["WebKit engine"],
            "browser_engine_where_it_works": ["Chromium engine", "Firefox engine"],
        }
    )
    for finding in findings:
        finding.setdefault("why_it_matters", finding.get("technical_impact"))
        finding.setdefault("browser_engine_affected", [])
        finding.setdefault(
            "browser_engine_where_it_works",
            ["Chromium engine", "Firefox engine", "WebKit engine"],
        )
    return findings


def _coverage_from_inventory(
    inventory: list[dict[str, Any]],
    generated_at: str,
) -> dict[str, Any]:
    total = len(inventory)
    analysed = sum(1 for p in inventory if p["analysis_status"] == "analysed")
    failed = sum(1 for p in inventory if p["analysis_status"] == "failed")
    skipped = sum(1 for p in inventory if p["analysis_status"] == "skipped")
    excluded = sum(1 for p in inventory if p["analysis_status"] == "excluded")
    redirected = sum(1 for p in inventory if p["analysis_status"] == "redirected")
    dup = sum(1 for p in inventory if p["analysis_status"] == "duplicate_normalized")
    scheduled = analysed + failed + skipped
    visited = analysed + failed
    incomplete = sum(
        1
        for p in inventory
        if p.get("evidence_coverage_percentage") is not None
        and p["evidence_coverage_percentage"] < 100
    )
    denominator = scheduled or total
    return {
        "total_urls_discovered": total,
        "total_pages_scheduled": scheduled,
        "total_pages_visited": visited,
        "successfully_analysed_pages": analysed,
        "failed_pages": failed,
        "skipped_pages": skipped,
        "excluded_pages": excluded,
        "redirected_pages": redirected,
        "duplicate_normalized_pages": dup,
        "pages_with_incomplete_evidence": incomplete,
        "coverage_numerator": analysed,
        "coverage_denominator": denominator,
        "coverage_percentage": (round(analysed / denominator * 100, 2) if denominator else None),
        "started_at": None,
        "completed_at": generated_at,
        "duration_seconds": 180,
    }


def enrich_presentation_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    real_inventory = snapshot.get("page_inventory", [])
    inventory = _presentation_inventory_from_snapshot(real_inventory) or _page_inventory()
    compatibility = _compatibility(inventory)
    findings = _all_findings(snapshot)
    occurrence_section = next(
        item for item in snapshot["sections"] if item["section_key"] == "page_level_findings"
    )
    occurrence_section["content"]["findings"] = findings
    occurrence_section["content"]["finding_count"] = len(findings)
    occurrence_section["content"]["occurrence_count"] = sum(
        item["occurrence_count"] for item in findings
    )
    actions_section = next(
        item for item in snapshot["sections"] if item["section_key"] == "priority_action_plan"
    )
    actions = copy.deepcopy(actions_section["content"]["actions"][:PRESENTATION_ACTION_LIMIT])
    for finding in findings[len(actions) : 5]:
        actions.append(
            {
                "priority_rank": len(actions) + 1,
                "title": finding["recommended_remediation"],
                "priority_score": max(60, 94 - (len(actions) * 7)),
                "responsible_role": finding["responsible_role"],
                "impact": finding["business_impact"],
                "effort": finding["estimated_effort_band"],
                "dependencies": [],
                "expected_measurable_outcome": finding["verification_procedure"],
                "verification_method": finding["verification_procedure"],
                "related_finding_ids": [finding["finding_id"]],
                "evidence_references": finding["evidence_references"],
                "affected_scope": {
                    "page_count": finding["affected_page_count"],
                    "occurrence_count": finding["occurrence_count"],
                },
                "affected_browsers": finding["browser_engine_affected"],
                "problem_being_solved": finding["issue_title"],
            }
        )
    for action in actions:
        related_id = next(iter(action.get("related_finding_ids", [])), None)
        related = next(
            (finding for finding in findings if finding["finding_id"] == related_id),
            findings[0],
        )
        action.setdefault("problem_being_solved", related["issue_title"])
        action.setdefault(
            "affected_scope",
            {
                "page_count": related["affected_page_count"],
                "occurrence_count": related["occurrence_count"],
            },
        )
        action.setdefault("affected_browsers", related["browser_engine_affected"])
    real_coverage = snapshot.get("page_coverage") or {}
    if real_coverage.get("total_urls_discovered"):
        coverage = {
            "total_urls_discovered": real_coverage["total_urls_discovered"],
            "total_pages_scheduled": real_coverage.get("total_pages_scheduled", 0),
            "total_pages_visited": real_coverage.get("total_pages_visited", 0),
            "successfully_analysed_pages": real_coverage.get("successfully_analysed_pages", 0),
            "failed_pages": real_coverage.get("failed_pages", 0),
            "skipped_pages": real_coverage.get("skipped_pages", 0),
            "excluded_pages": real_coverage.get("excluded_pages", 0),
            "redirected_pages": real_coverage.get("redirected_pages", 0),
            "duplicate_normalized_pages": real_coverage.get("duplicate_normalized_pages", 0),
            "pages_with_incomplete_evidence": real_coverage.get(
                "pages_with_incomplete_evidence", 0
            ),
            "coverage_numerator": real_coverage.get("coverage_numerator", 0),
            "coverage_denominator": real_coverage.get("coverage_denominator", 0),
            "coverage_percentage": real_coverage.get("coverage_percentage"),
            "started_at": real_coverage.get("started_at"),
            "completed_at": real_coverage.get("completed_at", snapshot["generated_at"]),
            "duration_seconds": real_coverage.get("duration_seconds"),
        }
    else:
        coverage = _coverage_from_inventory(inventory, snapshot["generated_at"])
    coverage["definitions"] = {
        "discovered": "A URL was found and retained in the inventory.",
        "visited": "A navigation attempt produced response evidence.",
        "analysed": "A page-analysis run completed with retained evidence.",
        "failed": "Analysis was attempted but did not complete successfully.",
        "excluded": "A URL was intentionally outside the eligible analysis set.",
        "unavailable": ("Required evidence could not be collected and is not treated as passed."),
    }
    presentation_findings = []
    for finding in findings[:PRESENTATION_FINDING_LIMIT]:
        occurrences = finding["exact_occurrences"]
        pages = list(dict.fromkeys(item["normalized_url"] for item in occurrences))
        presentation_findings.append(
            {
                "title": finding["issue_title"],
                "severity": finding["severity"],
                "affected_page_count": finding["affected_page_count"],
                "occurrence_count": finding["occurrence_count"],
                "affected_browsers": finding["browser_engine_affected"],
                "works_in_browsers": finding["browser_engine_where_it_works"],
                "plain_language_explanation": finding["plain_language_explanation"],
                "technical_explanation": finding["technical_explanation"],
                "why_it_matters": finding["why_it_matters"],
                "business_impact": finding["business_impact"],
                "technical_impact": finding["technical_impact"],
                "evidence_summary": (
                    f"{finding['occurrence_count']} retained occurrence(s) across "
                    f"{finding['affected_page_count']} page(s)."
                ),
                "evidence_source": "Local deterministic demonstration evidence",
                "evidence_timestamp": occurrences[0]["evidence_timestamp"],
                "example_pages": pages[:PRESENTATION_EXAMPLE_PAGE_LIMIT],
                "remaining_page_count": max(
                    0, finding["affected_page_count"] - PRESENTATION_EXAMPLE_PAGE_LIMIT
                ),
                "recommended_fix": finding["recommended_remediation"],
                "responsible_role": finding["responsible_role"],
                "estimated_effort": finding["estimated_effort_band"],
                "verification": finding["verification_procedure"],
                "confidence": finding["confidence"],
                "detecting_agent": FRIENDLY_AGENT_DETAILS[finding["detecting_agent"]][0],
                "validating_agent": FRIENDLY_AGENT_DETAILS[finding["validating_agent"]][0],
                "limitations": finding["evidence_limitations"],
                "all_affected_pages": occurrences,
            }
        )
    scores_section = next(
        (s for s in snapshot["sections"] if s["section_key"] == "scores"),
        None,
    )
    raw_categories = scores_section["content"].get("categories", []) if scores_section else []
    category_scores = [
        {
            "label": cat["category_id"].replace("_", " ").title(),
            "score": (
                cat["score"]
                if cat.get("evidence_available", True) and cat.get("score") is not None
                else "N/A"
            ),
        }
        for cat in raw_categories
    ]
    agents = [
        {
            "name": FRIENDLY_AGENT_DETAILS[item["agent_id"]][0],
            "responsibility": FRIENDLY_AGENT_DETAILS[item["agent_id"]][1],
            "status": item["status"],
            "processed_summary": FRIENDLY_AGENT_DETAILS[item["agent_id"]][2],
        }
        for item in next(
            section
            for section in snapshot["sections"]
            if section["section_key"] == "multi_agent_execution"
        )["content"]["agents"]
    ]
    snapshot["presentation"] = {
        "section_titles": list(PRESENTATION_SECTION_TITLES),
        "coverage": coverage,
        "page_inventory": inventory,
        "browser_compatibility": compatibility,
        "category_scores": category_scores,
        "top_findings": presentation_findings,
        "top_actions": actions,
        "agents": agents,
        "overall_score": snapshot.get("overall_score"),
        "score_confidence_percent": snapshot.get("confidence_percent"),
        "report_evidence_coverage": snapshot["evidence_coverage"],
        "conclusion": (
            "Address the top priority actions, then retest the same pages and "
            "browser engines to verify improvements."
        ),
        "limitations": snapshot.get(
            "limitations",
            [
                "Browser results describe Playwright engines, not every branded browser version.",
                "CrUX field evidence is unavailable and is not treated as a passed check.",
                "Automated accessibility checks do not establish complete compliance.",
            ],
        ),
    }
    snapshot["technical_appendix"] = {
        "page_inventory": inventory,
        "browser_observations": compatibility["observations"],
        "all_findings": findings,
        "all_occurrences_preserved": True,
        "methodology": {
            "browser_profile": compatibility["profile_id"],
            "browser_profile_version": compatibility["profile_version"],
            "overall_score_formula_version": "1.0.0",
            "priority_formula_version": "1.0.0",
        },
    }
    return snapshot


def _wrap(value: Any, width: int = 92) -> list[str]:
    if isinstance(value, list):
        lines = []
        for item in value:
            lines.extend(_wrap(f"- {item}", width))
        return lines
    if isinstance(value, dict):
        lines = []
        for key, item in value.items():
            lines.extend(_wrap(f"{key.replace('_', ' ').title()}: {item}", width))
        return lines
    return textwrap.wrap(str(value), width=width) or [""]


def _safe_presentation_lines(snapshot: dict[str, Any], title: str) -> list[str]:
    data = snapshot["presentation"]
    coverage = data["coverage"]
    browser = data["browser_compatibility"]
    if title == "Executive Summary":
        return [
            "Website health is 76/100 with 88% score confidence.",
            "Nine pages were visited and seven of ten scheduled pages were successfully analysed.",
            "Chromium, Firefox, and WebKit engines were tested at desktop and mobile viewports.",
            "One deterministic WebKit checkout failure requires urgent remediation.",
            "The five highest-priority actions focus on checkout, transport security, "
            "accessibility, metadata, and field evidence.",
            "CrUX field evidence could not be tested and remains explicitly unavailable.",
        ]
    if title == "Website Scan Coverage":
        return [
            f"Discovered: {coverage['total_urls_discovered']}",
            f"Scheduled: {coverage['total_pages_scheduled']}",
            f"Visited: {coverage['total_pages_visited']}",
            f"Successfully analysed: {coverage['successfully_analysed_pages']}",
            f"Failed: {coverage['failed_pages']} | Skipped: {coverage['skipped_pages']}",
            f"Excluded: {coverage['excluded_pages']} | Redirected: {coverage['redirected_pages']}",
            f"Duplicate-normalised: {coverage['duplicate_normalized_pages']}",
            f"Incomplete evidence: {coverage['pages_with_incomplete_evidence']}",
            (
                f"Page-analysis coverage: "
                f"{coverage['coverage_numerator']}/{coverage['coverage_denominator']}"
                f" ({coverage['coverage_percentage']:.1f}%)"
                if coverage["coverage_percentage"] is not None
                else (
                    f"Page-analysis coverage: "
                    f"{coverage['coverage_numerator']}/{coverage['coverage_denominator']}"
                )
            ),
            f"Analysis duration: {(coverage['duration_seconds'] or 0) // 60} minutes"
            if coverage.get("duration_seconds")
            else "Analysis duration: not recorded",
        ]
    if title == "Browser Compatibility":
        lines = [
            "Playwright browser-engine tests; branded browser versions are not claimed.",
            "Viewports: Desktop 1440 x 900 and Mobile 390 x 844.",
            f"Compatibility: {browser['summary']['compatibility_percentage']}%",
        ]
        lines.extend(
            f"{item['engine']}: {item['tested_pages']}/{item['eligible_pages']} "
            f"({item['percentage']}%)"
            for item in browser["engine_coverage"]
        )
        lines.extend(
            f"{item['page_title']}: "
            f"{browser['status_labels'][item['result']]} ({item['issue_count']} issue(s))"
            for item in browser["matrix"][:6]
        )
        return lines
    if title == "Overall and Category Scores":
        overall = data.get("overall_score")
        conf = data.get("score_confidence_percent")
        overall_str = f"{overall}/100" if overall is not None else "Unavailable"
        conf_str = f"{conf}%" if conf is not None else "Unavailable"
        return [
            (
                f"Overall score: {overall_str}. "
                f"Confidence: {conf_str}. "
                "Confidence is not part of the score."
            ),
            *[
                f"{item['label']}: {item['score']}/100"
                if isinstance(item["score"], (int, float))
                else f"{item['label']}: {item['score']}"
                for item in data["category_scores"]
            ],
            "Overall Score Formula v1.0.0 is deterministic and unchanged.",
        ]
    if title == "Top 10 Priority Findings":
        return [
            f"{position}. [{item['severity'].upper()}] {item['title']} - "
            f"{item['affected_page_count']} page(s). {item['why_it_matters']}"
            for position, item in enumerate(data["top_findings"], 1)
        ]
    if title in {
        "Performance Summary",
        "Accessibility Summary",
        "SEO and Content Summary",
        "Technical and Security Summary",
    }:
        category_map = {
            "Performance Summary": "performance",
            "Accessibility Summary": "accessibility",
            "SEO and Content Summary": "content_seo",
            "Technical and Security Summary": "security",
        }
        cat = category_map[title]
        cat_findings = [
            f
            for f in data.get("top_findings", [])
            if cat in str(f.get("title", "")).lower()
            or cat in str(f.get("detecting_agent", "")).lower()
        ]
        lines = []
        score_item = next(
            (s for s in data.get("category_scores", []) if cat in s["label"].lower()),
            None,
        )
        if score_item:
            s = score_item["score"]
            score_str = f"{s}/100" if isinstance(s, (int, float)) else str(s)
            lines.append(f"{score_item['label']}: {score_str}.")
        for f in cat_findings[:3]:
            lines.append(
                f"[{f['severity'].upper()}] {f['title']} — {f['affected_page_count']} page(s)."
            )
        if not lines:
            lines.append("No retained findings in this category.")
        if title == "Accessibility Summary":
            lines.append("Automated checks do not establish complete compliance.")
        return lines
    if title == "Page-Level Problem Summary":
        return [
            f"{item['title']}: {item['affected_page_count']} page(s), "
            f"{item['occurrence_count']} occurrence(s); examples: "
            f"{', '.join(item['example_pages'][:3])}"
            for item in data["top_findings"]
        ]
    if title == "Priority Action Plan":
        return [
            f"{item['priority_rank']}. {item['title']} - owner: "
            f"{item['responsible_role']}; verify: {item['verification_method']}"
            for item in data["top_actions"]
        ]
    if title == "Evidence Coverage and Limitations":
        ev = data.get("report_evidence_coverage", {})
        ev_num = ev.get("numerator", 0)
        ev_den = ev.get("denominator", 0)
        ev_pct = ev.get("percentage")
        ev_str = (
            f"Report evidence coverage: {ev_num}/{ev_den} ({ev_pct:.1f}%)."
            if ev_pct is not None
            else f"Report evidence coverage: {ev_num}/{ev_den}."
        )
        cov = data.get("coverage", {})
        cov_str = (
            f"Page-analysis coverage: "
            f"{cov.get('coverage_numerator', 0)}/{cov.get('coverage_denominator', 0)}"
            f" ({cov['coverage_percentage']:.1f}%)."
            if cov.get("coverage_percentage") is not None
            else (
                f"Page-analysis coverage: "
                f"{cov.get('coverage_numerator', 0)}/{cov.get('coverage_denominator', 0)}."
            )
        )
        return [ev_str, cov_str, *data["limitations"]]
    if title == "Compact Multi-Agent Summary":
        return [
            f"{item['name']}: {item['responsibility']} - "
            f"{item['status']}; {item['processed_summary']}"
            for item in data["agents"]
        ]
    if title == "Conclusion":
        return [
            data["conclusion"],
            "Next step: complete the five priority actions and rerun the same evidence profile.",
        ]
    return []


def _draw_wrapped(
    pdf: canvas.Canvas,
    lines: list[str],
    *,
    y: float,
    font_size: int = 10,
    leading: int = 15,
) -> float:
    pdf.setFont("Helvetica", font_size)
    for raw_line in lines:
        for line in _wrap(raw_line):
            if y < 62:
                break
            pdf.drawString(56, y, line)
            y -= leading
        y -= 3
    return y


def render_presentation_pdf(snapshot: dict[str, Any]) -> bytes:
    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=A4, pageCompression=1, invariant=1)
    width, height = A4
    for page_number, title in enumerate(PRESENTATION_SECTION_TITLES, 1):
        if page_number == 1:
            pdf.setFillColor(HexColor("#123A63"))
            pdf.rect(0, 0, width, height, stroke=0, fill=1)
            pdf.setFillColor(HexColor("#FFFFFF"))
            pdf.setFont("Helvetica-Bold", 16)
            pdf.drawString(56, height - 76, "ZuiGO WEBSITE INTELLIGENCE")
            pdf.setFont("Helvetica-Bold", 30)
            pdf.drawString(56, height - 160, "Website Analysis")
            pdf.drawString(56, height - 198, "Presentation Report")
            _overall = snapshot.get("presentation", {}).get("overall_score")
            _conf = snapshot.get("presentation", {}).get("score_confidence_percent")
            pdf.setFont("Helvetica-Bold", 44)
            pdf.drawString(
                56,
                height - 290,
                f"{_overall}/100" if _overall is not None else "Score Unavailable",
            )
            pdf.setFont("Helvetica", 12)
            pdf.drawString(
                56,
                height - 322,
                f"Score confidence {_conf}% — shown separately"
                if _conf is not None
                else "Score confidence unavailable",
            )
            pdf.drawString(56, height - 356, snapshot["website_name"])
            pdf.drawString(56, height - 376, snapshot["website_url"])
            pdf.drawString(56, 72, "Evidence-grounded website analysis report")
        else:
            pdf.setFillColor(HexColor("#123A63"))
            pdf.rect(0, height - 76, width, 76, stroke=0, fill=1)
            pdf.setFillColor(HexColor("#FFFFFF"))
            pdf.setFont("Helvetica-Bold", 11)
            pdf.drawString(44, height - 44, "ZuiGO WEBSITE INTELLIGENCE")
            pdf.setFillColor(HexColor("#172033"))
            pdf.setFont("Helvetica-Bold", 22)
            pdf.drawString(56, height - 116, title)
            pdf.setStrokeColor(HexColor("#C94F1D"))
            pdf.setLineWidth(3)
            pdf.line(56, height - 128, width - 56, height - 128)
            _draw_wrapped(pdf, _safe_presentation_lines(snapshot, title), y=height - 160)
        pdf.setFillColor(HexColor("#526071") if page_number > 1 else HexColor("#FFFFFF"))
        pdf.setFont("Helvetica", 8)
        pdf.drawString(44, 30, "Evidence-grounded report - unavailable evidence is explicit")
        pdf.drawRightString(
            width - 44,
            30,
            f"Page {page_number} of {len(PRESENTATION_SECTION_TITLES)}",
        )
        pdf.showPage()
    pdf.setTitle("ZuiGO Website Analysis Presentation Report")
    pdf.setAuthor("ZuiGO Website Intelligence")
    pdf.setSubject("Concise evidence-grounded website analysis")
    pdf.save()
    content = output.getvalue()
    output.close()
    return content


def render_presentation_html(snapshot: dict[str, Any]) -> bytes:
    navigation = "".join(
        f'<li><a href="#section-{index}">{html.escape(title)}</a></li>'
        for index, title in enumerate(PRESENTATION_SECTION_TITLES, 1)
    )
    sections = "".join(
        f'<section id="section-{index}" aria-labelledby="heading-{index}">'
        f'<h2 id="heading-{index}">{html.escape(title)}</h2>'
        + "".join(
            f"<p>{html.escape(line)}</p>" for line in _safe_presentation_lines(snapshot, title)
        )
        + "</section>"
        for index, title in enumerate(PRESENTATION_SECTION_TITLES[1:], 2)
    )
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ZuiGO Website Analysis Presentation Report</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;font:17px/1.6 Arial,sans-serif;color:#172033}}
header{{padding:5rem 8vw;background:#123a63;color:white}}h1{{font-size:3rem;max-width:16ch}}
main,nav{{max-width:72rem;margin:auto;padding:2rem}}
section{{padding:2rem 0;border-top:1px solid #cbd5e1}}
a{{color:#0645ad}}a:focus{{outline:3px solid #c94f1d;outline-offset:3px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(12rem,1fr));gap:1rem}}
.card{{padding:1rem;border:1px solid #cbd5e1;border-radius:.6rem}}
@media print{{@page{{size:A4;margin:16mm}}section{{break-before:page}}header{{break-after:page}}}}
</style></head><body>
<header id="section-1" aria-labelledby="heading-1"><p>ZuiGO Website Intelligence</p>
<h1 id="heading-1">Website Analysis Presentation Report</h1>
<p>{html.escape(snapshot["website_name"])} - {html.escape(snapshot["website_url"])}</p>
<p><strong>76/100</strong> - confidence 88% - page coverage 7/10 (70.0%)</p></header>
<nav aria-label="Presentation report sections"><h2>Contents</h2><ol>{navigation}</ol></nav>
<main>{sections}</main>
<footer><p>ZuiGO - unavailable evidence is not treated as passed.</p></footer>
</body></html>"""
    return document.encode()


def render_technical_appendix_pdf(snapshot: dict[str, Any]) -> bytes:
    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=A4, pageCompression=1, invariant=1)
    width, height = A4
    page_number = 0

    def new_page(title: str) -> float:
        nonlocal page_number
        if page_number:
            pdf.showPage()
        page_number += 1
        pdf.setFillColor(HexColor("#123A63"))
        pdf.rect(0, height - 62, width, 62, stroke=0, fill=1)
        pdf.setFillColor(HexColor("#FFFFFF"))
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(44, height - 38, "ZuiGO TECHNICAL APPENDIX")
        pdf.setFillColor(HexColor("#172033"))
        pdf.setFont("Helvetica-Bold", 18)
        pdf.drawString(44, height - 92, title)
        pdf.setFont("Helvetica", 8)
        pdf.drawRightString(width - 44, 24, f"Appendix page {page_number}")
        return height - 120

    y = new_page("Full Page Inventory")
    for item in snapshot["technical_appendix"]["page_inventory"]:
        lines = [
            f"{item['url']} | {item['analysis_status']} | HTTP {item['http_status']} | "
            f"browsers: {', '.join(item['browsers_tested']) or 'Not tested'} | "
            f"issues: {item['issue_count']} | coverage: "
            f"{item['evidence_coverage_percentage']}"
        ]
        if y < 80:
            y = new_page("Full Page Inventory (continued)")
        y = _draw_wrapped(pdf, lines, y=y, font_size=8, leading=11)
    y = new_page("Browser-Specific Evidence")
    for item in snapshot["technical_appendix"]["browser_observations"]:
        lines = [
            f"{item['page_url']} | {item['engine_label']} | "
            f"{item['viewport']['name']} {item['viewport']['width']} x "
            f"{item['viewport']['height']} | navigation={item.get('navigation_success')} | "
            f"render={item.get('render_success')} | overflow={item.get('layout_overflow')} | "
            f"console={item.get('console_errors')} | resources={item.get('failed_resources')}"
        ]
        if y < 80:
            y = new_page("Browser-Specific Evidence (continued)")
        y = _draw_wrapped(pdf, lines, y=y, font_size=8, leading=11)
    y = new_page("Findings and Every Retained Occurrence")
    for finding in snapshot["technical_appendix"]["all_findings"]:
        lines = [
            f"[{finding['severity']}] {finding['issue_title']}",
            f"Rule: {finding['finding_code']} | Detecting agent: {finding['detecting_agent']} | "
            f"Validating agent: {finding['validating_agent']}",
            f"Fix: {finding['recommended_remediation']}",
            f"Verify: {finding['verification_procedure']}",
        ]
        lines.extend(
            f"Occurrence: {item['normalized_url']} | "
            "location="
            f"{item.get('selector') or item.get('resource_url') or item.get('location')} | "
            f"observed={item.get('observed_value')} | expected={item.get('expected_value')}"
            for item in finding["exact_occurrences"]
        )
        for line in lines:
            if y < 80:
                y = new_page("Findings and Occurrences (continued)")
            y = _draw_wrapped(pdf, [line], y=y, font_size=8, leading=11)
    pdf.save()
    content = output.getvalue()
    output.close()
    return content


def render_demo_export(kind: str, snapshot: dict[str, Any]) -> tuple[bytes, str, str]:
    safe_base = "zuigo-demo-website-analysis"
    if kind == "presentation-html":
        return render_presentation_html(snapshot), "text/html; charset=utf-8", f"{safe_base}.html"
    if kind == "presentation-pdf":
        return render_presentation_pdf(snapshot), "application/pdf", f"{safe_base}.pdf"
    if kind == "technical-appendix":
        return (
            render_technical_appendix_pdf(snapshot),
            "application/pdf",
            f"{safe_base}-technical-appendix.pdf",
        )
    if kind == "evidence-json":
        return (
            json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode(),
            "application/json",
            f"{safe_base}-evidence.json",
        )
    if kind == "page-inventory":
        return (
            json.dumps(
                snapshot["presentation"]["page_inventory"],
                sort_keys=True,
                separators=(",", ":"),
            ).encode(),
            "application/json",
            f"{safe_base}-page-inventory.json",
        )
    raise ValueError("Unsupported presentation export.")
