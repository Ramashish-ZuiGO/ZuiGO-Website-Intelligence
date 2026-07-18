from decimal import ROUND_HALF_UP, Decimal
from typing import Any

FORMULA_VERSION = "1.0.0"
CATEGORY_WEIGHTS = {
    "performance": 25,
    "accessibility": 20,
    "best_practices": 15,
    "seo": 20,
    "technical_quality": 20,
}
SEVERITY_DEDUCTIONS = {
    "critical": 25,
    "high": 15,
    "medium": 8,
    "low": 3,
    "informational": 0,
}
PLAYWRIGHT_MEASUREMENT_KEYS = (
    "page_title",
    "meta_description",
    "canonical_url",
    "html_language",
    "h1_count",
    "image_count",
    "images_missing_alt",
    "internal_link_count",
    "external_link_count",
    "form_count",
    "button_count",
    "console_errors",
    "page_javascript_errors",
    "failed_network_requests",
    "https_usage",
)


def round_score(value: float) -> int:
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def technical_quality(findings: list[dict[str, Any]]) -> tuple[int, list[dict[str, Any]]]:
    deductions: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    for finding in findings:
        code = str(finding["finding_code"])
        source = str(finding["source"])
        if source not in {"playwright", "http"} or code in seen_codes:
            continue
        seen_codes.add(code)
        severity = str(finding["severity"])
        amount = SEVERITY_DEDUCTIONS[severity]
        deductions.append(
            {
                "finding_code": code,
                "severity": severity,
                "source": source,
                "deduction_amount": amount,
            }
        )
    return max(0, 100 - sum(item["deduction_amount"] for item in deductions)), deductions


def calculate_score(
    lighthouse_metrics: dict[str, Any],
    playwright_data: dict[str, Any],
    findings: list[dict[str, Any]],
    *,
    audit_completed: bool,
) -> dict[str, Any]:
    category_scores: dict[str, int | None] = {
        "performance": lighthouse_metrics.get("performance_score"),
        "accessibility": lighthouse_metrics.get("accessibility_score"),
        "best_practices": lighthouse_metrics.get("best_practices_score"),
        "seo": lighthouse_metrics.get("seo_score"),
    }
    technical_score, deductions = technical_quality(findings)
    category_scores["technical_quality"] = technical_score if playwright_data else None
    available = [name for name, value in category_scores.items() if value is not None]
    unavailable = [name for name, value in category_scores.items() if value is None]
    available_weight = sum(CATEGORY_WEIGHTS[name] for name in available)
    overall = None
    if available_weight:
        weighted_total = sum(
            int(category_scores[name]) * CATEGORY_WEIGHTS[name] for name in available
        )
        overall = round_score(weighted_total / available_weight)

    lighthouse_available = sum(
        category_scores[name] is not None
        for name in ("performance", "accessibility", "best_practices", "seo")
    )
    measurement_available = sum(key in playwright_data for key in PLAYWRIGHT_MEASUREMENT_KEYS)
    http_status = playwright_data.get("http_status_code")
    confidence = round_score(
        lighthouse_available / 4 * 60
        + measurement_available / len(PLAYWRIGHT_MEASUREMENT_KEYS) * 25
        + (10 if isinstance(http_status, int) and 200 <= http_status < 400 else 0)
        + (5 if audit_completed else 0)
    )
    normalized_weights = {
        name: round(CATEGORY_WEIGHTS[name] / available_weight, 6) for name in available
    }
    return {
        "formula_version": FORMULA_VERSION,
        "overall_score": overall,
        "performance_score": category_scores["performance"],
        "accessibility_score": category_scores["accessibility"],
        "best_practices_score": category_scores["best_practices"],
        "seo_score": category_scores["seo"],
        "technical_quality_score": category_scores["technical_quality"],
        "confidence_percent": confidence,
        "available_categories": available,
        "unavailable_categories": unavailable,
        "weights": CATEGORY_WEIGHTS,
        "deductions": deductions,
        "calculation_details": {
            "rounding": "round-half-up to the nearest integer",
            "starting_technical_quality_score": 100,
            "normalized_available_weights": normalized_weights,
            "available_weight_total": available_weight,
            "confidence_components": {
                "lighthouse_categories_max": 60,
                "playwright_measurements_max": 25,
                "successful_http_response": 10,
                "completed_audit": 5,
                "playwright_measurements_available": measurement_available,
                "playwright_measurements_expected": len(PLAYWRIGHT_MEASUREMENT_KEYS),
            },
        },
    }
