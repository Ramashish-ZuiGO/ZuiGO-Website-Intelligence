# ruff: noqa: E501

import html
import io
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

from lxml import etree
from lxml import html as lxml_html

from worker_app.analysis.url_safety import UrlSafetyError, validate_public_url

FORMULA_VERSION = "1.0.0"
# AT-2: 1.2.0 added the same HSTS max-age threshold check as
# page_security_risk_score's PAGE_SECURITY_RISK_FORMULA_VERSION 1.1.0 --
# these two deduction lists previously disagreed (this one treated any
# HSTS presence as a full pass; the other now correctly requires >= 6
# months) despite living in the same function and describing the same page.
SECURITY_FORMULA_VERSION = "1.2.0"
HTML_STANDARDS_FORMULA_VERSION = "1.0.0"
# AT-2: 1.1.0 added HSTS max-age threshold checking (previously presence-only)
# and a standard A+-F letter grade, informed by Mozilla/MDN's published HTTP
# Observatory grade scale (github.com/mdn/mdn-http-observatory) -- not a
# byte-exact port of their internal per-header point deltas, which are
# defined per-test-file rather than in one published table, but the same
# real 100-point-base/5-point-band grading categories rather than an
# invented scale.
PAGE_SECURITY_RISK_FORMULA_VERSION = "1.1.0"

# Mozilla/MDN HTTP Observatory's real recommended minimum: 6 months.
HSTS_MIN_MAX_AGE_SECONDS = 15_552_000

_SECURITY_GRADE_BANDS: list[tuple[int, str]] = [
    (100, "A+"),
    (90, "A"),
    (85, "A-"),
    (80, "B+"),
    (70, "B"),
    (65, "B-"),
    (60, "C+"),
    (50, "C"),
    (45, "C-"),
    (40, "D+"),
    (30, "D"),
    (25, "D-"),
]


def _security_grade(score: int) -> str:
    normalized = max(0, min(100, score))
    normalized -= normalized % 5
    for threshold, grade in _SECURITY_GRADE_BANDS:
        if normalized >= threshold:
            return grade
    return "F"


def _hsts_max_age_seconds(hsts_value: str) -> int | None:
    match = re.search(r"max-age\s*=\s*(\d+)", hsts_value, re.I)
    return int(match.group(1)) if match else None


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
    r"\b(last updated|updated|updated on|effective date|effective from|last modified|revised)\s*[:\-]?\s*([A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}|\d{1,2}[/-]\d{1,2}[/-]\d{4}|\d{4}-\d{2}-\d{2})",
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


def _extract_policy_title(html_text: str) -> str | None:
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.I | re.S)
    if title_match:
        return re.sub(r"\s+", " ", title_match.group(1)).strip()[:300] or None
    h1_match = re.search(r"<h1[^>]*>(.*?)</h1>", html_text, re.I | re.S)
    if h1_match:
        return re.sub(r"<[^>]+>", "", h1_match.group(1)).strip()[:300] or None
    return None


def policy_diagnostics(playwright: dict[str, Any], *, timeout: int) -> dict[str, Any]:
    links = playwright.get("policy_links", {})
    checked_at = datetime.now(UTC).isoformat()
    privacy_url = links.get("privacy")
    privacy_policy: dict[str, Any] = {
        "found": False,
        "url": None,
        "title": None,
        "explicit_update_date": None,
        "date_label": None,
        "evidence_text": None,
        "age_days": None,
        "freshness_status": "unavailable",
        "checked_at": checked_at,
    }
    observations: dict[str, Any] = {
        "privacy_policy": links.get("privacy"),
        "terms_and_conditions": links.get("terms"),
        "cookie_policy": links.get("cookie"),
        "privacy_freshness": "unknown",
    }
    unavailable: list[str] = []
    evidence: list[dict[str, Any]] = []
    if privacy_url:
        privacy_path = urlsplit(str(privacy_url)).path.casefold()
        policy_filename = privacy_path.rsplit("/", 1)[-1]
        if ("terms" in privacy_path and "privacy" not in privacy_path) or policy_filename.endswith(
            ".pdf"
        ):
            observations.update(
                {
                    "privacy_policy": None,
                    "potential_policy_document": privacy_url,
                    "policy_verification_status": (
                        "Potential policy document — manual verification required"
                    ),
                }
            )
            unavailable.append("verified_privacy_policy")
            evidence.append(
                {
                    "code": "POTENTIAL_POLICY_DOCUMENT",
                    "url": str(privacy_url)[:2048],
                    "manual_verification_required": True,
                }
            )
            return group(
                "partial",
                {**observations, "privacy_policy_detail": privacy_policy},
                unavailable=unavailable,
                evidence=evidence,
            )
        try:
            safe_url = validate_public_url(privacy_url)
            if urlsplit(safe_url).hostname != urlsplit(playwright["final_url"]).hostname:
                raise UrlSafetyError("UNSAFE_POLICY_URL", "Cross-site policy URL rejected.")
            with urllib.request.urlopen(safe_url, timeout=timeout) as response:
                raw_text = response.read(500_000).decode("utf-8", errors="replace")
            privacy_policy["found"] = True
            privacy_policy["url"] = str(safe_url)[:2048]
            privacy_policy["title"] = _extract_policy_title(raw_text)
            plain = re.sub(r"<[^>]+>", " ", raw_text)
            match = DATE_PATTERN.search(plain)
            if match and (
                parsed := _parse_date(match.group(2).replace(",", ", ").replace("  ", " "))
            ):
                age = (datetime.now(UTC) - parsed).days
                privacy_policy["explicit_update_date"] = parsed.date().isoformat()
                privacy_policy["date_label"] = match.group(1)
                privacy_policy["evidence_text"] = match.group(0)[:200]
                privacy_policy["age_days"] = age
                privacy_policy["freshness_status"] = (
                    "current" if age <= 365 else "older_than_one_year"
                )
                observations.update(
                    {
                        "privacy_date_label": match.group(1),
                        "privacy_date": parsed.date().isoformat(),
                        "privacy_freshness": privacy_policy["freshness_status"],
                    }
                )
                evidence.append({"code": "PRIVACY_POLICY_DATE", "text": match.group(0)[:200]})
                if age > 365:
                    evidence.append({"code": "PRIVACY_POLICY_STALE", "age_days": age})
            else:
                privacy_policy["freshness_status"] = "date_not_published"
                observations["privacy_freshness"] = "date_not_published"
                unavailable.append("privacy_policy_explicit_date")
                evidence.append({"code": "PRIVACY_POLICY_DATE_UNKNOWN"})
        except (OSError, TimeoutError, urllib.error.URLError, UrlSafetyError):
            unavailable.append("privacy_policy_page")
    else:
        unavailable.append("privacy_policy")
        evidence.append({"code": "PRIVACY_POLICY_MISSING"})
    observations["privacy_policy_detail"] = privacy_policy
    return group(
        "partial" if unavailable else "available",
        observations,
        unavailable=unavailable,
        evidence=evidence,
        limitations=["Policy freshness is not proof of legal compliance."],
    )


def copyright_diagnostics(playwright: dict[str, Any]) -> dict[str, Any]:
    text = str(playwright.get("copyright_text") or "")[:300]
    evidence_url = str(playwright.get("final_url") or "")[:2048] or None
    years = [int(value) for value in re.findall(r"\b(?:19|20)\d{2}\b", text)]
    current = datetime.now(UTC).year
    result = (
        "unknown"
        if not years
        else "current_year_detected"
        if current in years
        else "possibly_outdated"
    )
    freshness_status = (
        "unavailable" if not years else "current" if current in years else "possibly_outdated"
    )
    start_year = min(years) if years else None
    end_year = max(years) if years else None
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
            "detected": bool(years),
            "raw_text": text or None,
            "start_year": start_year,
            "end_year": end_year,
            "current_year": current,
            "freshness_status": freshness_status,
            "evidence_url": evidence_url,
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


SECURITY_HEADER_SPECS: list[dict[str, str]] = [
    {
        "header": "strict-transport-security",
        "explanation": "Instructs browsers to only connect over HTTPS, preventing protocol downgrade attacks.",
        "recommendation": "Add Strict-Transport-Security with max-age of at least 31536000 (one year).",
    },
    {
        "header": "content-security-policy",
        "explanation": "Controls which resources the browser is allowed to load, mitigating XSS and injection attacks.",
        "recommendation": "Define a Content-Security-Policy with restrictive source controls (default-src, script-src, style-src).",
    },
    {
        "header": "x-content-type-options",
        "explanation": "Prevents browsers from MIME-sniffing a response away from the declared content type.",
        "recommendation": "Set X-Content-Type-Options: nosniff.",
    },
    {
        "header": "referrer-policy",
        "explanation": "Controls how much referrer information is shared when navigating away from the page.",
        "recommendation": "Set Referrer-Policy to strict-origin-when-cross-origin or stricter.",
    },
    {
        "header": "permissions-policy",
        "explanation": "Restricts which browser features (camera, microphone, geolocation) the page may use.",
        "recommendation": "Define a Permissions-Policy limiting access to only required browser features.",
    },
    {
        "header": "x-frame-options",
        "explanation": "Prevents the page from being embedded in frames, mitigating clickjacking attacks.",
        "recommendation": "Set X-Frame-Options: DENY or SAMEORIGIN, or use CSP frame-ancestors.",
    },
    {
        "header": "cross-origin-opener-policy",
        "explanation": "Isolates the browsing context from cross-origin documents that open or are opened by this page.",
        "recommendation": "Set Cross-Origin-Opener-Policy: same-origin when cross-origin window access is not needed.",
    },
    {
        "header": "cross-origin-resource-policy",
        "explanation": "Restricts which origins can load this resource, protecting against cross-origin data leaks.",
        "recommendation": "Set Cross-Origin-Resource-Policy: same-origin or same-site where appropriate.",
    },
]


def _build_security_header_matrix(
    headers: dict[str, str | None],
    csp: str | None,
    final_url: str,
) -> list[dict[str, Any]]:
    matrix: list[dict[str, Any]] = []
    for spec in SECURITY_HEADER_SPECS:
        name = spec["header"]
        value = headers.get(name)
        if name == "x-frame-options" and not value and csp and "frame-ancestors" in csp:
            status = "not_applicable"
            recommendation = None
        elif value is None:
            status = "missing"
            recommendation = spec["recommendation"]
        else:
            status = "present"
            recommendation = None
        if name == "x-content-type-options" and value and value.lower() != "nosniff":
            status = "malformed"
            recommendation = spec["recommendation"]
        matrix.append(
            {
                "header": name,
                "status": status,
                "observed_value": value,
                "affected_page_count": 1,
                "example_urls": [final_url[:2048]],
                "explanation": spec["explanation"],
                "recommendation": recommendation,
            }
        )
    return matrix


AGGREGATION_HEADER_KEYS = [spec["header"] for spec in SECURITY_HEADER_SPECS]

_HEADER_TO_FIELD = {
    "strict-transport-security": "strict_transport_security",
    "content-security-policy": "content_security_policy",
    "x-frame-options": "x_frame_options",
    "x-content-type-options": "x_content_type_options",
    "referrer-policy": "referrer_policy",
    "permissions-policy": "permissions_policy",
    "cross-origin-opener-policy": "cross_origin_opener_policy",
    "cross-origin-resource-policy": "cross_origin_resource_policy",
}


def _classify_header_value(header: str, value: str | None, csp: str | None) -> str:
    if header == "x-frame-options" and not value and csp and "frame-ancestors" in csp:
        return "not_applicable"
    if value is None:
        return "missing"
    if header == "x-content-type-options" and value.lower() != "nosniff":
        return "malformed"
    return "present"


def aggregate_security_header_matrix(
    page_evidences: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    matrix: list[dict[str, Any]] = []
    for spec in SECURITY_HEADER_SPECS:
        header_name = spec["header"]
        field_name = _HEADER_TO_FIELD.get(header_name, header_name)
        pages_checked = 0
        pages_present = 0
        pages_missing = 0
        pages_malformed = 0
        pages_not_applicable = 0
        observed_values: list[str] = []
        example_present: list[str] = []
        example_missing: list[str] = []
        example_malformed: list[str] = []
        for page in page_evidences:
            sec = page.get("security_observations")
            if not sec:
                continue
            page_url = str(page.get("url") or page.get("final_url") or "")[:2048]
            value = sec.get(field_name)
            csp = sec.get("content_security_policy")
            status = _classify_header_value(header_name, value, csp)
            pages_checked += 1
            if status == "present":
                pages_present += 1
                if value and value not in observed_values:
                    observed_values.append(value)
                if len(example_present) < 3:
                    example_present.append(page_url)
            elif status == "missing":
                pages_missing += 1
                if len(example_missing) < 3:
                    example_missing.append(page_url)
            elif status == "malformed":
                pages_malformed += 1
                if value and value not in observed_values:
                    observed_values.append(value)
                if len(example_malformed) < 3:
                    example_malformed.append(page_url)
            elif status == "not_applicable":
                pages_not_applicable += 1
        if pages_checked == 0:
            consistency = "insufficient_evidence"
        elif pages_malformed > 0:
            consistency = "malformed"
        elif (
            pages_present == pages_checked
            or (pages_present + pages_not_applicable) == pages_checked
        ):
            consistency = "consistent_present"
        elif pages_missing == pages_checked:
            consistency = "consistently_missing"
        else:
            consistency = "inconsistent"
        coverage = round(pages_present / max(1, pages_checked) * 100, 1) if pages_checked else 0.0
        recommendation = (
            spec["recommendation"] if consistency not in ("consistent_present",) else None
        )
        matrix.append(
            {
                "header": header_name,
                "pages_checked": pages_checked,
                "pages_present": pages_present,
                "pages_missing": pages_missing,
                "pages_malformed": pages_malformed,
                "pages_not_applicable": pages_not_applicable,
                "coverage_percent": coverage,
                "consistency_status": consistency,
                "observed_values": observed_values[:10],
                "example_present_urls": example_present,
                "example_missing_urls": example_missing,
                "example_malformed_urls": example_malformed,
                "explanation": spec["explanation"],
                "recommendation": recommendation,
            }
        )
    return matrix


def aggregate_responsiveness(
    page_evidences: list[dict[str, Any]],
) -> dict[str, Any]:
    pages_tested = 0
    responsive_pages = 0
    partially_responsive_pages = 0
    not_responsive_pages = 0
    inconclusive_pages = 0
    per_page: list[dict[str, Any]] = []
    mobile_pass = 0
    mobile_total = 0
    tablet_pass = 0
    tablet_total = 0
    desktop_pass = 0
    desktop_total = 0
    for page in page_evidences:
        viewports = page.get("responsive_results")
        page_url = str(page.get("url") or page.get("final_url") or "")[:2048]
        if not viewports:
            per_page.append({"url": page_url, "status": "unavailable"})
            continue
        pages_tested += 1
        total_vp = len(viewports)
        passed_vp = sum(1 for vp in viewports if vp.get("status") == "passed")
        failed_vp = sum(1 for vp in viewports if vp.get("status") == "failed")
        overflow_vp = sum(1 for vp in viewports if vp.get("horizontal_overflow"))
        for vp in viewports:
            name = str(vp.get("name", "")).lower()
            vp_passed = vp.get("status") == "passed" and not vp.get("horizontal_overflow")
            if "mobile" in name:
                mobile_total += 1
                if vp_passed:
                    mobile_pass += 1
            elif "tablet" in name:
                tablet_total += 1
                if vp_passed:
                    tablet_pass += 1
            elif "desktop" in name or "laptop" in name:
                desktop_total += 1
                if vp_passed:
                    desktop_pass += 1
        if passed_vp == total_vp and overflow_vp == 0:
            page_status = "responsive"
            responsive_pages += 1
        elif failed_vp == total_vp:
            page_status = "not_responsive"
            not_responsive_pages += 1
        elif passed_vp == 0 and overflow_vp == 0:
            page_status = "inconclusive"
            inconclusive_pages += 1
        elif passed_vp > 0:
            page_status = "partially_responsive"
            partially_responsive_pages += 1
        else:
            page_status = "not_responsive"
            not_responsive_pages += 1
        per_page.append(
            {
                "url": page_url,
                "status": page_status,
                "viewports_passed": passed_vp,
                "viewports_total": total_vp,
            }
        )
    return {
        "pages_tested": pages_tested,
        "responsive_pages": responsive_pages,
        "partially_responsive_pages": partially_responsive_pages,
        "not_responsive_pages": not_responsive_pages,
        "inconclusive_pages": inconclusive_pages,
        "mobile_pass_percent": round(mobile_pass / max(1, mobile_total) * 100, 1)
        if mobile_total
        else None,
        "tablet_pass_percent": round(tablet_pass / max(1, tablet_total) * 100, 1)
        if tablet_total
        else None,
        "desktop_pass_percent": round(desktop_pass / max(1, desktop_total) * 100, 1)
        if desktop_total
        else None,
        "site_status": (
            "responsive"
            if pages_tested > 0 and responsive_pages == pages_tested
            else "partially_responsive"
            if responsive_pages > 0
            else "not_responsive"
            if not_responsive_pages > 0 and pages_tested > 0
            else "inconclusive"
            if pages_tested > 0
            else "unavailable"
        ),
        "per_page": per_page[:50],
    }


def security_diagnostics(playwright: dict[str, Any]) -> dict[str, Any]:
    headers = {
        key.lower(): value for key, value in playwright.get("main_response_headers", {}).items()
    }
    csp = headers.get("content-security-policy")
    csp_classification = classify_csp(csp)
    mixed = playwright.get("mixed_content_count", 0)
    final_url = str(playwright.get("final_url") or "")
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
    hsts_header = headers.get("strict-transport-security")
    if playwright.get("https_usage") and not hsts_header:
        deductions.append(
            {"code": "HSTS_MISSING", "reason": "HSTS is absent on HTTPS", "points": 15}
        )
    elif playwright.get("https_usage") and hsts_header:
        hsts_max_age = _hsts_max_age_seconds(hsts_header)
        if hsts_max_age is None or hsts_max_age < HSTS_MIN_MAX_AGE_SECONDS:
            deductions.append(
                {
                    "code": "HSTS_MAX_AGE_TOO_SHORT",
                    "reason": (
                        f"HSTS max-age is {hsts_max_age if hsts_max_age is not None else 'unparseable'}"
                        f" seconds, under the recommended {HSTS_MIN_MAX_AGE_SECONDS} (6 months)"
                    ),
                    "points": 7,
                }
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
    header_matrix = _build_security_header_matrix(headers, csp, final_url)
    risk_obs = {
        "https": playwright.get("https_usage"),
        "strict_transport_security": headers.get("strict-transport-security"),
        "content_security_policy": csp,
        "x_frame_options": headers.get("x-frame-options"),
        "x_content_type_options": headers.get("x-content-type-options"),
        "referrer_policy": headers.get("referrer-policy"),
        "permissions_policy": headers.get("permissions-policy"),
        "cross_origin_opener_policy": headers.get("cross-origin-opener-policy"),
        "cross_origin_resource_policy": headers.get("cross-origin-resource-policy"),
        "server": headers.get("server"),
        "x_powered_by": headers.get("x-powered-by"),
    }
    risk_score = page_security_risk_score(
        risk_obs,
        csp_quality=csp_classification["quality"],
        http_to_https_redirect=playwright.get("http_to_https_redirect"),
        mixed_content_count=mixed,
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
        "security_header_matrix": header_matrix,
        "page_security_risk": risk_score,
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
    final_url = str(playwright.get("final_url") or "")
    ga4 = sorted(set(re.findall(r"\bG-[A-Z0-9]{6,15}\b", source, re.I)))
    gtm = sorted(set(re.findall(r"\bGTM-[A-Z0-9]{4,12}\b", source, re.I)))
    gads = sorted(set(re.findall(r"\bAW-[A-Z0-9]{6,15}\b", source, re.I)))
    provider_map: dict[str, str] = {
        "Google Analytics 4": r"google-analytics|analytics\.google|gtag",
        "Google Tag Manager": r"googletagmanager",
        "Google Ads": r"googleads|adservices\.google",
        "Meta Pixel": r"connect\.facebook\.net|fbq\(",
    }
    providers = [name for name, pattern in provider_map.items() if re.search(pattern, source, re.I)]
    technologies: list[str] = []
    if ga4:
        technologies.append("GA4")
    if gtm:
        technologies.append("GTM")
    if re.search(r"\bgtag\s*\(", source, re.I):
        technologies.append("gtag.js")
    if re.search(r"\bdataLayer\b", source, re.I):
        technologies.append("dataLayer")
    if gads:
        technologies.append("Google Ads tag")
    public_identifiers = [*ga4[:10], *gtm[:10], *gads[:5]]
    analytics_requests = [
        url
        for url in playwright.get("network_urls", [])
        if re.search(r"analytics|collect|tagmanager", url, re.I)
    ]
    evidence_sources: list[str] = []
    if re.search(
        r"gtag|dataLayer|googletagmanager|google-analytics",
        str(playwright.get("script_evidence", "")),
        re.I,
    ):
        evidence_sources.append("inline_script")
    if any(
        re.search(r"analytics|tagmanager", url, re.I) for url in playwright.get("network_urls", [])
    ):
        evidence_sources.append("network_request")
    consent_observable = bool(playwright.get("consent_ui_detected"))
    detected = bool(ga4 or gtm or providers)
    confidence = 90 if detected and evidence_sources else 60 if detected else 0
    observations = {
        "detected": detected,
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
        "technologies": technologies,
        "public_identifiers": public_identifiers,
        "affected_page_count": 1,
        "example_urls": [final_url[:2048]] if final_url else [],
        "evidence_sources": evidence_sources,
        "confidence": confidence,
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
    viewports = playwright.get("responsive_results", [])
    if not viewports and not playwright.get("main_response_headers"):
        return group(
            "unavailable",
            {"matrix": {}},
            unavailable=["browser_testing"],
            limitations=["No browser engine data available; no compatibility finding produced."],
        )
    warnings = any(item.get("horizontal_overflow") for item in viewports) or bool(
        playwright.get("page_javascript_errors")
    )
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


DEPRECATED_HTML_ELEMENTS = frozenset(
    {
        "acronym",
        "applet",
        "basefont",
        "bgsound",
        "big",
        "blink",
        "center",
        "command",
        "content",
        "dir",
        "element",
        "font",
        "frame",
        "frameset",
        "hgroup",
        "image",
        "isindex",
        "keygen",
        "listing",
        "marquee",
        "menuitem",
        "multicol",
        "nextid",
        "nobr",
        "noembed",
        "noframes",
        "plaintext",
        "shadow",
        "spacer",
        "strike",
        "tt",
        "xmp",
    }
)

_VALID_VIEWPORT_KEYS = frozenset(
    {
        "width",
        "height",
        "initial-scale",
        "minimum-scale",
        "maximum-scale",
        "user-scalable",
        "interactive-widget",
        "viewport-fit",
    }
)


def _collect_parser_errors(html_content: str) -> list[dict[str, Any]]:
    parser = etree.HTMLParser(recover=True)
    etree.parse(io.StringIO(html_content), parser)
    issues: list[dict[str, Any]] = []
    for error in parser.error_log:
        if "Tag" in error.message and "invalid" in error.message.lower():
            continue
        issues.append(
            {
                "code": "HTML_PARSE_ERROR",
                "severity": "error",
                "message": str(error.message)[:300],
                "line": error.line,
                "column": error.column,
            }
        )
    return issues[:20]


def _check_duplicate_ids(tree: lxml_html.HtmlElement) -> list[dict[str, Any]]:
    seen: dict[str, int] = {}
    for el in tree.iter():
        el_id = el.get("id")
        if el_id:
            seen[el_id] = seen.get(el_id, 0) + 1
    issues: list[dict[str, Any]] = []
    for id_val, count in seen.items():
        if count > 1:
            issues.append(
                {
                    "code": "DUPLICATE_ID",
                    "severity": "error",
                    "message": f'Duplicate id="{html.escape(id_val[:80])}" appears {count} times',
                    "affected_id": id_val[:80],
                    "count": count,
                }
            )
    return issues[:30]


def _check_document_language(tree: lxml_html.HtmlElement) -> list[dict[str, Any]]:
    html_el = tree.find(".//html") if tree.tag != "html" else tree
    if html_el is None:
        html_el = tree
    lang = html_el.get("lang") or html_el.get("{http://www.w3.org/XML/1998/namespace}lang")
    if not lang:
        return [
            {
                "code": "MISSING_LANG",
                "severity": "warning",
                "message": "Document is missing a lang attribute on the <html> element",
            }
        ]
    lang = lang.strip()
    if not re.match(r"^[a-zA-Z]{2,8}(-[a-zA-Z0-9]{1,8})*$", lang):
        return [
            {
                "code": "INVALID_LANG",
                "severity": "warning",
                "message": f'Invalid lang attribute value: "{html.escape(lang[:40])}"',
                "observed_value": lang[:40],
            }
        ]
    return []


def _check_title(tree: lxml_html.HtmlElement) -> list[dict[str, Any]]:
    titles = tree.findall(".//head/title")
    if not titles:
        titles = tree.findall(".//title")
    if not titles:
        return [
            {
                "code": "MISSING_TITLE",
                "severity": "error",
                "message": "Document is missing a <title> element",
            }
        ]
    issues: list[dict[str, Any]] = []
    if len(titles) > 1:
        issues.append(
            {
                "code": "DUPLICATE_TITLE",
                "severity": "warning",
                "message": f"Document has {len(titles)} <title> elements; expected 1",
            }
        )
    title_text = (titles[0].text or "").strip()
    if not title_text:
        issues.append(
            {
                "code": "EMPTY_TITLE",
                "severity": "error",
                "message": "The <title> element is empty",
            }
        )
    return issues


def _check_heading_structure(tree: lxml_html.HtmlElement) -> list[dict[str, Any]]:
    headings: list[int] = []
    for el in tree.iter("h1", "h2", "h3", "h4", "h5", "h6"):
        headings.append(int(el.tag[1]))
    issues: list[dict[str, Any]] = []
    if headings and headings[0] != 1:
        issues.append(
            {
                "code": "HEADING_NOT_START_H1",
                "severity": "warning",
                "message": f"First heading is <h{headings[0]}>, expected <h1>",
            }
        )
    for i in range(1, len(headings)):
        if headings[i] > headings[i - 1] + 1:
            issues.append(
                {
                    "code": "HEADING_SKIP_LEVEL",
                    "severity": "warning",
                    "message": f"Heading level skips from <h{headings[i - 1]}> to <h{headings[i]}>",
                    "from_level": headings[i - 1],
                    "to_level": headings[i],
                }
            )
    return issues[:10]


def _check_deprecated_elements(tree: lxml_html.HtmlElement) -> list[dict[str, Any]]:
    found: dict[str, int] = {}
    for el in tree.iter():
        tag = el.tag if isinstance(el.tag, str) else ""
        if tag in DEPRECATED_HTML_ELEMENTS:
            found[tag] = found.get(tag, 0) + 1
    issues: list[dict[str, Any]] = []
    for tag, count in sorted(found.items()):
        issues.append(
            {
                "code": "DEPRECATED_ELEMENT",
                "severity": "warning",
                "message": f"Deprecated element <{tag}> used {count} time(s)",
                "element": tag,
                "count": count,
            }
        )
    return issues[:20]


def _check_meta_declarations(tree: lxml_html.HtmlElement) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    meta_names: dict[str, int] = {}
    charset_count = 0
    for meta in tree.iter("meta"):
        name = (meta.get("name") or "").lower().strip()
        if name:
            meta_names[name] = meta_names.get(name, 0) + 1
        if meta.get("charset") is not None:
            charset_count += 1
        if meta.get("http-equiv") and not meta.get("content"):
            issues.append(
                {
                    "code": "META_HTTPEQUIV_NO_CONTENT",
                    "severity": "warning",
                    "message": f'<meta http-equiv="{html.escape(str(meta.get("http-equiv"))[:40])}"> missing content attribute',
                }
            )
    for name, count in meta_names.items():
        if count > 1 and name in ("description", "viewport", "robots", "author", "keywords"):
            issues.append(
                {
                    "code": "DUPLICATE_META",
                    "severity": "warning",
                    "message": f'Duplicate <meta name="{html.escape(name)}"> ({count} occurrences)',
                    "meta_name": name,
                    "count": count,
                }
            )
    if charset_count > 1:
        issues.append(
            {
                "code": "DUPLICATE_CHARSET",
                "severity": "warning",
                "message": f"Multiple charset declarations ({charset_count})",
            }
        )
    return issues[:15]


def _check_canonical(tree: lxml_html.HtmlElement) -> list[dict[str, Any]]:
    canonicals = [
        link for link in tree.iter("link") if (link.get("rel") or "").lower() == "canonical"
    ]
    if len(canonicals) > 1:
        return [
            {
                "code": "DUPLICATE_CANONICAL",
                "severity": "error",
                "message": f"Multiple canonical declarations ({len(canonicals)}); search engines may ignore all",
            }
        ]
    if len(canonicals) == 1:
        href = canonicals[0].get("href", "").strip()
        if not href:
            return [
                {
                    "code": "EMPTY_CANONICAL",
                    "severity": "error",
                    "message": "Canonical link has an empty href",
                }
            ]
    return []


def _check_viewport_meta(tree: lxml_html.HtmlElement) -> list[dict[str, Any]]:
    viewports = [
        meta for meta in tree.iter("meta") if (meta.get("name") or "").lower() == "viewport"
    ]
    if not viewports:
        return [
            {
                "code": "MISSING_VIEWPORT",
                "severity": "warning",
                "message": "No viewport meta tag found",
            }
        ]
    issues: list[dict[str, Any]] = []
    content = viewports[0].get("content", "")
    if not content.strip():
        issues.append(
            {
                "code": "EMPTY_VIEWPORT",
                "severity": "error",
                "message": "Viewport meta tag has empty content",
            }
        )
        return issues
    parts = re.split(r"[,;]\s*", content)
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            issues.append(
                {
                    "code": "MALFORMED_VIEWPORT_DIRECTIVE",
                    "severity": "warning",
                    "message": f'Viewport directive missing value: "{html.escape(part[:40])}"',
                }
            )
            continue
        key = part.split("=", 1)[0].strip().lower()
        if key not in _VALID_VIEWPORT_KEYS:
            issues.append(
                {
                    "code": "UNKNOWN_VIEWPORT_KEY",
                    "severity": "warning",
                    "message": f'Unknown viewport key: "{html.escape(key[:40])}"',
                }
            )
    return issues[:10]


def _check_malformed_links(tree: lxml_html.HtmlElement) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    empty_href = 0
    for a_el in tree.iter("a"):
        href = a_el.get("href")
        if href is not None and not href.strip():
            empty_href += 1
    if empty_href:
        issues.append(
            {
                "code": "EMPTY_HREF",
                "severity": "warning",
                "message": f"{empty_href} anchor(s) with empty href attribute",
                "count": empty_href,
            }
        )
    empty_src = 0
    for tag in ("img", "script", "iframe", "source", "video", "audio"):
        for el in tree.iter(tag):
            src = el.get("src")
            if src is not None and not src.strip():
                empty_src += 1
    if empty_src:
        issues.append(
            {
                "code": "EMPTY_SRC",
                "severity": "warning",
                "message": f"{empty_src} element(s) with empty src attribute",
                "count": empty_src,
            }
        )
    return issues


def html_standards_validation(
    html_content: str,
    url: str,
    *,
    evidence_limit: int = 30,
) -> dict[str, Any]:
    if not html_content or not html_content.strip():
        return group(
            "unavailable",
            {
                "validation_status": "unavailable",
                "errors_count": 0,
                "warnings_count": 0,
                "standards_score": None,
                "score_version": HTML_STANDARDS_FORMULA_VERSION,
                "issues": [],
                "validator_name": "ZuiGO HTML Standards",
                "validator_version": HTML_STANDARDS_FORMULA_VERSION,
            },
            unavailable=["html_content"],
            limitations=["No HTML content available for validation."],
        )
    try:
        tree = lxml_html.fromstring(html_content)
    except Exception:
        return group(
            "partial",
            {
                "validation_status": "inconclusive",
                "errors_count": 0,
                "warnings_count": 0,
                "standards_score": None,
                "score_version": HTML_STANDARDS_FORMULA_VERSION,
                "issues": [],
                "validator_name": "ZuiGO HTML Standards",
                "validator_version": HTML_STANDARDS_FORMULA_VERSION,
            },
            unavailable=["html_parsing_failed"],
            limitations=["HTML content could not be parsed."],
        )

    all_issues: list[dict[str, Any]] = []
    all_issues.extend(_collect_parser_errors(html_content))
    all_issues.extend(_check_duplicate_ids(tree))
    all_issues.extend(_check_document_language(tree))
    all_issues.extend(_check_title(tree))
    all_issues.extend(_check_heading_structure(tree))
    all_issues.extend(_check_deprecated_elements(tree))
    all_issues.extend(_check_meta_declarations(tree))
    all_issues.extend(_check_canonical(tree))
    all_issues.extend(_check_viewport_meta(tree))
    all_issues.extend(_check_malformed_links(tree))

    errors = [i for i in all_issues if i["severity"] == "error"]
    warnings = [i for i in all_issues if i["severity"] == "warning"]
    errors_count = len(errors)
    warnings_count = len(warnings)

    deductions: list[dict[str, Any]] = []
    for issue in errors:
        code = issue["code"]
        pts = 8
        if code == "DUPLICATE_ID":
            pts = 5 * issue.get("count", 1)
        elif code in ("MISSING_TITLE", "EMPTY_TITLE"):
            pts = 10
        elif code == "DUPLICATE_CANONICAL":
            pts = 10
        elif code == "HTML_PARSE_ERROR":
            pts = 3
        deductions.append({"code": code, "reason": issue["message"][:200], "points": pts})
    for issue in warnings:
        code = issue["code"]
        pts = 3
        if code == "DEPRECATED_ELEMENT":
            pts = 2 * issue.get("count", 1)
        elif code in ("MISSING_LANG", "MISSING_VIEWPORT"):
            pts = 5
        elif code == "HEADING_SKIP_LEVEL":
            pts = 2
        elif code == "DUPLICATE_META":
            pts = 3
        deductions.append({"code": code, "reason": issue["message"][:200], "points": pts})

    raw_score = max(0, 100 - sum(d["points"] for d in deductions))
    validation_status = "valid" if not all_issues else "issues_found"

    observations = {
        "validation_status": validation_status,
        "errors_count": errors_count,
        "warnings_count": warnings_count,
        "standards_score": raw_score,
        "score_version": HTML_STANDARDS_FORMULA_VERSION,
        "issues": all_issues[:evidence_limit],
        "validator_name": "ZuiGO HTML Standards",
        "validator_version": HTML_STANDARDS_FORMULA_VERSION,
    }

    return group(
        "available",
        observations,
        evidence=[
            {
                "code": i["code"],
                "severity": i["severity"],
                "message": i["message"],
            }
            for i in all_issues[:evidence_limit]
        ],
        score=score_result(
            {"errors_count": errors_count, "warnings_count": warnings_count},
            deductions,
            90 if html_content else 0,
            formula_version=HTML_STANDARDS_FORMULA_VERSION,
        ),
        limitations=[
            "This is a ZuiGO HTML Standards Score, not an official W3C validation result.",
            "Checks are structural and deterministic using the lxml parser; they do not cover all HTML specification rules.",
            "For comprehensive validation, use the official Nu HTML Checker (validator.w3.org/nu/).",
        ],
        why_it_matters="Well-formed HTML reduces cross-browser rendering inconsistencies and improves accessibility tool compatibility.",
    )


def aggregate_html_standards(
    page_results: list[dict[str, Any]],
) -> dict[str, Any]:
    pages_checked = 0
    pages_valid = 0
    pages_with_errors = 0
    pages_inconclusive = 0
    total_errors = 0
    total_warnings = 0
    scores: list[int] = []
    issue_counts: dict[str, int] = {}
    for page in page_results:
        status = page.get("validation_status")
        if status == "unavailable":
            continue
        pages_checked += 1
        if status == "valid":
            pages_valid += 1
        elif status == "issues_found":
            pages_with_errors += 1
        elif status == "inconclusive":
            pages_inconclusive += 1
        total_errors += page.get("errors_count", 0)
        total_warnings += page.get("warnings_count", 0)
        score = page.get("standards_score")
        if score is not None:
            scores.append(score)
        for issue in page.get("issues", []):
            code = issue.get("code", "UNKNOWN")
            issue_counts[code] = issue_counts.get(code, 0) + 1
    common_groups = sorted(issue_counts.items(), key=lambda x: x[1], reverse=True)[:15]
    avg_score = round(sum(scores) / max(1, len(scores)), 1) if scores else None
    return {
        "pages_checked": pages_checked,
        "pages_valid": pages_valid,
        "pages_with_errors": pages_with_errors,
        "pages_inconclusive": pages_inconclusive,
        "total_errors": total_errors,
        "total_warnings": total_warnings,
        "common_issue_groups": [
            {"code": code, "occurrences": count} for code, count in common_groups
        ],
        "average_standards_score": avg_score,
    }


# ---------------------------------------------------------------------------
# Page Security & Risk Score — Formula v1.0.0
# ---------------------------------------------------------------------------

_SECURITY_RISK_CHECKS: list[dict[str, Any]] = [
    {"code": "HTTPS_ABSENT", "category": "transport", "points": 25, "requires": "https"},
    {
        "code": "HSTS_MISSING",
        "category": "transport",
        "points": 10,
        "requires": "strict_transport_security",
    },
    {
        "code": "HTTP_NO_REDIRECT",
        "category": "transport",
        "points": 5,
        "requires": "http_to_https_redirect",
    },
    {
        "code": "CSP_MISSING",
        "category": "headers",
        "points": 15,
        "requires": "content_security_policy",
    },
    {
        "code": "FRAME_PROTECTION_MISSING",
        "category": "headers",
        "points": 8,
        "requires": "x_frame_options",
    },
    {
        "code": "XCTO_MISSING",
        "category": "headers",
        "points": 8,
        "requires": "x_content_type_options",
    },
    {
        "code": "REFERRER_POLICY_MISSING",
        "category": "headers",
        "points": 5,
        "requires": "referrer_policy",
    },
    {
        "code": "PERMISSIONS_POLICY_MISSING",
        "category": "headers",
        "points": 5,
        "requires": "permissions_policy",
    },
    {
        "code": "COOP_MISSING",
        "category": "headers",
        "points": 4,
        "requires": "cross_origin_opener_policy",
    },
    {
        "code": "CORP_MISSING",
        "category": "headers",
        "points": 4,
        "requires": "cross_origin_resource_policy",
    },
    {
        "code": "MIXED_CONTENT",
        "category": "resource",
        "points": 15,
        "requires": "mixed_content_count",
    },
    {"code": "SERVER_EXPOSED", "category": "exposure", "points": 5, "requires": "server"},
]


def _risk_band(score: int) -> str:
    if score >= 90:
        return "strong"
    if score >= 75:
        return "good"
    if score >= 50:
        return "needs_attention"
    if score >= 25:
        return "weak"
    return "high_observable_risk"


def _has_key(d: dict[str, Any], key: str) -> bool:
    return key in d


def page_security_risk_score(
    security_obs: dict[str, Any],
    *,
    csp_quality: str | None = None,
    http_to_https_redirect: bool | None = None,
    mixed_content_count: int = 0,
) -> dict[str, Any]:
    deductions: list[dict[str, Any]] = []
    checks_available = 0
    checks_total = len(_SECURITY_RISK_CHECKS)
    findings_used: list[str] = []

    https = security_obs.get("https")
    has_https = _has_key(security_obs, "https")
    if has_https:
        checks_available += 1
        if not https:
            deductions.append(
                {"code": "HTTPS_ABSENT", "reason": "Page not served over HTTPS", "points": 25}
            )
            findings_used.append("HTTPS_ABSENT")
    hsts = security_obs.get("strict_transport_security")
    if _has_key(security_obs, "strict_transport_security") or has_https:
        checks_available += 1
        if not hsts and https:
            deductions.append(
                {"code": "HSTS_MISSING", "reason": "HSTS header absent on HTTPS page", "points": 10}
            )
            findings_used.append("HSTS_MISSING")
        elif hsts and https:
            max_age = _hsts_max_age_seconds(hsts)
            if max_age is None or max_age < HSTS_MIN_MAX_AGE_SECONDS:
                deductions.append(
                    {
                        "code": "HSTS_MAX_AGE_TOO_SHORT",
                        "reason": (
                            f"HSTS max-age is {max_age if max_age is not None else 'unparseable'}"
                            f" seconds, under the recommended {HSTS_MIN_MAX_AGE_SECONDS}"
                            " (6 months)"
                        ),
                        "points": 5,
                    }
                )
                findings_used.append("HSTS_MAX_AGE_TOO_SHORT")
    if http_to_https_redirect is not None:
        checks_available += 1
        if not http_to_https_redirect and https:
            deductions.append(
                {
                    "code": "HTTP_NO_REDIRECT",
                    "reason": "HTTP does not redirect to HTTPS",
                    "points": 5,
                }
            )
            findings_used.append("HTTP_NO_REDIRECT")
    csp = security_obs.get("content_security_policy")
    if _has_key(security_obs, "content_security_policy") or has_https:
        checks_available += 1
        if not csp:
            deductions.append(
                {
                    "code": "CSP_MISSING",
                    "reason": "Content-Security-Policy header absent",
                    "points": 15,
                }
            )
            findings_used.append("CSP_MISSING")
        elif csp_quality in ("weak", "upgrade_only"):
            deductions.append(
                {"code": "CSP_WEAK", "reason": f"CSP quality: {csp_quality}", "points": 8}
            )
            findings_used.append("CSP_WEAK")
    xfo = security_obs.get("x_frame_options")
    csp_fa = "frame-ancestors" in (csp or "")
    if _has_key(security_obs, "x_frame_options") or _has_key(
        security_obs, "content_security_policy"
    ):
        checks_available += 1
        if not xfo and not csp_fa:
            deductions.append(
                {
                    "code": "FRAME_PROTECTION_MISSING",
                    "reason": "No frame protection (X-Frame-Options or CSP frame-ancestors)",
                    "points": 8,
                }
            )
            findings_used.append("FRAME_PROTECTION_MISSING")
    xcto = security_obs.get("x_content_type_options")
    if _has_key(security_obs, "x_content_type_options") or has_https:
        checks_available += 1
        if not xcto or (isinstance(xcto, str) and xcto.lower() != "nosniff"):
            deductions.append(
                {
                    "code": "XCTO_MISSING",
                    "reason": "X-Content-Type-Options nosniff absent or malformed",
                    "points": 8,
                }
            )
            findings_used.append("XCTO_MISSING")
    rp = security_obs.get("referrer_policy")
    if _has_key(security_obs, "referrer_policy") or has_https:
        checks_available += 1
        if not rp:
            deductions.append(
                {
                    "code": "REFERRER_POLICY_MISSING",
                    "reason": "Referrer-Policy header absent",
                    "points": 5,
                }
            )
            findings_used.append("REFERRER_POLICY_MISSING")
    pp = security_obs.get("permissions_policy")
    if _has_key(security_obs, "permissions_policy") or has_https:
        checks_available += 1
        if not pp:
            deductions.append(
                {
                    "code": "PERMISSIONS_POLICY_MISSING",
                    "reason": "Permissions-Policy header absent",
                    "points": 5,
                }
            )
            findings_used.append("PERMISSIONS_POLICY_MISSING")
    coop = security_obs.get("cross_origin_opener_policy")
    if _has_key(security_obs, "cross_origin_opener_policy"):
        checks_available += 1
        if not coop:
            deductions.append(
                {"code": "COOP_MISSING", "reason": "Cross-Origin-Opener-Policy absent", "points": 4}
            )
            findings_used.append("COOP_MISSING")
    corp = security_obs.get("cross_origin_resource_policy")
    if _has_key(security_obs, "cross_origin_resource_policy"):
        checks_available += 1
        if not corp:
            deductions.append(
                {
                    "code": "CORP_MISSING",
                    "reason": "Cross-Origin-Resource-Policy absent",
                    "points": 4,
                }
            )
            findings_used.append("CORP_MISSING")
    checks_available += 1
    if mixed_content_count > 0:
        deductions.append(
            {
                "code": "MIXED_CONTENT",
                "reason": f"{mixed_content_count} mixed-content resource(s) detected",
                "points": 15,
            }
        )
        findings_used.append("MIXED_CONTENT")
    server = security_obs.get("server")
    x_powered = security_obs.get("x_powered_by")
    if server is not None or x_powered is not None:
        checks_available += 1
        if server or x_powered:
            deductions.append(
                {
                    "code": "SERVER_EXPOSED",
                    "reason": "Server technology header exposes implementation details",
                    "points": 5,
                }
            )
            findings_used.append("SERVER_EXPOSED")

    raw_score = max(0, 100 - sum(d["points"] for d in deductions))
    evidence_coverage = round(checks_available / max(1, checks_total) * 100, 1)
    confidence = (
        "high" if evidence_coverage >= 80 else "moderate" if evidence_coverage >= 50 else "low"
    )

    return {
        "score": raw_score,
        "score_version": PAGE_SECURITY_RISK_FORMULA_VERSION,
        "grade": _security_grade(raw_score),
        "risk_band": _risk_band(raw_score),
        "evidence_coverage": evidence_coverage,
        "confidence": confidence,
        "findings_used": findings_used,
        "deductions": deductions,
        "checks_available": checks_available,
        "checks_total": checks_total,
        "limitations": [
            "This is a ZuiGO Security & Risk Score based on observable security posture, not a penetration-test result.",
            "This score does not prove the absence of vulnerabilities.",
            "Missing evidence does not equal passing evidence; evidence coverage and confidence are reported separately.",
        ],
    }


def aggregate_page_security_scores(
    page_scores: list[dict[str, Any]],
) -> dict[str, Any]:
    scores: list[int] = []
    coverage_values: list[float] = []
    all_findings: dict[str, int] = {}
    lowest: list[dict[str, Any]] = []
    needs_attention: list[dict[str, Any]] = []
    band_dist: dict[str, int] = {}
    for page in page_scores:
        score = page.get("score")
        url = str(page.get("url", ""))[:2048]
        if score is None:
            continue
        scores.append(score)
        coverage_values.append(page.get("evidence_coverage", 0))
        band = page.get("risk_band", "unknown")
        band_dist[band] = band_dist.get(band, 0) + 1
        for finding in page.get("findings_used", []):
            all_findings[finding] = all_findings.get(finding, 0) + 1
        entry = {"url": url, "score": score, "risk_band": band}
        if score < 75:
            needs_attention.append(entry)
        lowest.append(entry)

    lowest.sort(key=lambda x: x["score"])
    needs_attention.sort(key=lambda x: x["score"])
    sorted_scores = sorted(scores)
    median = (
        (
            sorted_scores[len(sorted_scores) // 2]
            if len(sorted_scores) % 2 == 1
            else round(
                (
                    sorted_scores[len(sorted_scores) // 2 - 1]
                    + sorted_scores[len(sorted_scores) // 2]
                )
                / 2,
                1,
            )
        )
        if sorted_scores
        else None
    )
    top_weaknesses = sorted(all_findings.items(), key=lambda x: x[1], reverse=True)[:10]

    return {
        "pages_scored": len(scores),
        "average_score": round(sum(scores) / max(1, len(scores)), 1) if scores else None,
        "median_score": median,
        "lowest_scoring_pages": lowest[:10],
        "pages_needing_attention": needs_attention[:20],
        "score_distribution": band_dist,
        "common_weaknesses": [
            {"code": code, "affected_pages": count} for code, count in top_weaknesses
        ],
        "average_evidence_coverage": round(sum(coverage_values) / max(1, len(coverage_values)), 1)
        if coverage_values
        else None,
    }


def build_diagnostics(
    playwright: dict[str, Any], settings: Any, *, deadline: float | None = None
) -> dict[str, dict[str, Any]]:
    def bounded_timeout(configured: int) -> int:
        if deadline is None:
            return configured
        return max(0, min(configured, int(deadline - time.monotonic())))

    html_content = str(playwright.pop("_html", ""))
    collect_passive_security_metadata(
        playwright, settings.policy_page_timeout_seconds, deadline=deadline
    )
    w3c_timeout = bounded_timeout(settings.w3c_timeout_seconds)
    policy_timeout = bounded_timeout(settings.policy_page_timeout_seconds)
    final_url = str(playwright.get("final_url") or "")
    return {
        "standards_diagnostics": collect_w3c(
            html_content,
            enabled=settings.w3c_validation_enabled and w3c_timeout > 0,
            endpoint=str(settings.w3c_validation_endpoint),
            timeout=max(1, w3c_timeout),
            evidence_limit=settings.diagnostic_evidence_limit,
        ),
        "html_standards_diagnostics": html_standards_validation(
            html_content,
            final_url,
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
