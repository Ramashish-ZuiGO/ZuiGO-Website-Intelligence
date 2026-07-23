# ruff: noqa: E501

import html
import json
import re
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from worker_app.analysis.url_safety import UrlSafetyError, validate_public_url

FORMULA_VERSION = "1.0.0"
SECURITY_FORMULA_VERSION = "1.1.0"
TAP_TARGET_MINIMUM_CSS_PX = 24
TAP_TARGET_EVIDENCE_LIMIT = 20
SECURITY_DISCLAIMER = (
    "This passive security posture score is not a penetration-test result and does not "
    "prove the absence of vulnerabilities."
)


def score_result(
    inputs: dict[str, Any],
    deductions: list[dict[str, Any]],
    confidence: int,
    *,
    formula_version: str = FORMULA_VERSION,
) -> dict[str, Any]:
    return {
        "label": "ZuiGO-derived",
        "starting_score": 100,
        "inputs": inputs,
        "deductions": deductions,
        "final_score": max(0, 100 - sum(item["points"] for item in deductions)),
        "formula_version": formula_version,
        "confidence_percent": confidence,
    }


def group(
    status: str,
    observations: dict[str, Any],
    *,
    unavailable: list[str] | None = None,
    evidence: list[dict[str, Any]] | None = None,
    score: dict[str, Any] | None = None,
    limitations: list[str] | None = None,
    evidence_completeness: str | None = None,
    why_it_matters: str | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "verified_observations": observations,
        "unavailable_observations": unavailable or [],
        "evidence": evidence or [],
        "score": score,
        "limitations": limitations or [],
        "evidence_completeness": evidence_completeness or status,
        "why_it_matters": why_it_matters,
        "collected_at": datetime.now(UTC).isoformat(),
    }


def parse_w3c_response(payload: dict[str, Any], evidence_limit: int) -> dict[str, Any]:
    messages = payload.get("messages")
    if not isinstance(messages, list):
        raise ValueError("missing messages")
    errors = [item for item in messages if item.get("type") == "error"]
    warnings = [item for item in messages if item.get("type") in {"info", "warning"}]
    deductions = []
    if errors:
        deductions.append(
            {
                "code": "MARKUP_ERRORS",
                "reason": "5 points per verified error",
                "points": min(75, len(errors) * 5),
            }
        )
    if warnings:
        deductions.append(
            {
                "code": "MARKUP_WARNINGS",
                "reason": "1 point per verified warning",
                "points": min(25, len(warnings)),
            }
        )
    observations = {"error_count": len(errors), "warning_count": len(warnings)}
    evidence = []
    for item in messages[: max(0, evidence_limit)]:
        severity = "error" if item.get("type") == "error" else "warning"
        evidence.append(
            {
                "severity": severity,
                "validator_message": html.escape(str(item.get("message", ""))[:500]),
                "affected_element": html.escape(str(item.get("firstLine", ""))[:200]) or None,
                "line": item.get("lastLine") or item.get("firstLineNumber"),
                "column": item.get("lastColumn") or item.get("firstColumn"),
                "extract": html.escape(str(item.get("extract", ""))[:300]) or None,
                "diagnostic_code": html.escape(
                    str(item.get("subType") or f"W3C_{severity.upper()}")[:100]
                ),
                "evidence_source": "W3C validator",
            }
        )
    return group(
        "available",
        observations,
        evidence=evidence,
        score=score_result(observations, deductions, 100),
        limitations=["This is a ZuiGO-derived score, not an official W3C score."],
        evidence_completeness=(
            "bounded_complete" if len(messages) <= evidence_limit else "bounded_sample"
        ),
        why_it_matters="Validator messages identify the exact markup defects behind the derived deduction.",
    )


def collect_w3c(
    html: str, *, enabled: bool, endpoint: str, timeout: int, evidence_limit: int
) -> dict[str, Any]:
    if not enabled:
        return group("unavailable", {}, unavailable=["validation_disabled"])
    request = urllib.request.Request(
        endpoint,
        data=html.encode("utf-8"),
        headers={"Content-Type": "text/html; charset=utf-8", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return parse_w3c_response(json.loads(response.read()), evidence_limit)
    except (
        OSError,
        TimeoutError,
        ValueError,
        json.JSONDecodeError,
        urllib.error.URLError,
    ) as exception:
        return group(
            "unavailable",
            {},
            unavailable=["validator_unavailable"],
            evidence=[
                {"code": "MARKUP_VALIDATION_UNAVAILABLE", "reason": type(exception).__name__}
            ],
            limitations=["Validation failure does not imply valid markup."],
        )


def _cache_headers(headers: dict[str, str]) -> dict[str, Any]:
    cache_control = headers.get("cache-control", "")
    max_age = re.search(r"(?:^|,)\s*max-age=(\d+)", cache_control, re.I)
    s_maxage = re.search(r"(?:^|,)\s*s-maxage=(\d+)", cache_control, re.I)
    return {
        "cache_control": cache_control or None,
        "max_age": int(max_age.group(1)) if max_age else None,
        "s_maxage": int(s_maxage.group(1)) if s_maxage else None,
        "public": "public" in cache_control.lower(),
        "private": "private" in cache_control.lower(),
        "no_cache": "no-cache" in cache_control.lower(),
        "no_store": "no-store" in cache_control.lower(),
        "immutable": "immutable" in cache_control.lower(),
        "etag": headers.get("etag"),
        "last_modified": headers.get("last-modified"),
        "expires": headers.get("expires"),
        "content_encoding": headers.get("content-encoding"),
    }


def cache_diagnostics(playwright: dict[str, Any]) -> dict[str, Any]:
    html = _cache_headers(playwright.get("main_response_headers", {}))
    resources = []
    deductions: list[dict[str, Any]] = []
    if not html["cache_control"] and not html["etag"] and not html["last_modified"]:
        deductions.append(
            {
                "code": "HTML_CACHE_POLICY_RISK",
                "reason": "HTML has no explicit validator or cache policy",
                "points": 10,
            }
        )
    for item in playwright.get("resource_samples", []):
        cache = _cache_headers(item.get("headers", {}))
        hashed = bool(re.search(r"[._-][0-9a-f]{8,}[._-]", urlsplit(item["url"]).path, re.I))
        result = {
            "resource_type": item["resource_type"],
            "url_path": urlsplit(item["url"]).path[:300],
            "hashed_or_versioned": hashed,
            **cache,
        }
        resources.append(result)
        if not cache["cache_control"] and not cache["etag"] and not cache["last_modified"]:
            deductions.append(
                {
                    "code": "STATIC_ASSET_CACHE_MISSING",
                    "reason": f"{item['resource_type']} lacks cache metadata",
                    "points": 8,
                }
            )
        elif cache["max_age"] is not None and cache["max_age"] < 3600 and not cache["no_store"]:
            deductions.append(
                {
                    "code": "STATIC_ASSET_CACHE_TOO_SHORT",
                    "reason": f"{item['resource_type']} max-age is below one hour",
                    "points": 4,
                }
            )
    deductions = deductions[:10]
    sampled_count = len(resources)
    candidate_count = max(
        sampled_count, int(playwright.get("resource_sample_candidates") or sampled_count)
    )
    sample_limit = int(playwright.get("resource_sample_limit") or candidate_count or 0)
    if sampled_count == 0:
        completeness = "html_only"
        status = "partial"
        unavailable = ["static_asset_analysis"]
        evidence = [
            {
                "code": "STATIC_ASSET_ANALYSIS_UNAVAILABLE",
                "message": "Static asset analysis unavailable; the score is provisional.",
            }
        ]
    elif candidate_count > sampled_count:
        completeness = "partial_static_sample"
        status = "partial"
        unavailable = ["remaining_static_assets"]
        evidence = [
            {
                "code": "STATIC_ASSET_SAMPLE_BOUNDED",
                "sampled": sampled_count,
                "observed_candidates": candidate_count,
                "sample_limit": sample_limit,
            }
        ]
    else:
        completeness = "complete_observed_sample"
        status = "available"
        unavailable = []
        evidence = []
    inputs = {
        "html": html,
        "sampled_resources": sampled_count,
        "observed_static_resources": candidate_count,
    }
    confidence = min(100, 20 + len(resources) * 16)
    return group(
        status,
        {
            **inputs,
            "resources": resources,
            "cdn_indicators": playwright.get("cdn_indicators", []),
            "evidence_completeness": completeness,
            "score_qualification": (
                "provisional_html_only"
                if sampled_count == 0
                else "bounded_sample"
                if status == "partial"
                else "verified_observed_sample"
            ),
        },
        unavailable=unavailable,
        evidence=evidence,
        score=score_result(inputs, deductions, confidence),
        limitations=["Only a bounded first-party resource sample is evaluated."],
        evidence_completeness=completeness,
        why_it_matters="Cache evidence shows whether repeat visits can reuse HTML and static assets efficiently.",
    )


DATE_PATTERN = re.compile(
    r"\b(last updated|updated|effective date|effective from)\s*[:\-]?\s*([A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}|\d{1,2}[/-]\d{1,2}[/-]\d{4}|\d{4}-\d{2}-\d{2})",
    re.I,
)


def _parse_date(value: str) -> datetime | None:
    for pattern in (
        "%B %d, %Y",
        "%b %d, %Y",
        "%B %d %Y",
        "%b %d %Y",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(value, pattern).replace(tzinfo=UTC)
        except ValueError:
            pass
    return None


def policy_diagnostics(playwright: dict[str, Any], *, timeout: int) -> dict[str, Any]:
    links = playwright.get("policy_links", {})
    observations: dict[str, Any] = {
        "privacy_policy": links.get("privacy"),
        "terms_and_conditions": links.get("terms"),
        "cookie_policy": links.get("cookie"),
        "privacy_freshness": "unknown",
    }
    unavailable: list[str] = []
    evidence: list[dict[str, Any]] = []
    privacy_url = links.get("privacy")
    if privacy_url:
        try:
            safe_url = validate_public_url(privacy_url)
            if urlsplit(safe_url).hostname != urlsplit(playwright["final_url"]).hostname:
                raise UrlSafetyError("UNSAFE_POLICY_URL", "Cross-site policy URL rejected.")
            with urllib.request.urlopen(safe_url, timeout=timeout) as response:
                text = response.read(500_000).decode("utf-8", errors="replace")
            match = DATE_PATTERN.search(re.sub(r"<[^>]+>", " ", text))
            if match and (
                parsed := _parse_date(match.group(2).replace(",", ", ").replace("  ", " "))
            ):
                age = (datetime.now(UTC) - parsed).days
                observations.update(
                    {
                        "privacy_date_label": match.group(1),
                        "privacy_date": parsed.date().isoformat(),
                        "privacy_freshness": "current" if age <= 365 else "stale",
                    }
                )
                evidence.append({"code": "PRIVACY_POLICY_DATE", "text": match.group(0)[:200]})
                if age > 365:
                    evidence.append({"code": "PRIVACY_POLICY_STALE", "age_days": age})
            else:
                unavailable.append("privacy_policy_explicit_date")
                evidence.append({"code": "PRIVACY_POLICY_DATE_UNKNOWN"})
        except (OSError, TimeoutError, urllib.error.URLError, UrlSafetyError):
            unavailable.append("privacy_policy_page")
    else:
        unavailable.append("privacy_policy")
        evidence.append({"code": "PRIVACY_POLICY_MISSING"})
    return group(
        "partial" if unavailable else "available",
        observations,
        unavailable=unavailable,
        evidence=evidence,
        limitations=["Policy freshness is not proof of legal compliance."],
    )


def copyright_diagnostics(playwright: dict[str, Any]) -> dict[str, Any]:
    text = str(playwright.get("copyright_text") or "")[:300]
    years = [int(value) for value in re.findall(r"\b(?:19|20)\d{2}\b", text)]
    current = datetime.now(UTC).year
    result = (
        "unknown"
        if not years
        else "current_year_detected"
        if current in years
        else "possibly_outdated"
    )
    evidence = (
        [
            {
                "code": (
                    "COPYRIGHT_CURRENT_YEAR"
                    if current in years
                    else "COPYRIGHT_YEAR_POSSIBLY_OUTDATED"
                ),
                "detected_text": text,
                "detected_years": years,
            }
        ]
        if years
        else []
    )
    return group(
        "available" if years else "unavailable",
        {
            "detected_text": text or None,
            "single_year": years[0] if len(years) == 1 else None,
            "year_range": [min(years), max(years)] if len(years) > 1 else None,
            "current_year_present": current in years,
            "result": result,
            "confidence_percent": 90 if years else 0,
        },
        unavailable=[] if years else ["visible_copyright_year"],
        evidence=evidence,
        limitations=["Copyright detection does not prove legal ownership."],
        evidence_completeness="visible_text_match" if years else "no_reliable_match",
        why_it_matters="A current visible year can reassure visitors that site metadata is maintained.",
    )


def classify_csp(csp: str | None) -> dict[str, Any]:
    if not csp or not csp.strip():
        return {
            "quality": "absent",
            "reason": "No enforced Content-Security-Policy header was observed.",
            "directives": [],
            "strengths": [],
            "risks": ["policy_absent"],
        }
    directives: dict[str, list[str]] = {}
    for raw_directive in csp.split(";"):
        parts = raw_directive.strip().split()
        if parts:
            directives[parts[0].lower()] = [value.lower() for value in parts[1:]]
    names = set(directives)
    upgrade_only = names == {"upgrade-insecure-requests"}
    all_sources = [
        source
        for name, sources in directives.items()
        if name.endswith("-src") or name == "default-src"
        for source in sources
    ]
    wildcard = any(source == "*" or source.startswith("*") for source in all_sources)
    unsafe_inline = "'unsafe-inline'" in all_sources
    unsafe_eval = "'unsafe-eval'" in all_sources
    nonce_or_hash = any(
        source.startswith(("'nonce-", "'sha256-", "'sha384-", "'sha512-")) for source in all_sources
    )
    source_controls = names & {"default-src", "script-src", "style-src"}
    hardening = names & {"object-src", "base-uri", "frame-ancestors"}
    strengths = sorted(
        [
            *(["restrictive_source_controls"] if source_controls else []),
            *(["object_restriction"] if "object-src" in names else []),
            *(["base_uri_restriction"] if "base-uri" in names else []),
            *(["frame_ancestor_restriction"] if "frame-ancestors" in names else []),
            *(["nonce_or_hash_sources"] if nonce_or_hash else []),
            *(["insecure_request_upgrade"] if "upgrade-insecure-requests" in names else []),
        ]
    )
    risks = sorted(
        [
            *(["wildcard_source"] if wildcard else []),
            *(["unsafe_inline"] if unsafe_inline else []),
            *(["unsafe_eval"] if unsafe_eval else []),
            *(["missing_source_controls"] if not source_controls else []),
        ]
    )
    if upgrade_only:
        quality = "upgrade_only"
        reason = (
            "The policy only upgrades insecure requests and does not restrict script, style, "
            "object, frame, or other content sources."
        )
    elif wildcard or unsafe_eval or (unsafe_inline and not nonce_or_hash):
        quality = "weak"
        reason = (
            "The policy has source controls, but broad or unsafe source expressions weaken them."
        )
    elif (
        ("default-src" in names or {"script-src", "style-src"} <= names)
        and {"object-src", "base-uri", "frame-ancestors"} <= hardening
        and not risks
    ):
        quality = "strong"
        reason = "Restrictive source controls and key object, base-URI, and framing protections were observed."
    elif source_controls:
        quality = "moderate"
        reason = (
            "Useful source restrictions were observed, but key hardening directives are incomplete."
        )
    else:
        quality = "weak"
        reason = "The policy is present but does not define meaningful content source restrictions."
    return {
        "quality": quality,
        "reason": reason,
        "directives": sorted(names),
        "strengths": strengths,
        "risks": risks,
    }


def security_diagnostics(playwright: dict[str, Any]) -> dict[str, Any]:
    headers = {
        key.lower(): value for key, value in playwright.get("main_response_headers", {}).items()
    }
    csp = headers.get("content-security-policy")
    csp_classification = classify_csp(csp)
    mixed = playwright.get("mixed_content_count", 0)
    deductions = []
    if not csp:
        deductions.append(
            {"code": "CSP_MISSING", "reason": "Content-Security-Policy is absent", "points": 20}
        )
    elif csp_classification["quality"] in {"upgrade_only", "weak"}:
        deductions.append(
            {
                "code": "CSP_WEAK",
                "reason": csp_classification["reason"],
                "points": 10,
            }
        )
    if playwright.get("https_usage") and not headers.get("strict-transport-security"):
        deductions.append(
            {"code": "HSTS_MISSING", "reason": "HSTS is absent on HTTPS", "points": 15}
        )
    if not headers.get("x-frame-options") and "frame-ancestors" not in (csp or ""):
        deductions.append(
            {
                "code": "FRAME_PROTECTION_MISSING",
                "reason": "No verified frame protection",
                "points": 10,
            }
        )
    if headers.get("x-content-type-options", "").lower() != "nosniff":
        deductions.append(
            {
                "code": "MIME_SNIFFING_PROTECTION_MISSING",
                "reason": "nosniff is absent",
                "points": 10,
            }
        )
    if mixed:
        deductions.append(
            {
                "code": "MIXED_CONTENT_DETECTED",
                "reason": "HTTP subresources observed on HTTPS",
                "points": 20,
            }
        )
    if headers.get("server") or headers.get("x-powered-by"):
        deductions.append(
            {
                "code": "SERVER_INFORMATION_EXPOSED",
                "reason": "Server technology header exposed",
                "points": 5,
            }
        )
    observations = {
        "https_usage": playwright.get("https_usage"),
        "http_to_https_redirect": playwright.get("http_to_https_redirect"),
        "tls": playwright.get("tls_metadata"),
        "security_txt_present": playwright.get("security_txt_present"),
        "mixed_content_count": mixed,
        "headers": {
            name: headers.get(name)
            for name in (
                "content-security-policy",
                "content-security-policy-report-only",
                "strict-transport-security",
                "x-content-type-options",
                "referrer-policy",
                "permissions-policy",
                "x-frame-options",
                "cross-origin-opener-policy",
                "cross-origin-embedder-policy",
                "cross-origin-resource-policy",
                "server",
                "x-powered-by",
            )
        },
        "csp_quality": csp_classification["quality"],
        "csp_classification": csp_classification,
    }
    unavailable = []
    if playwright.get("https_usage") and not playwright.get("tls_metadata"):
        unavailable.append("tls_metadata")
    return group(
        "partial" if unavailable else "available",
        observations,
        unavailable=unavailable,
        score=score_result(
            observations,
            deductions,
            75 if unavailable else 90,
            formula_version=SECURITY_FORMULA_VERSION,
        ),
        limitations=[SECURITY_DISCLAIMER],
        why_it_matters="Response headers reduce common browser-side attack exposure when configured restrictively.",
    )


def collect_passive_security_metadata(
    playwright: dict[str, Any], timeout: int, *, deadline: float | None = None
) -> None:
    def bounded_timeout() -> float:
        if deadline is None:
            return timeout
        return max(0.0, min(float(timeout), deadline - time.monotonic()))

    final = urlsplit(playwright["final_url"])
    if final.scheme == "https" and final.hostname:
        try:
            request_timeout = bounded_timeout()
            if request_timeout <= 0:
                raise TimeoutError
            with socket.create_connection(
                (final.hostname, final.port or 443), timeout=request_timeout
            ) as raw:
                with ssl.create_default_context().wrap_socket(
                    raw, server_hostname=final.hostname
                ) as secure:
                    certificate = secure.getpeercert()
            playwright["tls_metadata"] = {
                "valid": True,
                "expires": certificate.get("notAfter"),
                "issuer": [list(item) for item in certificate.get("issuer", ())][:5],
            }
        except (OSError, ssl.SSLError, TimeoutError):
            playwright["tls_metadata"] = None
    try:
        request_timeout = bounded_timeout()
        if request_timeout <= 0:
            raise TimeoutError
        security_url = f"{final.scheme}://{final.netloc}/.well-known/security.txt"
        validate_public_url(security_url)
        with urllib.request.urlopen(security_url, timeout=request_timeout) as response:
            playwright["security_txt_present"] = response.status == 200
    except (OSError, TimeoutError, urllib.error.URLError, UrlSafetyError):
        playwright["security_txt_present"] = None
    if final.scheme == "https" and final.hostname:
        try:
            request_timeout = bounded_timeout()
            if request_timeout <= 0:
                raise TimeoutError
            http_url = urllib.parse.urlunsplit(("http", final.netloc, "/", "", ""))
            validate_public_url(http_url)
            with urllib.request.urlopen(http_url, timeout=request_timeout) as response:
                playwright["http_to_https_redirect"] = urlsplit(response.url).scheme == "https"
        except (OSError, TimeoutError, urllib.error.URLError, UrlSafetyError):
            playwright["http_to_https_redirect"] = None


def analytics_diagnostics(playwright: dict[str, Any]) -> dict[str, Any]:
    source = "\n".join(
        [str(playwright.get("script_evidence", "")), *playwright.get("network_urls", [])]
    )
    ga4 = sorted(set(re.findall(r"\bG-[A-Z0-9]{6,15}\b", source, re.I)))
    gtm = sorted(set(re.findall(r"\bGTM-[A-Z0-9]{4,12}\b", source, re.I)))
    providers = [
        name
        for name, pattern in {
            "Google Analytics": r"google-analytics|analytics\.google|gtag",
            "Google Tag Manager": r"googletagmanager",
            "Meta Pixel": r"connect\.facebook\.net|fbq\(",
        }.items()
        if re.search(pattern, source, re.I)
    ]
    analytics_requests = [
        url
        for url in playwright.get("network_urls", [])
        if re.search(r"analytics|collect|tagmanager", url, re.I)
    ]
    consent_observable = bool(playwright.get("consent_ui_detected"))
    observations = {
        "ga4_detected": bool(ga4),
        "gtm_detected": bool(gtm),
        "ga4_measurement_ids": ga4[:10],
        "gtm_container_ids": gtm[:10],
        "duplicate_ga4": len(ga4) > 1,
        "duplicate_gtm": len(gtm) > 1,
        "consent_mode_indicators": bool(
            re.search(r"consent.{0,30}(default|update)|analytics_storage", source, re.I | re.S)
        ),
        "analytics_request_count": len(analytics_requests),
        "trackers_before_consent": (
            [urlsplit(url).hostname for url in analytics_requests] if consent_observable else None
        ),
        "providers": providers,
    }
    evidence = []
    if len(ga4) > 1 or len(gtm) > 1:
        evidence.append({"code": "ANALYTICS_DUPLICATE_INSTALLATION"})
    if consent_observable and analytics_requests:
        evidence.append(
            {
                "code": "TRACKER_BEFORE_CONSENT",
                "provider_hosts": observations["trackers_before_consent"],
            }
        )
    return group(
        "available" if consent_observable else "partial",
        observations,
        evidence=evidence,
        unavailable=[] if consent_observable else ["tracker_before_consent_timing"],
        limitations=[
            "Public identifiers do not grant access to private analytics data or prove ownership."
        ],
    )


def _tap_target_evidence(viewports: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int, int]:
    evidence: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    informational = 0
    confirmed = 0
    for viewport in viewports:
        for target in viewport.get("tap_target_samples", []):
            if target.get("hidden"):
                continue
            desktop_only = (
                bool(target.get("desktop_only"))
                and "desktop" in str(viewport.get("name", "")).lower()
            )
            item = {
                "element_type": str(target.get("element_type") or "unknown")[:40],
                "accessible_label": str(target.get("accessible_label") or "")[:120] or None,
                "width_css_px": round(float(target.get("width") or 0), 1),
                "height_css_px": round(float(target.get("height") or 0), 1),
                "viewport": str(viewport.get("name") or "unknown")[:80],
                "spacing_exception": bool(target.get("spacing_exception")),
                "desktop_only": desktop_only,
            }
            item["classification"] = (
                "informational_small_target"
                if item["spacing_exception"] or desktop_only
                else "confirmed_usability_failure"
            )
            key = (
                item["element_type"],
                item["accessible_label"],
                item["width_css_px"],
                item["height_css_px"],
                item["viewport"],
            )
            if key in seen:
                continue
            seen.add(key)
            if item["spacing_exception"] or desktop_only:
                informational += 1
            else:
                confirmed += 1
            if len(evidence) < TAP_TARGET_EVIDENCE_LIMIT:
                evidence.append(item)
    return evidence, informational, confirmed


def responsive_diagnostics(playwright: dict[str, Any]) -> dict[str, Any]:
    viewports = playwright.get("responsive_results", [])
    tap_evidence, informational_targets, confirmed_targets = _tap_target_evidence(viewports)
    deductions = []
    for item in viewports:
        if item.get("status") == "failed":
            deductions.append(
                {
                    "code": "RESPONSIVE_VIEWPORT_FAILED",
                    "reason": f"{item['name']} failed",
                    "points": 20,
                }
            )
        elif item.get("horizontal_overflow"):
            deductions.append(
                {
                    "code": "MOBILE_HORIZONTAL_OVERFLOW"
                    if "mobile" in item["name"]
                    else "RESPONSIVE_CRITICAL_ELEMENT_OVERFLOW",
                    "reason": f"Horizontal overflow at {item['name']}",
                    "points": 10,
                }
            )
    if not playwright.get("viewport_meta"):
        deductions.append(
            {"code": "VIEWPORT_META_MISSING", "reason": "Viewport meta tag is absent", "points": 15}
        )
    successful = sum(item.get("status") == "passed" for item in viewports)
    inputs = {
        "tested_viewports": len(viewports),
        "successful_viewports": successful,
        "viewport_meta": playwright.get("viewport_meta"),
        "viewports": viewports,
        "tap_target_threshold_css_px": {
            "minimum_width": TAP_TARGET_MINIMUM_CSS_PX,
            "minimum_height": TAP_TARGET_MINIMUM_CSS_PX,
        },
        "spacing_exception_considered": True,
        "informational_small_targets": informational_targets,
        "confirmed_tap_target_failures": confirmed_targets,
        "tap_target_scoring_behavior": (
            "Observed small targets do not reduce responsive formula 1.0.0; only failed "
            "viewports, horizontal overflow, and missing viewport metadata are deducted."
        ),
    }
    unavailable = [item["name"] for item in viewports if item.get("status") == "failed"]
    if not viewports:
        unavailable.append("tap_target_measurements")
    return group(
        "available" if viewports and successful == len(viewports) else "partial",
        inputs,
        unavailable=unavailable,
        evidence=tap_evidence,
        score=score_result(inputs, deductions, round(successful / max(1, len(viewports)) * 100)),
        limitations=[
            "Results apply only to the tested Chromium viewports, not all devices.",
            "A small target is informational when its 24 CSS-pixel spacing exclusion area does not overlap another target.",
        ],
        evidence_completeness="tested_viewports" if viewports else "unavailable",
        why_it_matters="Adequate target size or spacing helps touch and motor-impaired users activate controls reliably.",
    )


def browser_compatibility(playwright: dict[str, Any]) -> dict[str, Any]:
    warnings = any(
        item.get("horizontal_overflow") for item in playwright.get("responsive_results", [])
    ) or bool(playwright.get("page_javascript_errors"))
    chromium = "passed_with_warnings" if warnings else "passed"
    return group(
        "available",
        {
            "matrix": {
                "chromium": {"tested": True, "result": chromium},
                "firefox": {"tested": False, "result": "not_tested"},
                "webkit": {"tested": False, "result": "not_tested"},
            }
        },
        limitations=[
            "Chromium testing does not establish Chrome, Edge, Firefox, Safari, or universal browser support."
        ],
    )


def build_diagnostics(
    playwright: dict[str, Any], settings: Any, *, deadline: float | None = None
) -> dict[str, dict[str, Any]]:
    def bounded_timeout(configured: int) -> int:
        if deadline is None:
            return configured
        return max(0, min(configured, int(deadline - time.monotonic())))

    html = str(playwright.pop("_html", ""))
    collect_passive_security_metadata(
        playwright, settings.policy_page_timeout_seconds, deadline=deadline
    )
    w3c_timeout = bounded_timeout(settings.w3c_timeout_seconds)
    policy_timeout = bounded_timeout(settings.policy_page_timeout_seconds)
    return {
        "standards_diagnostics": collect_w3c(
            html,
            enabled=settings.w3c_validation_enabled and w3c_timeout > 0,
            endpoint=str(settings.w3c_validation_endpoint),
            timeout=max(1, w3c_timeout),
            evidence_limit=settings.diagnostic_evidence_limit,
        ),
        "cache_diagnostics": cache_diagnostics(playwright),
        "policy_diagnostics": {
            **(
                policy_diagnostics(playwright, timeout=max(1, policy_timeout))
                if policy_timeout > 0
                else group("unavailable", {}, unavailable=["diagnostic_deadline"])
            ),
            "copyright": copyright_diagnostics(playwright),
        },
        "security_diagnostics": security_diagnostics(playwright),
        "analytics_diagnostics": analytics_diagnostics(playwright),
        "responsive_diagnostics": responsive_diagnostics(playwright),
        "browser_compatibility": browser_compatibility(playwright),
    }
