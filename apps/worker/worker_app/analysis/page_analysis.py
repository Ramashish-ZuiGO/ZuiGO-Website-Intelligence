import logging
import re
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urljoin, urlsplit

from worker_app.analysis.url_safety import UrlSafetyError, validate_public_url

logger = logging.getLogger(__name__)

PAGE_ANALYSIS_REASON_CODES = {
    "unsupported_content_type",
    "blocked_by_robots",
    "outside_allowed_origin",
    "duplicate_canonical",
    "page_limit_reached",
    "timeout",
    "navigation_failure",
    "lighthouse_failure",
    "unsafe_url",
    "redirect_outside_origin",
    "http_error",
    "connection_error",
    "skip_no_analysis_needed",
}

MAX_REDIRECTS = 5
MAX_RESPONSE_BYTES = 2_000_000
REQUEST_TIMEOUT = 15


_OPENER = urllib.request.build_opener()
# Remove the default redirect handler so we get raw 3xx responses
_OPENER.handlers[:] = [
    h for h in _OPENER.handlers if not isinstance(h, urllib.request.HTTPRedirectHandler)
]


def _make_request(url: str) -> urllib.request.Request:
    return urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (compatible; ZuiGO-PageAnalyzer/1.0; +https://zuigo.ai/bot)"
            ),
            "Accept": "text/html,application/xhtml+xml,*/*",
        },
    )


def _safe_headers(headers: dict[str, str]) -> dict[str, str]:
    return {key.lower(): value for key, value in headers.items()}


def _detect_content_type(headers: dict[str, str]) -> str | None:
    ct = headers.get("content-type", "")
    return ct.split(";")[0].strip() if ct else None


def _detect_language(html: str, headers: dict[str, str]) -> str | None:
    lang_attr = re.search(r'<html[^>]*\blang=["\']([^"\']+)["\']', html, re.I)
    if lang_attr:
        return lang_attr.group(1)
    return headers.get("content-language")


def _extract_title(html: str) -> str | None:
    match = re.search(r"<title[^>]*>([^<]+)</title>", html, re.I | re.S)
    return match.group(1).strip()[:500] if match else None


def _extract_meta_description(html: str) -> str | None:
    match = re.search(
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)["\']',
        html,
        re.I,
    )
    if not match:
        match = re.search(
            r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+name=["\']description["\']',
            html,
            re.I,
        )
    return match.group(1).strip()[:500] if match else None


def _extract_heading_structure(html: str) -> list[dict[str, Any]]:
    headings: list[dict[str, Any]] = []
    for level in range(1, 7):
        pattern = rf"<h{level}[^>]*>([^<]+)</h{level}>"
        for match in re.finditer(pattern, html, re.I | re.S):
            headings.append(
                {
                    "level": level,
                    "text": match.group(1).strip()[:200],
                }
            )
    return headings[:50]


def _extract_links(html: str, base_url: str) -> tuple[int, int]:
    internal = 0
    external = 0
    base_host = urlsplit(base_url).hostname or ""
    for match in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\']', html, re.I):
        href = match.group(1)
        if href.startswith("#") or href.startswith("javascript:"):
            continue
        try:
            parsed = urlsplit(href)
            host = parsed.hostname or base_host
            if host == base_host or not parsed.netloc:
                internal += 1
            else:
                external += 1
        except ValueError:
            continue
    return internal, external


def _extract_images(html: str) -> tuple[int, int]:
    total = 0
    missing_alt = 0
    for match in re.finditer(r"<img[^>]+>", html, re.I):
        total += 1
        alt_match = re.search(r'alt=["\']([^"\']*)["\']', match.group(0), re.I)
        if not alt_match or not alt_match.group(1).strip():
            missing_alt += 1
    return total, missing_alt


def _extract_forms(html: str) -> int:
    return len(re.findall(r"<form[^>]*>", html, re.I))


def _check_structured_data(html: str) -> bool:
    return bool(
        re.search(
            r'<script[^>]+type=["\']application/ld\+json["\']',
            html,
            re.I,
        )
    )


def _check_robots_directives(html: str, headers: dict[str, str]) -> dict[str, Any]:
    directives: dict[str, Any] = {
        "x_robots_tag": headers.get("x-robots-tag"),
        "meta_robots": None,
    }
    match = re.search(
        r'<meta[^>]+name=["\']robots["\'][^>]+content=["\']([^"\']+)["\']',
        html,
        re.I,
    )
    if not match:
        match = re.search(
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']robots["\']',
            html,
            re.I,
        )
    if match:
        directives["meta_robots"] = match.group(1)
    return directives


def _basic_seo_signals(
    title: str | None,
    meta_description: str | None,
    canonical: str | None,
    headings: list[dict[str, Any]],
    h1_count: int,
) -> dict[str, Any]:
    return {
        "has_title": title is not None,
        "has_meta_description": meta_description is not None,
        "has_canonical": canonical is not None,
        "h1_count": h1_count,
        "multiple_h1": h1_count > 1,
        "no_h1": h1_count == 0,
    }


def _basic_accessibility_signals(
    images_missing_alt: int,
    html_lang: str | None,
    headings: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "images_missing_alt": images_missing_alt,
        "has_html_lang": html_lang is not None,
        "heading_count": len(headings),
        "heading_gaps": sorted(set(range(1, 7)) - {h["level"] for h in headings}),
    }


def _security_observations(headers: dict[str, str], final_url: str) -> dict[str, Any]:
    return {
        "https": urlsplit(final_url).scheme == "https",
        "strict_transport_security": headers.get("strict-transport-security"),
        "content_security_policy": headers.get("content-security-policy"),
        "x_frame_options": headers.get("x-frame-options"),
        "x_content_type_options": headers.get("x-content-type-options"),
        "referrer_policy": headers.get("referrer-policy"),
        "permissions_policy": headers.get("permissions-policy"),
        "server": headers.get("server"),
        "x_powered_by": headers.get("x-powered-by"),
    }


def analyze_page_level_1(
    page_url: str,
    max_redirects: int = MAX_REDIRECTS,
    timeout: int = REQUEST_TIMEOUT,
    max_bytes: int = MAX_RESPONSE_BYTES,
) -> dict[str, Any]:
    started_at = time.monotonic()
    try:
        safe_url = validate_public_url(page_url)
    except UrlSafetyError as exception:
        elapsed = int((time.monotonic() - started_at) * 1000)
        return {
            "status": "failed",
            "requested_url": page_url,
            "final_url": None,
            "canonical_url": None,
            "http_status_code": None,
            "redirect_chain": [],
            "page_title": None,
            "meta_description": None,
            "heading_structure": [],
            "robots_directives": {},
            "content_type": None,
            "language": None,
            "structured_data_present": None,
            "internal_link_count": None,
            "external_link_count": None,
            "image_count": None,
            "images_missing_alt": None,
            "form_count": None,
            "basic_accessibility_signals": {},
            "basic_seo_signals": {},
            "security_observations": {},
            "evidence": {},
            "elapsed_ms": elapsed,
            "failure_reason_code": "unsafe_url",
            "failure_reason_text": exception.safe_message,
        }
    original_host = urlsplit(safe_url).hostname

    redirect_chain: list[dict[str, Any]] = []
    current_url = safe_url
    status_code: int | None = None
    final_url: str | None = None
    response_headers: dict[str, str] = {}
    html = ""
    error_code: str | None = None
    error_text: str | None = None

    for _hop in range(max_redirects + 1):
        try:
            validate_public_url(current_url)
            req = _make_request(current_url)
            resp = _OPENER.open(req, timeout=timeout)

            status_code = resp.status
            raw_headers = dict(resp.headers)
            response_headers = _safe_headers(raw_headers)
            final_url = resp.url

            ct = _detect_content_type(response_headers)
            if ct and "text/html" not in ct and "application/xhtml" not in ct:
                error_code = "unsupported_content_type"
                error_text = f"Content-Type is not HTML: {ct}"
                html = ""
                break

            raw = resp.read(max_bytes)
            html = raw.decode("utf-8", errors="replace")
            break

        except urllib.error.HTTPError as exception:
            status_code = exception.code
            raw_headers = dict(exception.headers)
            response_headers = _safe_headers(raw_headers)
            final_url = exception.url or current_url

            if 300 <= exception.code < 400:
                location = response_headers.get("location", "")
                if not location:
                    error_code = "connection_error"
                    error_text = "Redirect response missing Location header"
                    break

                next_url = (
                    location
                    if location.startswith(("http://", "https://"))
                    else urljoin(current_url, location)
                )

                try:
                    validate_public_url(next_url)
                except UrlSafetyError as exc:
                    error_code = exc.code if exc.code == "PRIVATE_NETWORK_TARGET" else "unsafe_url"
                    error_text = exc.safe_message
                    break

                redirect_chain.append(
                    {
                        "url": current_url,
                        "status": status_code,
                        "final": False,
                    }
                )

                redirect_host = urlsplit(next_url).hostname
                if redirect_host != original_host:
                    error_code = "redirect_outside_origin"
                    error_text = f"Redirect to outside origin: {next_url}"
                    break

                current_url = next_url
                continue

            error_code = "http_error"
            error_text = f"HTTP error {exception.code}: {exception.reason}"
            break
        except urllib.error.URLError as exception:
            error_code = "connection_error"
            error_text = f"Connection error: {exception.reason}"
            break
        except UrlSafetyError as exception:
            error_code = "unsafe_url"
            error_text = exception.safe_message
            break
        except (OSError, TimeoutError) as exception:
            error_code = "timeout"
            error_text = f"Request timed out: {exception}"
            break

    if redirect_chain and redirect_chain[-1].get("status", 0) < 400:
        redirect_chain[-1]["final"] = True

    if not html and error_code is None:
        error_code = "connection_error"
        error_text = "No HTML content retrieved after redirects"

    canonical_url = None
    if html:
        match = re.search(
            r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)["\']',
            html,
            re.I,
        )
        if match:
            canonical_url = match.group(1)

    h1_count = len(re.findall(r"<h1[^>]*>", html, re.I))
    title = _extract_title(html) if html else None
    meta_description = _extract_meta_description(html) if html else None
    headings = _extract_heading_structure(html) if html else []
    internal_links, external_links = _extract_links(html, final_url or safe_url) if html else (0, 0)
    image_count, missing_alt = _extract_images(html) if html else (0, 0)
    form_count = _extract_forms(html) if html else 0
    structured_data = _check_structured_data(html) if html else False
    language = _detect_language(html, response_headers) if html else None
    robots_dirs = _check_robots_directives(html, response_headers) if html else {}
    content_type = _detect_content_type(response_headers)

    elapsed = int((time.monotonic() - started_at) * 1000)

    status = "completed" if not error_code else "failed"

    return {
        "status": status,
        "requested_url": safe_url,
        "final_url": final_url or safe_url,
        "canonical_url": canonical_url,
        "http_status_code": status_code,
        "redirect_chain": redirect_chain,
        "page_title": title,
        "meta_description": meta_description,
        "heading_structure": headings,
        "robots_directives": robots_dirs,
        "content_type": content_type,
        "language": language,
        "structured_data_present": structured_data,
        "internal_link_count": internal_links,
        "external_link_count": external_links,
        "image_count": image_count,
        "images_missing_alt": missing_alt,
        "form_count": form_count,
        "basic_accessibility_signals": _basic_accessibility_signals(
            missing_alt, language, headings
        ),
        "basic_seo_signals": _basic_seo_signals(
            title, meta_description, canonical_url, headings, h1_count
        ),
        "security_observations": _security_observations(response_headers, final_url or safe_url),
        "evidence": {
            "headers_sampled": {
                k: response_headers.get(k)
                for k in (
                    "content-type",
                    "content-length",
                    "cache-control",
                    "content-language",
                    "last-modified",
                    "etag",
                )
            },
            "html_length_bytes": len(html),
        },
        "elapsed_ms": elapsed,
        "failure_reason_code": error_code,
        "failure_reason_text": error_text,
    }
