from datetime import UTC, datetime
from typing import Any

import pytest
from worker_app.analysis.diagnostics import (
    _build_security_header_matrix,
    aggregate_html_standards,
    aggregate_page_security_scores,
    aggregate_responsiveness,
    aggregate_security_header_matrix,
    analytics_diagnostics,
    browser_compatibility,
    cache_diagnostics,
    classify_csp,
    collect_w3c,
    copyright_diagnostics,
    html_standards_validation,
    page_security_risk_score,
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
    data = {
        "responsive_results": [],
        "page_javascript_errors": [],
        "main_response_headers": {"server": "nginx"},
    }
    matrix = browser_compatibility(data)["verified_observations"]["matrix"]
    assert matrix["chromium"] == {"tested": True, "result": "passed"}
    assert matrix["firefox"]["result"] == "not_tested"
    assert matrix["webkit"]["result"] == "not_tested"


def test_copyright_current_outdated_and_unknown() -> None:
    current = datetime.now(UTC).year
    current_result = copyright_diagnostics(
        {"copyright_text": f"© {current} Example", "final_url": "https://example.com/"}
    )
    assert current_result["verified_observations"]["result"] == "current_year_detected"
    assert current_result["verified_observations"]["freshness_status"] == "current"
    assert current_result["verified_observations"]["detected"] is True
    assert current_result["verified_observations"]["current_year"] == current

    outdated_result = copyright_diagnostics(
        {"copyright_text": "Copyright 2019 Example", "final_url": "https://example.com/"}
    )
    assert outdated_result["verified_observations"]["result"] == "possibly_outdated"
    assert outdated_result["verified_observations"]["freshness_status"] == "possibly_outdated"

    missing_result = copyright_diagnostics({})
    assert missing_result["verified_observations"]["result"] == "unknown"
    assert missing_result["verified_observations"]["freshness_status"] == "unavailable"
    assert missing_result["verified_observations"]["detected"] is False


def test_copyright_year_range_is_preserved() -> None:
    current = datetime.now(UTC).year
    result = copyright_diagnostics(
        {"copyright_text": f"Copyright 2018-{current} Example", "final_url": "https://example.com/"}
    )
    observations = result["verified_observations"]
    assert observations["year_range"] == [2018, current]
    assert observations["current_year_present"] is True
    assert observations["confidence_percent"] == 90
    assert observations["start_year"] == 2018
    assert observations["end_year"] == current
    assert observations["freshness_status"] == "current"
    assert observations["evidence_url"] == "https://example.com/"


def test_copyright_single_year() -> None:
    result = copyright_diagnostics(
        {"copyright_text": "© 2025 Company", "final_url": "https://example.com/"}
    )
    observations = result["verified_observations"]
    assert observations["single_year"] == 2025
    assert observations["start_year"] == 2025
    assert observations["end_year"] == 2025
    assert observations["detected"] is True


def test_copyright_inconsistent_footer_values() -> None:
    result = copyright_diagnostics(
        {"copyright_text": "© 2020 – 2023 Company", "final_url": "https://example.com/"}
    )
    observations = result["verified_observations"]
    assert observations["start_year"] == 2020
    assert observations["end_year"] == 2023
    assert observations["freshness_status"] == "possibly_outdated"


def test_policy_explicit_date_current_and_no_inference(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self, limit: int) -> bytes:
            date = datetime.now(UTC).strftime("%B %d, %Y")
            return f"<title>Privacy Policy</title><p>Last updated: {date}</p>".encode()

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
    detail = result["verified_observations"]["privacy_policy_detail"]
    assert detail["found"] is True
    assert detail["freshness_status"] == "current"
    assert detail["explicit_update_date"] is not None
    assert detail["age_days"] is not None
    assert detail["age_days"] <= 1
    assert detail["title"] == "Privacy Policy"
    assert detail["checked_at"] is not None


def test_policy_found_but_no_date(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self, limit: int) -> bytes:
            return b"<title>Privacy Policy</title><p>We respect your privacy.</p>"

    monkeypatch.setattr(
        "worker_app.analysis.diagnostics.urllib.request.urlopen", lambda *args, **kwargs: Response()
    )
    result = policy_diagnostics(
        {
            "final_url": "https://example.com/",
            "policy_links": {"privacy": "https://example.com/privacy"},
        },
        timeout=1,
    )
    detail = result["verified_observations"]["privacy_policy_detail"]
    assert detail["found"] is True
    assert detail["freshness_status"] == "date_not_published"
    assert detail["explicit_update_date"] is None
    assert detail["age_days"] is None


def test_policy_date_older_than_one_year(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self, limit: int) -> bytes:
            return b"<p>Last updated: January 01, 2020</p>"

    monkeypatch.setattr(
        "worker_app.analysis.diagnostics.urllib.request.urlopen", lambda *args, **kwargs: Response()
    )
    result = policy_diagnostics(
        {
            "final_url": "https://example.com/",
            "policy_links": {"privacy": "https://example.com/privacy"},
        },
        timeout=1,
    )
    detail = result["verified_observations"]["privacy_policy_detail"]
    assert detail["found"] is True
    assert detail["freshness_status"] == "older_than_one_year"
    assert detail["age_days"] > 365
    assert any(item.get("code") == "PRIVACY_POLICY_STALE" for item in result["evidence"])


def test_policy_ignores_misleading_dates(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self, limit: int) -> bytes:
            return b"<p>Copyright 2024. Sitemap lastmod 2024-06-01. We care about privacy.</p>"

    monkeypatch.setattr(
        "worker_app.analysis.diagnostics.urllib.request.urlopen", lambda *args, **kwargs: Response()
    )
    result = policy_diagnostics(
        {
            "final_url": "https://example.com/",
            "policy_links": {"privacy": "https://example.com/privacy"},
            "main_response_headers": {"last-modified": "Mon, 01 Jan 2024 00:00:00 GMT"},
        },
        timeout=1,
    )
    detail = result["verified_observations"]["privacy_policy_detail"]
    assert detail["found"] is True
    assert detail["freshness_status"] == "date_not_published"
    assert detail["explicit_update_date"] is None


def test_policy_revised_date_label(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self, limit: int) -> bytes:
            return f"<p>Revised: {datetime.now(UTC).strftime('%B %d, %Y')}</p>".encode()

    monkeypatch.setattr(
        "worker_app.analysis.diagnostics.urllib.request.urlopen", lambda *args, **kwargs: Response()
    )
    result = policy_diagnostics(
        {
            "final_url": "https://example.com/",
            "policy_links": {"privacy": "https://example.com/privacy"},
        },
        timeout=1,
    )
    detail = result["verified_observations"]["privacy_policy_detail"]
    assert detail["found"] is True
    assert detail["date_label"].lower() == "revised"
    assert detail["freshness_status"] == "current"


def test_policy_multiple_candidates_uses_first(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self, limit: int) -> bytes:
            return b"<p>Effective date: January 15, 2024</p><p>Last updated: March 01, 2025</p>"

    monkeypatch.setattr(
        "worker_app.analysis.diagnostics.urllib.request.urlopen", lambda *args, **kwargs: Response()
    )
    result = policy_diagnostics(
        {
            "final_url": "https://example.com/",
            "policy_links": {"privacy": "https://example.com/privacy"},
        },
        timeout=1,
    )
    detail = result["verified_observations"]["privacy_policy_detail"]
    assert detail["found"] is True
    assert detail["explicit_update_date"] == "2024-01-15"
    assert detail["date_label"].lower() == "effective date"


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


def test_terms_pdf_is_not_asserted_as_a_privacy_policy() -> None:
    result = policy_diagnostics(
        {
            "final_url": "https://example.com/",
            "policy_links": {"privacy": "https://example.com/documents/terms-conditions.pdf"},
        },
        timeout=1,
    )
    observations = result["verified_observations"]
    assert observations["privacy_policy"] is None
    assert (
        observations["policy_verification_status"]
        == "Potential policy document — manual verification required"
    )
    assert "verified_privacy_policy" in result["unavailable_observations"]


def test_policy_missing() -> None:
    result = policy_diagnostics(
        {"final_url": "https://example.com/", "policy_links": {}},
        timeout=1,
    )
    detail = result["verified_observations"]["privacy_policy_detail"]
    assert detail["found"] is False
    assert detail["freshness_status"] == "unavailable"
    assert any(item.get("code") == "PRIVACY_POLICY_MISSING" for item in result["evidence"])


# --- Security Header Matrix Tests ---


def test_security_header_matrix_all_present() -> None:
    result = security_diagnostics(
        {
            "https_usage": True,
            "mixed_content_count": 0,
            "final_url": "https://example.com/",
            "main_response_headers": {
                "content-security-policy": (
                    "default-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
                ),
                "strict-transport-security": "max-age=31536000",
                "x-content-type-options": "nosniff",
                "referrer-policy": "strict-origin-when-cross-origin",
                "permissions-policy": "camera=(), microphone=()",
                "x-frame-options": "DENY",
                "cross-origin-opener-policy": "same-origin",
                "cross-origin-resource-policy": "same-origin",
            },
        }
    )
    matrix = result["verified_observations"]["security_header_matrix"]
    assert isinstance(matrix, list)
    assert len(matrix) == 8
    statuses = {item["header"]: item["status"] for item in matrix}
    assert statuses["strict-transport-security"] == "present"
    assert statuses["content-security-policy"] == "present"
    assert statuses["x-content-type-options"] == "present"
    assert statuses["referrer-policy"] == "present"
    assert statuses["permissions-policy"] == "present"
    assert statuses["x-frame-options"] == "present"
    assert all(item["recommendation"] is None for item in matrix if item["status"] == "present")


def test_security_header_matrix_missing_headers() -> None:
    result = security_diagnostics(
        {
            "https_usage": True,
            "mixed_content_count": 0,
            "final_url": "https://example.com/",
            "main_response_headers": {},
        }
    )
    matrix = result["verified_observations"]["security_header_matrix"]
    missing = [item for item in matrix if item["status"] == "missing"]
    assert len(missing) == 8
    for item in missing:
        assert item["recommendation"] is not None
        assert item["observed_value"] is None
        assert item["example_urls"] == ["https://example.com/"]


def test_security_header_matrix_malformed_xcto() -> None:
    result = security_diagnostics(
        {
            "https_usage": False,
            "mixed_content_count": 0,
            "final_url": "https://example.com/",
            "main_response_headers": {
                "x-content-type-options": "wrong-value",
            },
        }
    )
    matrix = result["verified_observations"]["security_header_matrix"]
    xcto = next(item for item in matrix if item["header"] == "x-content-type-options")
    assert xcto["status"] == "malformed"
    assert xcto["observed_value"] == "wrong-value"
    assert xcto["recommendation"] is not None


def test_security_header_matrix_csp_frame_ancestors_substitutes_xfo() -> None:
    result = security_diagnostics(
        {
            "https_usage": False,
            "mixed_content_count": 0,
            "final_url": "https://example.com/",
            "main_response_headers": {
                "content-security-policy": "default-src 'self'; frame-ancestors 'none'",
            },
        }
    )
    matrix = result["verified_observations"]["security_header_matrix"]
    xfo = next(item for item in matrix if item["header"] == "x-frame-options")
    assert xfo["status"] == "not_applicable"
    assert xfo["recommendation"] is None
    assert not any(
        item["code"] == "FRAME_PROTECTION_MISSING" for item in result["score"]["deductions"]
    )


def test_security_header_matrix_different_headers_across_pages() -> None:
    headers_a = {"strict-transport-security": "max-age=31536000"}
    headers_b = {}
    matrix_a = _build_security_header_matrix(
        {k.lower(): v for k, v in headers_a.items()}, None, "https://example.com/a"
    )
    matrix_b = _build_security_header_matrix(
        {k.lower(): v for k, v in headers_b.items()}, None, "https://example.com/b"
    )
    hsts_a = next(item for item in matrix_a if item["header"] == "strict-transport-security")
    hsts_b = next(item for item in matrix_b if item["header"] == "strict-transport-security")
    assert hsts_a["status"] == "present"
    assert hsts_b["status"] == "missing"
    assert hsts_a["example_urls"] == ["https://example.com/a"]
    assert hsts_b["example_urls"] == ["https://example.com/b"]


# --- Analytics Detection Tests ---


def test_analytics_ga4_detected() -> None:
    result = analytics_diagnostics(
        {
            "script_evidence": "gtag('config', 'G-ABCDEF1234');",
            "network_urls": ["https://www.google-analytics.com/g/collect"],
            "final_url": "https://example.com/",
        }
    )
    obs = result["verified_observations"]
    assert obs["detected"] is True
    assert obs["ga4_detected"] is True
    assert "G-ABCDEF1234" in obs["ga4_measurement_ids"]
    assert "GA4" in obs["technologies"]
    assert "gtag.js" in obs["technologies"]
    assert "Google Analytics 4" in obs["providers"]
    assert obs["confidence"] == 90
    assert "inline_script" in obs["evidence_sources"]
    assert "network_request" in obs["evidence_sources"]


def test_analytics_gtm_detected() -> None:
    result = analytics_diagnostics(
        {
            "script_evidence": "window.dataLayer = []; (function(w,d,s,l,i){GTM-XXXYYY})()",
            "network_urls": ["https://www.googletagmanager.com/gtm.js?id=GTM-XXXYYY"],
            "final_url": "https://example.com/",
        }
    )
    obs = result["verified_observations"]
    assert obs["detected"] is True
    assert obs["gtm_detected"] is True
    assert "GTM-XXXYYY" in obs["gtm_container_ids"]
    assert "GTM" in obs["technologies"]
    assert "dataLayer" in obs["technologies"]
    assert "Google Tag Manager" in obs["providers"]


def test_analytics_both_ga4_and_gtm() -> None:
    result = analytics_diagnostics(
        {
            "script_evidence": "gtag('config', 'G-ABC123'); dataLayer GTM-XYZ789",
            "network_urls": [
                "https://www.google-analytics.com/g/collect",
                "https://www.googletagmanager.com/gtm.js",
            ],
            "final_url": "https://example.com/",
        }
    )
    obs = result["verified_observations"]
    assert obs["ga4_detected"] is True
    assert obs["gtm_detected"] is True
    assert "GA4" in obs["technologies"]
    assert "GTM" in obs["technologies"]
    assert len(obs["public_identifiers"]) >= 2


def test_analytics_no_analytics() -> None:
    result = analytics_diagnostics(
        {
            "script_evidence": "var x = 1;",
            "network_urls": ["https://example.com/app.js"],
            "final_url": "https://example.com/",
        }
    )
    obs = result["verified_observations"]
    assert obs["detected"] is False
    assert obs["ga4_detected"] is False
    assert obs["gtm_detected"] is False
    assert obs["technologies"] == []
    assert obs["providers"] == []
    assert obs["confidence"] == 0


def test_analytics_false_positive_resistant() -> None:
    result = analytics_diagnostics(
        {
            "script_evidence": "var game_tag = 'GAME-123456'; var gtm_like = 'not-real';",
            "network_urls": ["https://example.com/analytics-dashboard"],
            "final_url": "https://example.com/",
        }
    )
    obs = result["verified_observations"]
    assert obs["ga4_detected"] is False
    assert obs["gtm_detected"] is False
    assert "G-" not in str(obs["public_identifiers"])


# --- Report Integration Tests ---


def test_report_executive_values_no_unsupported_claims() -> None:
    """Executive diagnostics do not claim traffic, visitors, or compliance."""
    analytics = analytics_diagnostics(
        {
            "script_evidence": "G-TESTID gtag",
            "network_urls": [],
            "final_url": "https://example.com/",
        }
    )
    obs_str = str(analytics["verified_observations"])
    for banned in ("visitors", "traffic", "sessions", "revenue", "conversion", "rankings"):
        assert banned not in obs_str.lower()

    copyright_result = copyright_diagnostics({"copyright_text": "© 2025 Company"})
    limitations = " ".join(copyright_result["limitations"])
    assert "legal ownership" not in limitations or "does not prove" in limitations


def test_report_technical_evidence_retained() -> None:
    """Technical evidence fields are retained for detailed view."""
    result = security_diagnostics(
        {
            "https_usage": True,
            "mixed_content_count": 0,
            "final_url": "https://example.com/",
            "main_response_headers": {
                "strict-transport-security": "max-age=31536000; includeSubDomains",
                "content-security-policy": "default-src 'self'",
                "x-content-type-options": "nosniff",
            },
        }
    )
    matrix = result["verified_observations"]["security_header_matrix"]
    hsts = next(item for item in matrix if item["header"] == "strict-transport-security")
    assert hsts["observed_value"] == "max-age=31536000; includeSubDomains"
    assert hsts["example_urls"] == ["https://example.com/"]


# --- Multi-page security header aggregation tests ---


def test_aggregate_security_all_pages_present() -> None:
    pages = [
        {
            "url": "https://example.com/",
            "security_observations": {
                "strict_transport_security": "max-age=31536000",
                "content_security_policy": "default-src 'self'",
                "x_frame_options": "DENY",
                "x_content_type_options": "nosniff",
                "referrer_policy": "strict-origin",
                "permissions_policy": "camera=()",
                "cross_origin_opener_policy": "same-origin",
                "cross_origin_resource_policy": "same-origin",
            },
        },
        {
            "url": "https://example.com/about",
            "security_observations": {
                "strict_transport_security": "max-age=31536000",
                "content_security_policy": "default-src 'self'",
                "x_frame_options": "DENY",
                "x_content_type_options": "nosniff",
                "referrer_policy": "strict-origin",
                "permissions_policy": "camera=()",
                "cross_origin_opener_policy": "same-origin",
                "cross_origin_resource_policy": "same-origin",
            },
        },
    ]
    matrix = aggregate_security_header_matrix(pages)
    hsts = next(h for h in matrix if h["header"] == "strict-transport-security")
    assert hsts["pages_checked"] == 2
    assert hsts["pages_present"] == 2
    assert hsts["pages_missing"] == 0
    assert hsts["coverage_percent"] == 100.0
    assert hsts["consistency_status"] == "consistent_present"
    assert hsts["recommendation"] is None


def test_aggregate_security_inconsistent_across_pages() -> None:
    pages = [
        {
            "url": "https://example.com/",
            "security_observations": {
                "strict_transport_security": "max-age=31536000",
                "content_security_policy": "default-src 'self'",
                "x_content_type_options": "nosniff",
            },
        },
        {
            "url": "https://example.com/about",
            "security_observations": {
                "strict_transport_security": None,
                "content_security_policy": None,
                "x_content_type_options": "nosniff",
            },
        },
    ]
    matrix = aggregate_security_header_matrix(pages)
    hsts = next(h for h in matrix if h["header"] == "strict-transport-security")
    assert hsts["pages_present"] == 1
    assert hsts["pages_missing"] == 1
    assert hsts["consistency_status"] == "inconsistent"
    assert hsts["coverage_percent"] == 50.0
    assert len(hsts["example_present_urls"]) == 1
    assert len(hsts["example_missing_urls"]) == 1


def test_aggregate_security_consistently_missing() -> None:
    pages = [
        {"url": "https://a.com/", "security_observations": {"strict_transport_security": None}},
        {"url": "https://a.com/b", "security_observations": {"strict_transport_security": None}},
    ]
    matrix = aggregate_security_header_matrix(pages)
    hsts = next(h for h in matrix if h["header"] == "strict-transport-security")
    assert hsts["consistency_status"] == "consistently_missing"
    assert hsts["recommendation"] is not None


def test_aggregate_security_malformed_xcto() -> None:
    pages = [
        {
            "url": "https://example.com/",
            "security_observations": {"x_content_type_options": "wrong-value"},
        },
    ]
    matrix = aggregate_security_header_matrix(pages)
    xcto = next(h for h in matrix if h["header"] == "x-content-type-options")
    assert xcto["pages_malformed"] == 1
    assert xcto["consistency_status"] == "malformed"


def test_aggregate_security_csp_frame_ancestors_makes_xfo_not_applicable() -> None:
    pages = [
        {
            "url": "https://example.com/",
            "security_observations": {
                "x_frame_options": None,
                "content_security_policy": "frame-ancestors 'self'",
            },
        },
    ]
    matrix = aggregate_security_header_matrix(pages)
    xfo = next(h for h in matrix if h["header"] == "x-frame-options")
    assert xfo["pages_not_applicable"] == 1
    assert xfo["consistency_status"] == "consistent_present"


def test_aggregate_security_no_pages() -> None:
    matrix = aggregate_security_header_matrix([])
    for item in matrix:
        assert item["pages_checked"] == 0
        assert item["consistency_status"] == "insufficient_evidence"


def test_aggregate_security_math_invariants() -> None:
    """pages_checked == pages_present + pages_missing + pages_malformed + pages_not_applicable."""
    pages = [
        {
            "url": "https://example.com/",
            "security_observations": {
                "strict_transport_security": "max-age=31536000",
                "x_content_type_options": "wrong",
                "x_frame_options": None,
                "content_security_policy": "frame-ancestors 'self'",
            },
        },
        {
            "url": "https://example.com/about",
            "security_observations": {
                "strict_transport_security": None,
                "x_content_type_options": "nosniff",
                "x_frame_options": "DENY",
            },
        },
    ]
    matrix = aggregate_security_header_matrix(pages)
    for item in matrix:
        total = (
            item["pages_present"]
            + item["pages_missing"]
            + item["pages_malformed"]
            + item["pages_not_applicable"]
        )
        msg = f"{item['header']}: {item['pages_checked']} != {total}"
        assert item["pages_checked"] == total, msg


# --- Responsiveness aggregation tests ---


def test_aggregate_responsiveness_all_responsive() -> None:
    pages = [
        {
            "url": "https://example.com/",
            "responsive_results": [
                {"name": "mobile_portrait", "status": "passed", "horizontal_overflow": False},
                {"name": "desktop", "status": "passed", "horizontal_overflow": False},
            ],
        },
        {
            "url": "https://example.com/about",
            "responsive_results": [
                {"name": "mobile_portrait", "status": "passed", "horizontal_overflow": False},
                {"name": "desktop", "status": "passed", "horizontal_overflow": False},
            ],
        },
    ]
    result = aggregate_responsiveness(pages)
    assert result["pages_tested"] == 2
    assert result["responsive_pages"] == 2
    assert result["site_status"] == "responsive"
    assert result["mobile_pass_percent"] == 100.0
    assert result["desktop_pass_percent"] == 100.0


def test_aggregate_responsiveness_partially_responsive() -> None:
    pages = [
        {
            "url": "https://example.com/",
            "responsive_results": [
                {"name": "mobile_portrait", "status": "passed", "horizontal_overflow": False},
                {"name": "desktop", "status": "passed", "horizontal_overflow": False},
            ],
        },
        {
            "url": "https://example.com/about",
            "responsive_results": [
                {"name": "mobile_portrait", "status": "passed", "horizontal_overflow": True},
                {"name": "desktop", "status": "passed", "horizontal_overflow": False},
            ],
        },
    ]
    result = aggregate_responsiveness(pages)
    assert result["pages_tested"] == 2
    assert result["responsive_pages"] == 1
    assert result["partially_responsive_pages"] == 1
    assert result["site_status"] == "partially_responsive"


def test_aggregate_responsiveness_not_responsive() -> None:
    pages = [
        {
            "url": "https://example.com/",
            "responsive_results": [
                {"name": "mobile_portrait", "status": "failed"},
                {"name": "desktop", "status": "failed"},
            ],
        },
    ]
    result = aggregate_responsiveness(pages)
    assert result["pages_tested"] == 1
    assert result["not_responsive_pages"] == 1
    assert result["site_status"] == "not_responsive"


def test_aggregate_responsiveness_no_viewport_data() -> None:
    pages = [
        {"url": "https://example.com/"},
        {"url": "https://example.com/about"},
    ]
    result = aggregate_responsiveness(pages)
    assert result["pages_tested"] == 0
    assert result["site_status"] == "unavailable"
    assert len(result["per_page"]) == 2
    assert all(p["status"] == "unavailable" for p in result["per_page"])


def test_aggregate_responsiveness_empty_pages() -> None:
    result = aggregate_responsiveness([])
    assert result["pages_tested"] == 0
    assert result["site_status"] == "unavailable"


def test_aggregate_responsiveness_mobile_tablet_desktop_split() -> None:
    pages = [
        {
            "url": "https://example.com/",
            "responsive_results": [
                {"name": "mobile_portrait", "status": "passed", "horizontal_overflow": False},
                {"name": "mobile_landscape", "status": "passed", "horizontal_overflow": True},
                {"name": "tablet", "status": "passed", "horizontal_overflow": False},
                {"name": "laptop", "status": "passed", "horizontal_overflow": False},
                {"name": "desktop", "status": "passed", "horizontal_overflow": False},
            ],
        },
    ]
    result = aggregate_responsiveness(pages)
    assert result["mobile_pass_percent"] == 50.0
    assert result["tablet_pass_percent"] == 100.0
    assert result["desktop_pass_percent"] == 100.0


def test_aggregate_responsiveness_math_invariants() -> None:
    """Sum of classified pages equals pages_tested."""
    pages = [
        {
            "url": "https://example.com/",
            "responsive_results": [
                {"name": "mobile_portrait", "status": "passed", "horizontal_overflow": False},
                {"name": "desktop", "status": "passed", "horizontal_overflow": False},
            ],
        },
        {
            "url": "https://example.com/about",
            "responsive_results": [
                {"name": "mobile_portrait", "status": "failed"},
                {"name": "desktop", "status": "failed"},
            ],
        },
    ]
    result = aggregate_responsiveness(pages)
    classified = (
        result["responsive_pages"]
        + result["partially_responsive_pages"]
        + result["not_responsive_pages"]
        + result["inconclusive_pages"]
    )
    assert classified == result["pages_tested"]


# --- Browser compatibility false-positive tests ---


def test_browser_unavailable_engine_produces_no_finding() -> None:
    result = browser_compatibility({})
    assert result["status"] == "unavailable"
    assert result["verified_observations"]["matrix"] == {}


def test_browser_with_data_still_works() -> None:
    result = browser_compatibility(
        {
            "responsive_results": [
                {"name": "mobile", "status": "passed", "horizontal_overflow": False}
            ],
            "main_response_headers": {"server": "nginx"},
        }
    )
    assert result["status"] == "available"
    assert result["verified_observations"]["matrix"]["chromium"]["tested"] is True


# --- Report integration: multi-page observations ---


def test_aggregate_security_observed_values_retained() -> None:
    """Each unique header value across pages is retained in observed_values."""
    pages = [
        {
            "url": "https://example.com/",
            "security_observations": {
                "strict_transport_security": "max-age=31536000",
            },
        },
        {
            "url": "https://example.com/about",
            "security_observations": {
                "strict_transport_security": "max-age=86400",
            },
        },
    ]
    matrix = aggregate_security_header_matrix(pages)
    hsts = next(h for h in matrix if h["header"] == "strict-transport-security")
    assert "max-age=31536000" in hsts["observed_values"]
    assert "max-age=86400" in hsts["observed_values"]
    assert hsts["consistency_status"] == "consistent_present"


def test_aggregate_responsiveness_per_page_status() -> None:
    """Per-page results contain status and viewport counts."""
    pages = [
        {
            "url": "https://example.com/",
            "responsive_results": [
                {"name": "mobile", "status": "passed", "horizontal_overflow": False},
                {"name": "desktop", "status": "passed", "horizontal_overflow": False},
            ],
        },
    ]
    result = aggregate_responsiveness(pages)
    assert len(result["per_page"]) == 1
    assert result["per_page"][0]["status"] == "responsive"
    assert result["per_page"][0]["viewports_passed"] == 2
    assert result["per_page"][0]["viewports_total"] == 2


# --- HTML Standards Validation tests ---

VALID_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Valid Page</title>
</head>
<body><h1>Hello</h1><p>World</p></body>
</html>"""

INVALID_STRUCTURE_HTML = """<!DOCTYPE html>
<html>
<head><title></title></head>
<body>
<div id="dup"></div><div id="dup"></div>
<h1>Title</h1><h3>Skipped h2</h3>
<font color="red">Old element</font>
<center>Deprecated</center>
</body>
</html>"""


def test_html_standards_valid_document() -> None:
    result = html_standards_validation(VALID_HTML, "https://example.com/")
    obs = result["verified_observations"]
    assert obs["validation_status"] == "valid"
    assert obs["errors_count"] == 0
    assert obs["warnings_count"] == 0
    assert obs["standards_score"] == 100
    assert obs["validator_name"] == "ZuiGO HTML Standards"
    assert obs["score_version"] == "1.0.0"


def test_html_standards_invalid_structure() -> None:
    result = html_standards_validation(INVALID_STRUCTURE_HTML, "https://example.com/")
    obs = result["verified_observations"]
    assert obs["validation_status"] == "issues_found"
    assert obs["errors_count"] > 0 or obs["warnings_count"] > 0
    assert obs["standards_score"] < 100
    codes = [i["code"] for i in obs["issues"]]
    assert "MISSING_LANG" in codes
    assert "EMPTY_TITLE" in codes
    assert "DUPLICATE_ID" in codes
    assert "HEADING_SKIP_LEVEL" in codes
    assert "DEPRECATED_ELEMENT" in codes


def test_html_standards_duplicate_ids() -> None:
    doc = '<html lang="en"><head><title>T</title></head><body>'
    doc += '<div id="x"></div><div id="x"></div><div id="x"></div>'
    doc += "</body></html>"
    result = html_standards_validation(doc, "https://example.com/")
    obs = result["verified_observations"]
    dup = [i for i in obs["issues"] if i["code"] == "DUPLICATE_ID"]
    assert len(dup) == 1
    assert dup[0]["count"] == 3


def test_html_standards_malformed_metadata() -> None:
    doc = """<!DOCTYPE html><html lang="en"><head>
    <title>T</title>
    <meta name="description" content="A">
    <meta name="description" content="B">
    <meta name="viewport" content="width=device-width">
    <meta name="viewport" content="width=device-width">
    <meta charset="utf-8">
    <meta charset="utf-8">
    </head><body><h1>H</h1></body></html>"""
    result = html_standards_validation(doc, "https://example.com/")
    obs = result["verified_observations"]
    codes = [i["code"] for i in obs["issues"]]
    assert "DUPLICATE_META" in codes
    assert "DUPLICATE_CHARSET" in codes


def test_html_standards_deprecated_markup() -> None:
    doc = '<html lang="en"><head><title>T</title></head><body>'
    doc += "<marquee>Scroll</marquee><blink>Blink</blink>"
    doc += "</body></html>"
    result = html_standards_validation(doc, "https://example.com/")
    obs = result["verified_observations"]
    deprecated = [i for i in obs["issues"] if i["code"] == "DEPRECATED_ELEMENT"]
    tags = {i["element"] for i in deprecated}
    assert "marquee" in tags
    assert "blink" in tags


def test_html_standards_duplicate_canonical() -> None:
    doc = """<!DOCTYPE html><html lang="en"><head><title>T</title>
    <link rel="canonical" href="https://a.com/">
    <link rel="canonical" href="https://b.com/">
    </head><body><h1>H</h1></body></html>"""
    result = html_standards_validation(doc, "https://example.com/")
    obs = result["verified_observations"]
    codes = [i["code"] for i in obs["issues"]]
    assert "DUPLICATE_CANONICAL" in codes


def test_html_standards_malformed_viewport() -> None:
    doc = """<!DOCTYPE html><html lang="en"><head><title>T</title>
    <meta name="viewport" content="width=device-width, bogus-key=1">
    </head><body><h1>H</h1></body></html>"""
    result = html_standards_validation(doc, "https://example.com/")
    obs = result["verified_observations"]
    codes = [i["code"] for i in obs["issues"]]
    assert "UNKNOWN_VIEWPORT_KEY" in codes


def test_html_standards_empty_html() -> None:
    result = html_standards_validation("", "https://example.com/")
    assert result["status"] == "unavailable"
    obs = result["verified_observations"]
    assert obs["validation_status"] == "unavailable"
    assert obs["standards_score"] is None


def test_html_standards_unavailable_inconclusive() -> None:
    result = html_standards_validation("", "https://example.com/")
    assert result["verified_observations"]["validation_status"] == "unavailable"


def test_html_standards_score_bounded() -> None:
    """Score is always 0-100 even with many issues."""
    doc = "<html><head></head><body>"
    for i in range(50):
        doc += f'<div id="d{i}"></div><div id="d{i}"></div>'
    doc += "<font>x</font>" * 30
    doc += "</body></html>"
    result = html_standards_validation(doc, "https://example.com/")
    obs = result["verified_observations"]
    assert 0 <= obs["standards_score"] <= 100


def test_html_standards_deterministic() -> None:
    """Same input produces same output."""
    r1 = html_standards_validation(VALID_HTML, "https://example.com/")
    r2 = html_standards_validation(VALID_HTML, "https://example.com/")
    assert (
        r1["verified_observations"]["standards_score"]
        == r2["verified_observations"]["standards_score"]
    )
    assert (
        r1["verified_observations"]["errors_count"] == r2["verified_observations"]["errors_count"]
    )


def test_html_standards_template_issue_grouping() -> None:
    pages = [
        {
            "validation_status": "issues_found",
            "errors_count": 2,
            "warnings_count": 1,
            "standards_score": 80,
            "issues": [
                {"code": "DUPLICATE_ID"},
                {"code": "DUPLICATE_ID"},
                {"code": "MISSING_LANG"},
            ],
        },
        {
            "validation_status": "issues_found",
            "errors_count": 1,
            "warnings_count": 1,
            "standards_score": 90,
            "issues": [
                {"code": "DUPLICATE_ID"},
                {"code": "MISSING_VIEWPORT"},
            ],
        },
    ]
    agg = aggregate_html_standards(pages)
    assert agg["pages_checked"] == 2
    assert agg["pages_with_errors"] == 2
    assert agg["total_errors"] == 3
    assert agg["total_warnings"] == 2
    assert agg["average_standards_score"] == 85.0
    groups = {g["code"]: g["occurrences"] for g in agg["common_issue_groups"]}
    assert groups["DUPLICATE_ID"] == 3


def test_html_standards_malformed_links() -> None:
    doc = '<html lang="en"><head><title>T</title></head><body>'
    doc += '<h1>H</h1><a href="">empty</a><a href="">empty2</a>'
    doc += '<img src=""><script src=""></script>'
    doc += "</body></html>"
    result = html_standards_validation(doc, "https://example.com/")
    obs = result["verified_observations"]
    codes = [i["code"] for i in obs["issues"]]
    assert "EMPTY_HREF" in codes
    assert "EMPTY_SRC" in codes


# --- Page Security & Risk Score tests ---


def test_security_risk_strong_evidence() -> None:
    obs = {
        "https": True,
        "strict_transport_security": "max-age=31536000",
        "content_security_policy": "default-src 'self'",
        "x_frame_options": "DENY",
        "x_content_type_options": "nosniff",
        "referrer_policy": "strict-origin",
        "permissions_policy": "camera=()",
        "cross_origin_opener_policy": "same-origin",
        "cross_origin_resource_policy": "same-origin",
        "server": None,
        "x_powered_by": None,
    }
    result = page_security_risk_score(obs, csp_quality="strong")
    assert result["score"] == 100
    assert result["risk_band"] == "strong"
    assert result["score_version"] == "1.0.0"
    assert len(result["deductions"]) == 0
    assert result["evidence_coverage"] > 80
    assert result["confidence"] == "high"


def test_security_risk_missing_headers() -> None:
    obs = {
        "https": True,
        "strict_transport_security": None,
        "content_security_policy": None,
        "x_frame_options": None,
        "x_content_type_options": None,
        "referrer_policy": None,
        "permissions_policy": None,
        "cross_origin_opener_policy": None,
        "cross_origin_resource_policy": None,
        "server": "Apache/2.4",
        "x_powered_by": "PHP/8.1",
    }
    result = page_security_risk_score(obs)
    assert result["score"] < 50
    assert result["risk_band"] in ("weak", "high_observable_risk")
    assert len(result["deductions"]) > 5
    codes = [d["code"] for d in result["deductions"]]
    assert "CSP_MISSING" in codes
    assert "HSTS_MISSING" in codes
    assert "SERVER_EXPOSED" in codes
    assert "FRAME_PROTECTION_MISSING" in codes


def test_security_risk_malformed_csp() -> None:
    obs = {
        "https": True,
        "content_security_policy": "upgrade-insecure-requests",
        "x_content_type_options": "nosniff",
    }
    result = page_security_risk_score(obs, csp_quality="upgrade_only")
    codes = [d["code"] for d in result["deductions"]]
    assert "CSP_WEAK" in codes
    assert "CSP_MISSING" not in codes


def test_security_risk_https_absent() -> None:
    obs = {"https": False}
    result = page_security_risk_score(obs)
    codes = [d["code"] for d in result["deductions"]]
    assert "HTTPS_ABSENT" in codes
    assert result["score"] <= 75


def test_security_risk_mixed_content() -> None:
    obs = {"https": True, "content_security_policy": "default-src 'self'"}
    result = page_security_risk_score(obs, mixed_content_count=3)
    codes = [d["code"] for d in result["deductions"]]
    assert "MIXED_CONTENT" in codes


def test_security_risk_incomplete_evidence_not_pass() -> None:
    """Missing evidence must not equal passing."""
    obs: dict[str, Any] = {}
    result = page_security_risk_score(obs)
    assert result["evidence_coverage"] < 50
    assert result["confidence"] == "low"
    assert result["score"] == 100
    assert result["evidence_coverage"] < 20


def test_security_risk_score_always_bounded() -> None:
    obs = {
        "https": False,
        "strict_transport_security": None,
        "content_security_policy": None,
        "x_frame_options": None,
        "x_content_type_options": None,
        "referrer_policy": None,
        "permissions_policy": None,
        "cross_origin_opener_policy": None,
        "cross_origin_resource_policy": None,
        "server": "nginx",
        "x_powered_by": "Express",
    }
    result = page_security_risk_score(obs, mixed_content_count=10)
    assert 0 <= result["score"] <= 100


def test_security_risk_deterministic() -> None:
    obs = {
        "https": True,
        "strict_transport_security": "max-age=31536000",
        "content_security_policy": None,
    }
    r1 = page_security_risk_score(obs)
    r2 = page_security_risk_score(obs)
    assert r1["score"] == r2["score"]
    assert r1["deductions"] == r2["deductions"]


def test_security_risk_version_retained() -> None:
    obs = {"https": True}
    result = page_security_risk_score(obs)
    assert result["score_version"] == "1.0.0"


def test_security_risk_deductions_explain_score() -> None:
    obs = {
        "https": True,
        "strict_transport_security": None,
        "content_security_policy": None,
    }
    result = page_security_risk_score(obs)
    total_deducted = sum(d["points"] for d in result["deductions"])
    assert result["score"] == max(0, 100 - total_deducted)


def test_security_risk_evidence_coverage_independent() -> None:
    """Evidence coverage reflects data availability, not score value."""
    full_obs = {
        "https": True,
        "strict_transport_security": None,
        "content_security_policy": None,
        "x_frame_options": None,
        "x_content_type_options": None,
        "referrer_policy": None,
        "permissions_policy": None,
        "cross_origin_opener_policy": None,
        "cross_origin_resource_policy": None,
        "server": "nginx",
        "x_powered_by": None,
    }
    full_result = page_security_risk_score(full_obs)
    partial_obs: dict[str, Any] = {"https": True}
    partial_result = page_security_risk_score(partial_obs)
    assert full_result["evidence_coverage"] > partial_result["evidence_coverage"]


# --- Site-wide security aggregation tests ---


def test_aggregate_security_scores_correct() -> None:
    pages = [
        {
            "url": "https://example.com/",
            "score": 90,
            "risk_band": "strong",
            "evidence_coverage": 80,
            "findings_used": ["HSTS_MISSING"],
        },
        {
            "url": "https://example.com/about",
            "score": 60,
            "risk_band": "needs_attention",
            "evidence_coverage": 75,
            "findings_used": ["CSP_MISSING", "HSTS_MISSING"],
        },
        {
            "url": "https://example.com/contact",
            "score": 40,
            "risk_band": "weak",
            "evidence_coverage": 90,
            "findings_used": ["CSP_MISSING", "HTTPS_ABSENT"],
        },
    ]
    agg = aggregate_page_security_scores(pages)
    assert agg["pages_scored"] == 3
    assert agg["average_score"] is not None
    expected_avg = round((90 + 60 + 40) / 3, 1)
    assert agg["average_score"] == expected_avg
    assert agg["median_score"] == 60
    assert agg["lowest_scoring_pages"][0]["score"] == 40
    assert len(agg["pages_needing_attention"]) == 2
    weaknesses = {w["code"]: w["affected_pages"] for w in agg["common_weaknesses"]}
    assert weaknesses["CSP_MISSING"] == 2
    assert weaknesses["HSTS_MISSING"] == 2


def test_aggregate_security_scores_empty() -> None:
    agg = aggregate_page_security_scores([])
    assert agg["pages_scored"] == 0
    assert agg["average_score"] is None
    assert agg["median_score"] is None


def test_aggregate_security_score_distribution() -> None:
    pages = [
        {
            "url": "https://a.com/",
            "score": 95,
            "risk_band": "strong",
            "evidence_coverage": 80,
            "findings_used": [],
        },
        {
            "url": "https://a.com/b",
            "score": 95,
            "risk_band": "strong",
            "evidence_coverage": 80,
            "findings_used": [],
        },
        {
            "url": "https://a.com/c",
            "score": 45,
            "risk_band": "weak",
            "evidence_coverage": 80,
            "findings_used": ["CSP_MISSING"],
        },
    ]
    agg = aggregate_page_security_scores(pages)
    assert agg["score_distribution"]["strong"] == 2
    assert agg["score_distribution"]["weak"] == 1
