"""Priority Formula v1.0.0.

Calculates a deterministic 0-100 priority score for actionable remediation items.

Inputs:
  - severity: str ('critical', 'high', 'medium', 'low', 'informational')
  - affected_page_count: int (number of pages affected)
  - estimated_score_impact: int (0-100, estimated impact on score if fixed)
  - confidence_percent: int (0-100, how confident we are in the finding)
  - implementation_effort: str ('low', 'medium', 'high', 'very_high')
  - business_impact: str ('critical', 'major', 'moderate', 'minor', 'negligible')

Formula v1.0.0:
  1. Severity base (0-35):
     critical=35, high=25, medium=15, low=5, informational=0

  2. Affected pages multiplier (0-25):
     >=50 pages: 25, >=20: 20, >=10: 15, >=5: 10, >=2: 5, 1 page: 0

  3. Score impact (0-15):
     proportional: round(score_impact / 100 * 15)

  4. Confidence weight (0-10):
     >=90: 10, >=70: 7, >=50: 5, >=30: 3, >=10: 1, <10: 0

  5. Effort penalty (0-15, inverted — lower effort = higher priority):
     low: 15, medium: 10, high: 5, very_high: 0

  6. Business impact boost (0-15, added on top of severity):
     critical: 15, major: 10, moderate: 6, minor: 3, negligible: 0

   Total = severity_base + pages_score + impact_score + confidence_score \
            - effort_penalty + business_boost
  Clamped to 0-100.
"""

from typing import Any

PRIORITY_FORMULA_VERSION = "1.0.0"

SEVERITY_BASE: dict[str, int] = {
    "critical": 35,
    "high": 25,
    "medium": 15,
    "low": 5,
    "informational": 0,
}

AFFECTED_PAGE_BREAKPOINTS: list[tuple[int, int]] = [
    (50, 25),
    (20, 20),
    (10, 15),
    (5, 10),
    (2, 5),
]

CONFIDENCE_BREAKPOINTS: list[tuple[int, int]] = [
    (90, 10),
    (70, 7),
    (50, 5),
    (30, 3),
    (10, 1),
]

EFFORT_SCORES: dict[str, int] = {
    "low": 15,
    "medium": 10,
    "high": 5,
    "very_high": 0,
}

BUSINESS_IMPACT_SCORES: dict[str, int] = {
    "critical": 15,
    "major": 10,
    "moderate": 6,
    "minor": 3,
    "negligible": 0,
}


def _compute_affected_pages_score(count: int) -> int:
    for threshold, score in AFFECTED_PAGE_BREAKPOINTS:
        if count >= threshold:
            return score
    return 0


def _compute_confidence_score(confidence_percent: int) -> int:
    confidence_percent = max(0, min(100, confidence_percent))
    for threshold, score in CONFIDENCE_BREAKPOINTS:
        if confidence_percent >= threshold:
            return score
    return 0


def calculate_priority_score(
    severity: str,
    affected_page_count: int,
    estimated_score_impact: int,
    confidence_percent: int,
    implementation_effort: str,
    business_impact: str,
) -> tuple[int, dict[str, Any]]:
    severity_base = SEVERITY_BASE.get(severity, 0)
    pages_score = _compute_affected_pages_score(affected_page_count)
    impact_score = max(0, min(15, round(estimated_score_impact / 100 * 15)))
    confidence_score = _compute_confidence_score(confidence_percent)
    effort_penalty = EFFORT_SCORES.get(implementation_effort, 5)
    business_boost = BUSINESS_IMPACT_SCORES.get(business_impact, 0)

    raw = (
        severity_base
        + pages_score
        + impact_score
        + confidence_score
        + effort_penalty
        + business_boost
    )
    clamped = max(0, min(100, raw))

    components: dict[str, Any] = {
        "severity_base": severity_base,
        "pages_score": pages_score,
        "impact_score": impact_score,
        "confidence_score": confidence_score,
        "effort_score": effort_penalty,
        "business_boost": business_boost,
        "raw_total": raw,
        "formula_version": PRIORITY_FORMULA_VERSION,
    }

    return clamped, components
