from worker_app.analysis.scoring import calculate_score, technical_quality


def complete_playwright() -> dict[str, object]:
    return {
        "page_title": "Example",
        "meta_description": "Description",
        "canonical_url": "https://example.com/",
        "html_language": "en",
        "h1_count": 1,
        "image_count": 0,
        "images_missing_alt": 0,
        "internal_link_count": 1,
        "external_link_count": 0,
        "form_count": 0,
        "button_count": 0,
        "console_errors": [],
        "page_javascript_errors": [],
        "failed_network_requests": [],
        "https_usage": True,
        "http_status_code": 200,
    }


def test_exact_formula_and_confidence() -> None:
    score = calculate_score(
        {
            "performance_score": 80,
            "accessibility_score": 90,
            "best_practices_score": 70,
            "seo_score": 100,
        },
        complete_playwright(),
        [],
        audit_completed=True,
    )

    assert score["overall_score"] == 89
    assert score["technical_quality_score"] == 100
    assert score["confidence_percent"] == 100


def test_missing_category_is_not_fabricated_and_weights_normalize() -> None:
    score = calculate_score(
        {
            "performance_score": 80,
            "accessibility_score": None,
            "best_practices_score": 70,
            "seo_score": 100,
        },
        complete_playwright(),
        [],
        audit_completed=True,
    )

    assert score["accessibility_score"] is None
    assert score["unavailable_categories"] == ["accessibility"]
    assert score["overall_score"] == 88
    assert score["calculation_details"]["available_weight_total"] == 80
    assert score["confidence_percent"] == 85


def test_technical_deductions_are_unique_source_limited_and_floor_at_zero() -> None:
    findings = [
        {"finding_code": "A", "severity": "critical", "source": "playwright"},
        {"finding_code": "A", "severity": "critical", "source": "playwright"},
        {"finding_code": "LH", "severity": "critical", "source": "lighthouse"},
        *[
            {"finding_code": f"H{index}", "severity": "high", "source": "http"}
            for index in range(6)
        ],
    ]

    technical_score, deductions = technical_quality(findings)

    assert technical_score == 0
    assert len(deductions) == 7
    assert sum(item["deduction_amount"] for item in deductions) == 115


def test_partial_playwright_measurements_reduce_confidence() -> None:
    score = calculate_score({}, {"http_status_code": 500, "h1_count": 1}, [], audit_completed=False)

    assert score["overall_score"] == 100
    assert score["confidence_percent"] == 2
