from datetime import UTC, datetime

import pytest
from worker_app.analysis.diagnostics import (
    analytics_diagnostics,
    browser_compatibility,
    cache_diagnostics,
    collect_w3c,
    copyright_diagnostics,
    parse_w3c_response,
    policy_diagnostics,
    responsive_diagnostics,
    security_diagnostics,
)


def test_markup_formula_is_reproducible_and_bounded() -> None:
    result = parse_w3c_response(
        {
            "messages": [{"type": "error", "message": "bad"}] * 30
            + [{"type": "info", "message": "warning"}] * 40
        },
        5,
    )
    assert result["verified_observations"] == {"error_count": 30, "warning_count": 40}
    assert result["score"]["final_score"] == 0
    assert len(result["evidence"]) == 5
    assert result["score"]["label"] == "ZuiGO-derived"


def test_w3c_timeout_and_invalid_output_are_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "worker_app.analysis.diagnostics.urllib.request.urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError()),
    )
    timed_out = collect_w3c(
        "<html>", enabled=True, endpoint="https://validator.example", timeout=1, evidence_limit=2
    )
    assert timed_out["status"] == "unavailable"

    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b"not-json"

    monkeypatch.setattr(
        "worker_app.analysis.diagnostics.urllib.request.urlopen", lambda *args, **kwargs: Response()
    )
    invalid = collect_w3c(
        "<html>", enabled=True, endpoint="https://validator.example", timeout=1, evidence_limit=2
    )
    assert invalid["status"] == "unavailable"


def test_cache_evaluates_html_and_static_assets_separately() -> None:
    result = cache_diagnostics(
        {
            "main_response_headers": {"cache-control": "no-cache", "etag": "abc"},
            "resource_samples": [
                {
                    "url": "https://example.com/app.abcdef123.js",
                    "resource_type": "script",
                    "headers": {"cache-control": "public, max-age=31536000, immutable"},
                },
                {
                    "url": "https://example.com/site.css",
                    "resource_type": "stylesheet",
                    "headers": {},
                },
            ],
        }
    )
    assert result["score"]["final_score"] == 92
    assert result["verified_observations"]["resources"][0]["immutable"] is True


def test_no_store_static_response_is_not_short_lifetime_failure() -> None:
    result = cache_diagnostics(
        {
            "main_response_headers": {"cache-control": "no-store"},
            "resource_samples": [
                {
                    "url": "https://example.com/private.js",
                    "resource_type": "script",
                    "headers": {"cache-control": "no-store"},
                }
            ],
        }
    )
    assert not any(
        item["code"] == "STATIC_ASSET_CACHE_TOO_SHORT" for item in result["score"]["deductions"]
    )


def test_security_strong_csp_and_frame_ancestors() -> None:
    result = security_diagnostics(
        {
            "https_usage": True,
            "mixed_content_count": 0,
            "main_response_headers": {
                "content-security-policy": "default-src 'self'; frame-ancestors 'none'",
                "strict-transport-security": "max-age=31536000",
                "x-content-type-options": "nosniff",
            },
        }
    )
    assert result["verified_observations"]["csp_quality"] == "strong"
    assert result["score"]["final_score"] == 100
    assert "does not prove" in result["limitations"][0]


def test_security_weak_csp_and_exposure_are_deducted() -> None:
    result = security_diagnostics(
        {
            "https_usage": True,
            "mixed_content_count": 1,
            "main_response_headers": {
                "content-security-policy": "default-src * 'unsafe-inline'",
                "server": "example",
            },
        }
    )
    codes = {item["code"] for item in result["score"]["deductions"]}
    assert {
        "CSP_WEAK",
        "HSTS_MISSING",
        "MIXED_CONTENT_DETECTED",
        "SERVER_INFORMATION_EXPOSED",
    } <= codes


def test_analytics_detects_ga4_gtm_duplicates_and_consent() -> None:
    result = analytics_diagnostics(
        {
            "script_evidence": "gtag consent default G-ABC12345 G-XYZ67890 GTM-AAAA GTM-BBBB",
            "network_urls": ["https://analytics.google.com/g/collect"],
        }
    )
    values = result["verified_observations"]
    assert values["ga4_detected"] and values["gtm_detected"]
    assert values["duplicate_ga4"] and values["duplicate_gtm"]
    assert values["consent_mode_indicators"]
    assert "visitors" not in values


def test_responsive_partial_failure_and_formula() -> None:
    result = responsive_diagnostics(
        {
            "viewport_meta": "width=device-width",
            "responsive_results": [
                {"name": "mobile_portrait", "status": "passed", "horizontal_overflow": True},
                {"name": "desktop", "status": "failed"},
            ],
        }
    )
    assert result["status"] == "partial"
    assert result["score"]["final_score"] == 70
    assert result["score"]["confidence_percent"] == 50


def test_browser_matrix_does_not_claim_untested_engines() -> None:
    matrix = browser_compatibility({"responsive_results": [], "page_javascript_errors": []})[
        "verified_observations"
    ]["matrix"]
    assert matrix["chromium"] == {"tested": True, "result": "passed"}
    assert matrix["firefox"]["result"] == "not_tested"
    assert matrix["webkit"]["result"] == "not_tested"


def test_copyright_current_outdated_and_unknown() -> None:
    current = datetime.now(UTC).year
    assert (
        copyright_diagnostics({"copyright_text": f"© {current} Example"})["verified_observations"][
            "result"
        ]
        == "current_year_detected"
    )
    assert (
        copyright_diagnostics({"copyright_text": "Copyright 2019 Example"})[
            "verified_observations"
        ]["result"]
        == "possibly_outdated"
    )
    assert copyright_diagnostics({})["verified_observations"]["result"] == "unknown"


def test_policy_explicit_date_current_and_no_inference(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self, limit: int) -> bytes:
            return f"<p>Last updated: {datetime.now(UTC).strftime('%B %d, %Y')}</p>".encode()

    monkeypatch.setattr(
        "worker_app.analysis.diagnostics.urllib.request.urlopen", lambda *args, **kwargs: Response()
    )
    result = policy_diagnostics(
        {
            "final_url": "https://example.com/",
            "policy_links": {"privacy": "https://example.com/privacy"},
            "copyright_text": "© 2018",
            "main_response_headers": {"last-modified": "today"},
        },
        timeout=1,
    )
    assert result["verified_observations"]["privacy_freshness"] == "current"
    assert result["verified_observations"]["privacy_date_label"].lower() == "last updated"


def test_policy_cross_site_link_is_rejected() -> None:
    result = policy_diagnostics(
        {
            "final_url": "https://example.com/",
            "policy_links": {"privacy": "https://other.example/privacy"},
        },
        timeout=1,
    )
    assert "privacy_policy_page" in result["unavailable_observations"]
    assert result["verified_observations"]["privacy_freshness"] == "unknown"
