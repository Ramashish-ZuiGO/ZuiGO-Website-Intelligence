from worker_app.analysis.findings import generate_findings
from worker_app.analysis.lighthouse_audit import parse_lighthouse
from worker_app.analysis.playwright_audit import (
    classify_failed_request,
    detect_technology,
    parse_playwright_measurements,
)


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
                "unused-javascript": {
                    "title": "Reduce unused JavaScript",
                    "score": 0.5,
                    "description": "Remove unused code.",
                    "details": {
                        "type": "opportunity",
                        "items": [{"url": "https://example.com/a.js"}],
                    },
                },
            },
            "configSettings": {
                "formFactor": "mobile",
                "throttlingMethod": "simulate",
                "screenEmulation": {"mobile": True, "width": 412, "height": 823},
            },
            "environment": {"networkUserAgent": "Mozilla/5.0 Chrome/140.0.0.0 Safari/537.36"},
            "fetchTime": "2026-07-23T08:00:00.000Z",
        }
    )
    assert parsed["performance_score"] == 72
    assert parsed["largest_contentful_paint_ms"] == 3100
    assert parsed["cumulative_layout_shift"] == 0.12
    assert parsed["total_blocking_time_ms"] is None
    assert parsed["lighthouse_context"]["form_factor"] == "mobile"
    assert parsed["lighthouse_context"]["chromium_version"] == "140.0.0.0"
    assert parsed["time_to_interactive_context"]["status"] == "legacy_supplementary"


def test_lighthouse_failed_and_manual_audits_are_bounded() -> None:
    parsed = parse_lighthouse(
        {
            "categories": {
                "accessibility": {
                    "score": 1,
                    "auditRefs": [
                        {"id": "color-contrast"},
                        {"id": "focus-manual"},
                    ],
                }
            },
            "audits": {
                "color-contrast": {
                    "title": "Contrast",
                    "score": 0,
                    "displayValue": "2 elements",
                    "details": {"type": "table", "items": [{}, {}]},
                },
                "focus-manual": {
                    "title": "Focus order",
                    "score": None,
                    "scoreDisplayMode": "manual",
                },
            },
        }
    )
    breakdown = parsed["lighthouse_audit_breakdown"]
    assert [item["audit_id"] for item in breakdown] == ["color-contrast", "focus-manual"]
    assert breakdown[1]["manual_check"] is True
    assert parsed["accessibility_context"]["manual_testing_required"] is True


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


def test_failed_request_classification() -> None:
    class Request:
        failure = "net::ERR_ABORTED"
        url = "https://example.com/app.js"
        resource_type = "script"

    assert classify_failed_request(Request(), "https://example.com/") == "critical"


def test_failed_request_classification_uses_resource_origin_console_and_shutdown() -> None:
    class Request:
        def __init__(self, url: str, resource_type: str, failure: str = "net::ERR_ABORTED"):
            self.url = url
            self.resource_type = resource_type
            self.failure = failure

    css = Request("https://example.com/site.css", "stylesheet")
    script = Request("https://example.com/app.js", "script")
    analytics = Request("https://www.google-analytics.com/g/collect?x=1", "fetch")
    video = Request("https://example.com/hero.mp4", "media")
    shutdown = Request("https://cdn.example.net/image.jpg", "image")
    unknown = Request("https://cdn.example.net/data.bin", "other", "net::ERR_FAILED")

    assert (
        classify_failed_request(
            css,
            "https://example.com/",
            console_errors=[
                "Refused to apply style from https://example.com/site.css because its MIME type"
            ],
        )
        == "critical"
    )
    assert classify_failed_request(script, "https://example.com/") == "critical"
    assert classify_failed_request(analytics, "https://example.com/") == "non_critical"
    assert classify_failed_request(video, "https://example.com/") == "expected_aborted"
    assert (
        classify_failed_request(shutdown, "https://example.com/", navigation_shutting_down=True)
        == "expected_aborted"
    )
    assert classify_failed_request(unknown, "https://example.com/") == "unknown"


def test_nextjs_detection_positive_uncertain_and_negative() -> None:
    positive = detect_technology(
        {
            "technology_evidence": {
                "next_asset_path": "https://example.com/_next/static/a.js",
                "next_root": True,
            }
        }
    )
    uncertain = detect_technology(
        {"technology_evidence": {"next_asset_path": "https://example.com/_next/static/a.js"}}
    )
    negative = detect_technology({"technology_evidence": {}})
    assert positive["status"] == "detected"
    assert uncertain["status"] == "uncertain"
    assert negative["status"] == "not_detected"
    assert positive["indicators"]


def test_expected_aborted_requests_do_not_create_findings() -> None:
    playwright_data = {
        "final_url": "https://example.com/",
        "page_title": "Example",
        "meta_description": "Description",
        "canonical_url": "https://example.com/",
        "html_language": "en",
        "h1_count": 1,
        "image_count": 0,
        "images_missing_alt": 0,
        "page_javascript_errors": [],
        "failed_network_requests": [
            {
                "url": "https://example.com/video.mp4",
                "failure": "net::ERR_ABORTED",
                "classification": "expected_aborted",
            }
        ],
        "https_usage": True,
    }
    findings = generate_findings(playwright_data, {})
    assert "FAILED_NETWORK_REQUESTS" not in {item["finding_code"] for item in findings}


def test_css_mime_failure_creates_specific_finding_without_generic_duplicate() -> None:
    playwright_data = {
        "final_url": "https://example.com/",
        "page_title": "Example",
        "meta_description": "Description",
        "canonical_url": "https://example.com/",
        "html_language": "en",
        "h1_count": 1,
        "image_count": 0,
        "images_missing_alt": 0,
        "page_javascript_errors": [],
        "failed_network_requests": [
            {
                "url": "https://example.com/site.css",
                "failure": "net::ERR_ABORTED",
                "resource_type": "stylesheet",
                "first_party": True,
                "classification": "critical",
                "console_evidence": ["Refused to apply style because its MIME type is text/html"],
            }
        ],
        "https_usage": True,
    }
    findings = generate_findings(playwright_data, {})
    codes = [item["finding_code"] for item in findings]
    assert codes.count("CSS_MIME_TYPE_FAILURE") == 1
    assert "FAILED_NETWORK_REQUESTS" not in codes
