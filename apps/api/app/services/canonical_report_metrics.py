"""Canonical report metrics — single source of truth for all customer-facing values.

Every report section, export, and frontend surface must consume these
canonical values rather than recomputing metrics independently.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EvidenceCoverage:
    numerator: int
    denominator: int
    percentage: float | None
    label: str


@dataclass(frozen=True)
class CategoryEvidence:
    category_id: str
    score: int | None
    included: bool
    evidence_available: bool
    dedicated_audit_available: bool
    exclusion_reason: str | None
    limitation: str | None


@dataclass(frozen=True)
class CanonicalReportMetrics:
    # Evidence completeness — report sections available
    report_section_coverage: EvidenceCoverage
    # Score evidence — scoring categories available
    score_category_coverage: EvidenceCoverage
    # Page coverage
    eligible_pages: int
    analysed_pages: int
    failed_pages: int
    # Browser
    browser_tested: int
    browser_expected: int
    browser_coverage_percent: float | None
    # Confidence
    formula_determinism_percent: float | None
    report_confidence_percent: int | None
    confidence_components: dict[str, float | None]
    confidence_explanation: str
    # Category evidence
    category_evidence: list[CategoryEvidence]
    # Findings
    unique_finding_count: int
    total_occurrence_count: int
    affected_eligible_page_count: int
    # Limitations (deduplicated)
    semantic_limitations: list[SemanticLimitation]


@dataclass(frozen=True)
class SemanticLimitation:
    """Deduplicated limitation for renderer consumption.

    M13: this is a PRESENTATION-side dedup of free-text limitation
    strings; the authoritative machine-readable taxonomy
    (required/optional/optional_infrastructure/not_applicable) lives in
    the completion block's limitation_reasons built by
    _completion_semantics. ``kind`` is carried through here when the
    caller supplies it so the taxonomy is never silently lost by
    consuming this list instead.
    """

    limitation_id: str
    message: str
    source: str
    kind: str | None = None


# ---------------------------------------------------------------------------
# Limitation deduplication
# ---------------------------------------------------------------------------

_LIMITATION_PATTERNS: dict[str, str] = {
    "discovery_incomplete": "Website discovery was incomplete",
    "discovery_partial": "partial coverage",
    "discovery_inconclusive": "discovery was inconclusive",
    "crawl_safety_limit": "crawl-depth limit",
    "firefox_unavailable": "Firefox",
    "accessibility_unavailable": "Accessibility evidence was not",
    "evidence_incomplete": "Some advanced data sources were unavailable",
    "automated_accessibility": "Automated accessibility evidence cannot",
    "deterministic_fallback": "deterministic fallback",
    "no_competitor_comparison": "No competitor or search-engine ranking",
    "unavailable_not_passed": "Unavailable evidence is not",
    "lab_not_field": "Laboratory performance evidence is not field",
    "evidence_coverage_separate": "Evidence completeness and website page coverage are separate",
}


def _assign_limitation_id(message: str) -> str:
    lower = message.casefold()
    for lid, pattern in _LIMITATION_PATTERNS.items():
        if pattern.casefold() in lower:
            return lid
    # M13: Python's hash() is salted per process (PYTHONHASHSEED), so the
    # previous hash()-based fallback gave the SAME unmatched limitation a
    # DIFFERENT opaque id on every report generation. A content digest is
    # stable across runs, processes, and machines.
    digest = hashlib.sha256(message.encode("utf-8")).hexdigest()[:8]
    return f"other_{digest}"


def deduplicate_limitations(
    raw_limitations: list[dict[str, str]],
) -> list[SemanticLimitation]:
    seen_ids: dict[str, SemanticLimitation] = {}
    for item in raw_limitations:
        message = item.get("message", "").strip()
        if not message:
            continue
        lid = _assign_limitation_id(message)
        if lid not in seen_ids:
            seen_ids[lid] = SemanticLimitation(
                limitation_id=lid,
                message=message,
                source=item.get("source", "unknown"),
                kind=item.get("kind"),
            )
    return list(seen_ids.values())


# ---------------------------------------------------------------------------
# Affected-page reconciliation
# ---------------------------------------------------------------------------


def reconcile_affected_pages(
    findings: list[dict[str, Any]],
    eligible_urls: set[str],
) -> int:
    affected = set()
    for finding in findings:
        for occ in finding.get("exact_occurrences", []):
            url = occ.get("normalized_url")
            if url and url in eligible_urls:
                affected.add(url)
    return len(affected)


# ---------------------------------------------------------------------------
# Category evidence availability
# ---------------------------------------------------------------------------


def compute_category_evidence(
    categories: list[dict[str, Any]],
    section_availability: dict[str, str],
) -> list[CategoryEvidence]:
    _CATEGORY_SECTION_MAP = {
        "performance": "performance",
        "accessibility": "accessibility",
        "best_practices": "site_diagnostics",
        "seo": "content_seo",
        "technical_quality": "site_diagnostics",
    }
    result = []
    for cat in categories:
        cat_id = str(cat.get("category_id", ""))
        section_key = _CATEGORY_SECTION_MAP.get(cat_id)
        dedicated_available = (
            section_availability.get(section_key, "unavailable") != "unavailable"
            if section_key
            else False
        )
        score = cat.get("score")
        included = cat.get("included", False)
        limitation = None
        if included and score is not None and not dedicated_available:
            limitation = (
                f"Score calculated from available formula inputs; "
                f"dedicated {cat_id.replace('_', ' ')} audit evidence was unavailable."
            )
        result.append(
            CategoryEvidence(
                category_id=cat_id,
                score=score,
                included=included,
                evidence_available=bool(included and score is not None),
                dedicated_audit_available=dedicated_available,
                exclusion_reason=cat.get("exclusion_reason"),
                limitation=limitation,
            )
        )
    return result


# ---------------------------------------------------------------------------
# Invariant checks
# ---------------------------------------------------------------------------


class ReportInvariantError(ValueError):
    pass


def check_invariants(
    *,
    discovered: int,
    eligible: int,
    scheduled: int,
    visited: int,
    successful: int,
    affected_eligible: int,
    browser_tested: int,
    browser_expected: int,
    section_statuses: dict[str, str],
    category_evidence: list[CategoryEvidence],
) -> list[str]:
    violations = []

    if successful > visited:
        violations.append(f"successful ({successful}) > visited ({visited})")
    if visited > scheduled:
        violations.append(f"visited ({visited}) > scheduled ({scheduled})")
    if scheduled > eligible:
        violations.append(f"scheduled ({scheduled}) > eligible ({eligible})")
    if affected_eligible > eligible:
        violations.append(f"affected_eligible ({affected_eligible}) > eligible ({eligible})")
    if browser_tested > browser_expected:
        violations.append(
            f"browser_tested ({browser_tested}) > browser_expected ({browser_expected})"
        )

    # M9: the false-100%-complete guard originally covered only the
    # accessibility category; a perfect score claimed on unavailable
    # evidence in any other category passed unchecked. Every score category
    # now maps to the report section that carries its dedicated evidence
    # (mirrors _category_has_dedicated_audit in report_delivery.py).
    section_key_map = {
        "accessibility": "accessibility",
        "performance": "performance",
        "seo": "content_seo",
        "best_practices": "site_diagnostics",
        "technical_quality": "site_diagnostics",
    }
    for cat_ev in category_evidence:
        section_key = section_key_map.get(cat_ev.category_id)
        if section_key and section_statuses.get(section_key) == "unavailable":
            if cat_ev.evidence_available and cat_ev.score == 100:
                violations.append(
                    f"Category {cat_ev.category_id} shows score=100 with "
                    f"evidence_available=True but dedicated section is unavailable; "
                    f"must show limitation"
                )

    return violations


# ---------------------------------------------------------------------------
# Build canonical metrics from report snapshot data
# ---------------------------------------------------------------------------


def build_canonical_metrics(
    *,
    sections: list[dict[str, Any]],
    page_coverage: dict[str, Any],
    browser_compatibility: dict[str, Any],
    score_categories: list[dict[str, Any]],
    score_confidence: float | None,
    grouped_findings: list[dict[str, Any]],
    eligible_urls: set[str],
    report_confidence: int | None,
    confidence_components: dict[str, float | None],
    all_limitations: list[dict[str, str]],
) -> CanonicalReportMetrics:
    available_sections = sum(1 for s in sections if s.get("status") != "unavailable")
    total_sections = len(sections)
    section_pct = round(available_sections / total_sections * 100, 2) if total_sections else None
    section_availability = {s["section_key"]: s["status"] for s in sections}

    score_available = sum(
        1 for c in score_categories if c.get("included") and c.get("score") is not None
    )
    score_total = len(score_categories) or 5
    score_pct = round(score_available / score_total * 100, 2) if score_total else None

    eligible = int(page_coverage.get("eligible_pages", 0))
    analysed = int(page_coverage.get("successfully_analysed_pages", 0))
    failed = int(page_coverage.get("failed_pages", 0))

    browser_engines = browser_compatibility.get("engines", [])
    browser_tested = sum(int(e.get("tested_pages", 0)) for e in browser_engines)
    browser_expected = sum(int(e.get("eligible_pages", 0)) for e in browser_engines)
    browser_pct = round(browser_tested / browser_expected * 100, 2) if browser_expected else None

    cat_evidence = compute_category_evidence(score_categories, section_availability)

    unique_findings = len(grouped_findings)
    total_occurrences = sum(int(f.get("occurrence_count", 0)) for f in grouped_findings)
    affected = reconcile_affected_pages(grouped_findings, eligible_urls)

    deduped_limitations = deduplicate_limitations(all_limitations)

    confidence_explanation = (
        "The score formula is deterministic, while report confidence is limited by the "
        "least complete of discovery completeness, retained evidence, eligible-page "
        "analysis, and requested browser-engine coverage."
    )

    return CanonicalReportMetrics(
        report_section_coverage=EvidenceCoverage(
            numerator=available_sections,
            denominator=total_sections,
            percentage=section_pct,
            label="report sections with available evidence",
        ),
        score_category_coverage=EvidenceCoverage(
            numerator=score_available,
            denominator=score_total,
            percentage=score_pct,
            label="scoring categories with available evidence",
        ),
        eligible_pages=eligible,
        analysed_pages=analysed,
        failed_pages=failed,
        browser_tested=browser_tested,
        browser_expected=browser_expected,
        browser_coverage_percent=browser_pct,
        formula_determinism_percent=score_confidence,
        report_confidence_percent=report_confidence,
        confidence_components=confidence_components,
        confidence_explanation=confidence_explanation,
        category_evidence=cat_evidence,
        unique_finding_count=unique_findings,
        total_occurrence_count=total_occurrences,
        affected_eligible_page_count=affected,
        semantic_limitations=deduped_limitations,
    )
