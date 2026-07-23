from datetime import UTC, datetime

import pytest
from worker_app.analysis.diagnostics import (
    analytics_diagnostics,
    browser_compatibility,
    cache_diagnostics,
    classify_csp,
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


def test_markup_evidence_is_bounded_structured_and_escaped() -> None:
    result = parse_w3c_response(
        {
            "messages": [
                {
                    "type": "error",
                    "message": "<script>alert(1)</script>",
                    "extract": '<img onerror="alert(1)">',
                    "lastLine": 12,
                    "lastColumn": 4,
                    "subType": "bad-value",
                },
                {"type": "info", "message": "second"},
            ]
        },
        1,
    )
    assert len(result["evidence"]) == 1
    evidence = result["evidence"][0]
    assert evidence["severity"] == "error"
    assert evidence["diagnostic_code"] == "bad-value"
    assert evidence["line"] == 12
    assert "<script>" not in evidence["validator_message"]
    assert "&lt;script&gt;" in evidence["validator_message"]
    assert "<img" not in evidence["extract"]


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


def test_cache_html_only_is_provisional_without_changing_score() -> None:
    result = cache_diagnostics(
        {"main_response_headers": {"cache-control": "no-cache"}, "resource_samples": []}
    )
    assert result["status"] == "partial"
    assert result["score"]["final_score"] == 100
    assert result["score"]["confidence_percent"] == 20
    assert result["evidence_completeness"] == "html_only"
    assert result["verified_observations"]["score_qualification"] == "provisional_html_only"
    assert "static_asset_analysis" in result["unavailable_observations"]


def test_cache_partial_and_complete_static_samples() -> None:
    resource = {
        "url": "https://example.com/app.abcdef123.js",
        "resource_type": "script",
        "headers": {"cache-control": "public, max-age=31536000, immutable"},
    }
    partial = cache_diagnostics(
        {
            "main_response_headers": {},
            "resource_samples": [resource],
            "resource_sample_candidates": 3,
            "resource_sample_limit": 1,
        }
    )
    complete = cache_diagnostics(
        {
            "main_response_headers": {},
            "resource_samples": [resource],
            "resource_sample_candidates": 1,
            "resource_sample_limit": 20,
        }
    )
    assert partial["status"] == "partial"
    assert partial["evidence_completeness"] == "partial_static_sample"
    assert complete["status"] == "available"
    assert complete["evidence_completeness"] == "complete_observed_sample"


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
                "content-security-policy": (
                    "default-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
                ),
                "strict-transport-security": "max-age=31536000",
                "x-content-type-options": "nosniff",
            },
        }
    )
    assert result["verified_observations"]["csp_quality"] == "strong"
    assert result["score"]["final_score"] == 100
    assert "does not prove" in result["limitations"][0]


@pytest.mark.parametrize(
    ("policy", "quality"),
    [
        (None, "absent"),
        ("upgrade-insecure-requests", "upgrade_only"),
        ("default-src * 'unsafe-inline'", "weak"),
        ("default-src 'self'; object-src 'none'", "moderate"),
        (
            "default-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'",
            "strong",
        ),
    ],
)
def test_csp_quality_states_are_deterministic(policy: str | None, quality: str) -> None:
    result = classify_csp(policy)
    assert result["quality"] == quality
    assert result["reason"]


def test_upgrade_only_csp_uses_new_security_formula() -> None:
    result = security_diagnostics(
        {
            "https_usage": False,
            "main_response_headers": {
                "content-security-policy": "upgrade-insecure-requests",
                "x-content-type-options": "nosniff",
                "x-frame-options": "DENY",
            },
        }
    )
    assert result["verified_observations"]["csp_quality"] == "upgrade_only"
    assert result["score"]["formula_version"] == "1.1.0"
    assert any(item["code"] == "CSP_WEAK" for item in result["score"]["deductions"])


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


def test_responsive_tap_targets_explain_spacing_and_deduplicate() -> None:
    repeated = {
        "element_type": "button",
        "accessible_label": "Menu",
        "width": 20,
        "height": 20,
        "spacing_exception": False,
    }
    result = responsive_diagnostics(
        {
            "viewport_meta": "width=device-width",
            "responsive_results": [
                {
                    "name": "mobile",
                    "status": "passed",
                    "horizontal_overflow": False,
                    "tap_target_samples": [
                        repeated,
                        repeated,
                        {
                            "element_type": "a",
                            "accessible_label": "Help",
                            "width": 18,
                            "height": 18,
                            "spacing_exception": True,
                        },
                    ],
                }
            ],
        }
    )
    assert len(result["evidence"]) == 2
    assert result["verified_observations"]["confirmed_tap_target_failures"] == 1
    assert result["verified_observations"]["informational_small_targets"] == 1
    assert result["score"]["final_score"] == 100
    assert "do not reduce" in result["verified_observations"]["tap_target_scoring_behavior"]


def test_responsive_hidden_and_desktop_only_targets_are_not_confirmed_failures() -> None:
    result = responsive_diagnostics(
        {
            "viewport_meta": "width=device-width",
            "responsive_results": [
                {
                    "name": "desktop",
                    "status": "passed",
                    "horizontal_overflow": False,
                    "tap_target_samples": [
                        {
                            "element_type": "button",
                            "accessible_label": "Hidden",
                            "width": 1,
                            "height": 1,
                            "hidden": True,
                        },
                        {
                            "element_type": "button",
                            "accessible_label": "Compact desktop tool",
                            "width": 20,
                            "height": 20,
                            "desktop_only": True,
                            "spacing_exception": False,
                        },
                    ],
                }
            ],
        }
    )
    assert len(result["evidence"]) == 1
    assert result["verified_observations"]["confirmed_tap_target_failures"] == 0
    assert result["evidence"][0]["classification"] == "informational_small_target"


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


def test_copyright_year_range_is_preserved() -> None:
    current = datetime.now(UTC).year
    result = copyright_diagnostics({"copyright_text": f"Copyright 2018-{current} Example"})
    observations = result["verified_observations"]
    assert observations["year_range"] == [2018, current]
    assert observations["current_year_present"] is True
    assert observations["confidence_percent"] == 90


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
