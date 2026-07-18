from worker_app.analysis.findings import generate_findings
from worker_app.analysis.lighthouse_audit import parse_lighthouse
from worker_app.analysis.playwright_audit import parse_playwright_measurements


def test_playwright_result_parsing_preserves_direct_measurements() -> None:
    parsed = parse_playwright_measurements(
        {"page_title": "Example", "h1_texts": ["One", "Two"], "image_count": 3},
        requested_url="https://example.com/",
        final_url="https://www.example.com/",
        http_status_code=200,
        user_agent="test-agent",
        console_errors=["console failure"],
        page_errors=[],
        failed_requests=[],
    )
    assert parsed["page_title"] == "Example"
    assert parsed["h1_count"] == 2
    assert parsed["https_usage"] is True
    assert parsed["console_errors"] == ["console failure"]


def test_lighthouse_result_parsing_preserves_measured_values() -> None:
    parsed = parse_lighthouse(
        {
            "lighthouseVersion": "13.3.0",
            "categories": {
                "performance": {"score": 0.72},
                "accessibility": {"score": 0.91},
                "best-practices": {"score": 0.88},
                "seo": {"score": 0.95},
            },
            "audits": {
                "largest-contentful-paint": {"numericValue": 3100},
                "cumulative-layout-shift": {"numericValue": 0.12},
            },
        }
    )
    assert parsed["performance_score"] == 72
    assert parsed["largest_contentful_paint_ms"] == 3100
    assert parsed["cumulative_layout_shift"] == 0.12
    assert parsed["total_blocking_time_ms"] is None


def test_deterministic_findings_use_only_verified_values() -> None:
    playwright_data = {
        "final_url": "https://example.com/",
        "page_title": None,
        "meta_description": None,
        "canonical_url": None,
        "html_language": "en",
        "h1_count": 0,
        "image_count": 2,
        "images_missing_alt": 1,
        "page_javascript_errors": [],
        "failed_network_requests": [],
        "https_usage": True,
    }
    findings = generate_findings(
        playwright_data,
        {
            "performance_score": 40,
            "accessibility_score": None,
            "best_practices_score": None,
            "seo_score": None,
            "largest_contentful_paint_ms": None,
            "cumulative_layout_shift": None,
            "total_blocking_time_ms": None,
        },
    )
    codes = {item["finding_code"] for item in findings}
    assert "MISSING_PAGE_TITLE" in codes
    assert "IMAGES_MISSING_ALT" in codes
    assert "POOR_LIGHTHOUSE_PERFORMANCE" in codes
    assert "HIGH_LCP" not in codes
    assert all(item["confidence_percent"] == 100 for item in findings)
