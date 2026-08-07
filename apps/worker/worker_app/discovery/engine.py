import gzip
import io
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
import xml.etree.ElementTree as ET
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any

from app.services.resource_classification import (
    ResourceClassification,
    classify_resource,
)

from worker_app.analysis.url_safety import UrlSafetyError, validate_public_url

TRACKING_PARAMETERS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "utm_name",
    "utm_reader",
    "utm_referrer",
    "gclid",
    "gclsrc",
    "dclid",
    "wbraid",
    "gbraid",
    "fbclid",
    "msclkid",
    "yclid",
    "mc_eid",
    "mc_cid",
    "igshid",
    "vero_id",
    "vero_conv",
    "_hsenc",
    "_hsmi",
    "mkt_tok",
    "oly_anon_id",
    "oly_enc_id",
    "hsa_cam",
    "hsa_grp",
    "hsa_ad",
    "s_kwcid",
    "ref_src",
    "spm",
    "sessionid",
    "sid",
    "phpsessid",
    "jsessionid",
    "cfid",
    "cftoken",
}
DESTRUCTIVE_PATH_PARTS = {
    "logout",
    "signout",
    "delete",
    "remove",
    "unsubscribe",
    "reset",
    "checkout",
    "payment",
    "cart",
    "purchase",
    "order",
    "confirm",
    "approve",
    "reject",
    "download",
    "export",
    "admin",
    "wp-admin",
}
CLASSIFICATION_VERSION = "1.0.0"


class DiscoveryError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message
        self.attempts = 1


@dataclass(frozen=True)
class DiscoveryConfig:
    max_discovered_urls: int = 50_000
    max_html_pages: int = 10_000
    # ``max_crawl_depth`` is an emergency safety bound against pathologically deep
    # or self-generating URL spaces, NOT the normal stop condition. Ordinary finite
    # sites terminate by frontier exhaustion long before this is reached.
    max_crawl_depth: int = 1_000
    max_links_per_page: int = 500
    # Per-path cap on distinct query-string variants, bounding faceted navigation,
    # calendars, and session/tracking parameter explosion.
    max_query_variants_per_path: int = 200
    max_sitemap_files: int = 50
    max_sitemap_depth: int = 5
    max_redirects: int = 5
    request_timeout_seconds: int = 15
    deadline_seconds: int = 1800
    max_response_bytes: int = 2_000_000
    include_verified_subdomains: bool = False
    max_fetch_attempts: int = 3
    retry_backoff_seconds: float = 0.25


@dataclass
class FetchResponse:
    url: str
    status: int
    headers: dict[str, str]
    body: bytes
    redirects: list[str]
    size_limited: bool = False
    attempts: int = 1


Fetch = Callable[[str, DiscoveryConfig], FetchResponse]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        return None


def normalize_url(url: str, base_url: str | None = None) -> str:
    raw = urllib.parse.urljoin(base_url, url) if base_url else url
    try:
        parsed = urllib.parse.urlsplit(raw)
        port = parsed.port
    except ValueError as exception:
        raise DiscoveryError(
            "UNSAFE_URL_REJECTED", "The discovered URL is malformed."
        ) from exception
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.hostname:
        raise DiscoveryError(
            "UNSAFE_URL_REJECTED", "Only discovered HTTP and HTTPS URLs are eligible."
        )
    if parsed.username or parsed.password:
        raise DiscoveryError("UNSAFE_URL_REJECTED", "Credential-bearing URLs are excluded.")
    hostname = parsed.hostname.rstrip(".").lower()
    if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        port = None
    netloc = f"[{hostname}]" if ":" in hostname else hostname
    if port is not None:
        netloc = f"{netloc}:{port}"
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query = [
        (key, value)
        for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in TRACKING_PARAMETERS
    ]
    return urllib.parse.urlunsplit(
        (scheme, netloc, path, urllib.parse.urlencode(query, doseq=True), "")
    )


def registrable_domain(hostname: str) -> str:
    labels = hostname.lower().rstrip(".").split(".")
    if len(labels) <= 2:
        return ".".join(labels)
    common_second_level = {"co.uk", "org.uk", "com.au", "co.in", "com.br", "co.jp"}
    tail = ".".join(labels[-2:])
    return ".".join(labels[-3:]) if tail in common_second_level else tail


def origin_relation(url: str, submitted_url: str, include_subdomains: bool = False) -> str:
    candidate = urllib.parse.urlsplit(url)
    submitted = urllib.parse.urlsplit(submitted_url)
    candidate_origin = (candidate.scheme, candidate.hostname, candidate.port)
    submitted_origin = (submitted.scheme, submitted.hostname, submitted.port)
    if candidate_origin == submitted_origin:
        return "same_origin"
    if (
        candidate.hostname
        and submitted.hostname
        and (registrable_domain(candidate.hostname) == registrable_domain(submitted.hostname))
    ):
        return "allowed_subdomain" if include_subdomains else "same_domain"
    return "external"


def destructive_path_reason(url: str) -> str | None:
    parts = {
        value for value in re.split(r"[/_.-]+", urllib.parse.urlsplit(url).path.lower()) if value
    }
    matched = sorted(parts & DESTRUCTIVE_PATH_PARTS)
    return f"unsafe_state_changing_path:{matched[0]}" if matched else None


def _decoded_response_body(
    body: bytes,
    headers: dict[str, str],
    config: DiscoveryConfig,
) -> tuple[bytes, bool]:
    limited = len(body) > config.max_response_bytes
    body = body[: config.max_response_bytes]
    if "gzip" not in headers.get("content-encoding", "").lower():
        return body, limited
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(body)) as archive:
            decoded = archive.read(config.max_response_bytes + 1)
    except (OSError, EOFError) as exception:
        raise DiscoveryError(
            "RESPONSE_DECOMPRESSION_FAILED",
            "A compressed discovery response could not be decoded.",
        ) from exception
    decoded_limited = len(decoded) > config.max_response_bytes
    headers.pop("content-encoding", None)
    return decoded[: config.max_response_bytes], limited or decoded_limited


def safe_fetch(url: str, config: DiscoveryConfig) -> FetchResponse:
    current = validate_public_url(url)
    redirects: list[str] = []
    opener = urllib.request.build_opener(_NoRedirect)
    for _ in range(config.max_redirects + 1):
        request = urllib.request.Request(
            current,
            headers={"User-Agent": "ZuiGO-Discovery/1.0", "Accept-Encoding": "gzip"},
        )
        try:
            response = opener.open(request, timeout=config.request_timeout_seconds)
        except urllib.error.HTTPError as exception:
            if exception.code in {301, 302, 303, 307, 308} and exception.headers.get("Location"):
                if len(redirects) >= config.max_redirects:
                    raise DiscoveryError(
                        "DISCOVERY_PAGE_FETCH_FAILED", "The redirect limit was reached."
                    ) from exception
                current = validate_public_url(
                    urllib.parse.urljoin(current, exception.headers["Location"])
                )
                redirects.append(current)
                continue
            if exception.code == 404:
                return FetchResponse(current, 404, {}, b"", redirects)
            raise DiscoveryError(
                "DISCOVERY_PAGE_FETCH_FAILED", "A discovery request failed."
            ) from exception
        with response:
            encoded_body = response.read(config.max_response_bytes + 1)
            headers = {key.lower(): value for key, value in response.headers.items()}
            body, limited = _decoded_response_body(encoded_body, headers, config)
            return FetchResponse(response.url, response.status, headers, body, redirects, limited)
    raise DiscoveryError("DISCOVERY_PAGE_FETCH_FAILED", "The redirect limit was reached.")


def _retryable_fetch_error(exception: BaseException) -> bool:
    if isinstance(exception, UrlSafetyError):
        return exception.code == "DNS_RESOLUTION_FAILED"
    if isinstance(exception, DiscoveryError):
        return exception.code in {
            "DISCOVERY_PAGE_FETCH_FAILED",
            "RESPONSE_DECOMPRESSION_FAILED",
        }
    return isinstance(exception, OSError)


def fetch_with_bounded_retry(
    fetch: Fetch,
    url: str,
    config: DiscoveryConfig,
) -> FetchResponse:
    last_error: BaseException | None = None
    for attempt in range(1, config.max_fetch_attempts + 1):
        try:
            response = fetch(url, config)
            response.attempts = attempt
            return response
        except (DiscoveryError, UrlSafetyError, OSError) as exception:
            last_error = exception
            if not _retryable_fetch_error(exception) or attempt >= config.max_fetch_attempts:
                if hasattr(exception, "attempts"):
                    exception.attempts = attempt
                raise
            time.sleep(config.retry_backoff_seconds * attempt)
    raise AssertionError("bounded discovery retry exhausted") from last_error


class LinkParser(HTMLParser):
    def __init__(self, limit: int) -> None:
        super().__init__(convert_charrefs=True)
        self.limit = limit
        self.links: list[str] = []
        self.canonical: str | None = None
        self.title = ""
        self.h1 = ""
        self._capture: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value for key, value in attrs}
        if tag == "a" and values.get("href") and len(self.links) < self.limit:
            self.links.append(str(values["href"]))
        if tag == "link" and "canonical" in str(values.get("rel", "")).lower():
            self.canonical = values.get("href")
        if tag in {"title", "h1"}:
            self._capture = tag

    def handle_endtag(self, tag: str) -> None:
        if self._capture == tag:
            self._capture = None

    def handle_data(self, data: str) -> None:
        if self._capture == "title":
            self.title = (self.title + " " + data).strip()[:300]
        elif self._capture == "h1":
            self.h1 = (self.h1 + " " + data).strip()[:300]


def parse_robots(
    robots_url: str, response: FetchResponse | None, user_agent: str = "ZuiGO-Discovery"
) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    if response is None:
        return {
            "url": robots_url,
            "fetch_status": "failed",
            "fetched_at": now,
            "policy_status": "unknown",
            "user_agent": user_agent,
            "crawl_delay": None,
            "sitemaps": [],
            "limitations": ["robots.txt could not be fetched; permissions are unknown."],
        }
    if response.status == 404:
        return {
            "url": robots_url,
            "fetch_status": "missing",
            "fetched_at": now,
            "policy_status": "not_present",
            "user_agent": user_agent,
            "crawl_delay": None,
            "sitemaps": [],
            "limitations": [],
        }
    try:
        text = response.body.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return {
            "url": robots_url,
            "fetch_status": "parse_failed",
            "fetched_at": now,
            "policy_status": "unknown",
            "user_agent": user_agent,
            "crawl_delay": None,
            "sitemaps": [],
            "limitations": ["robots.txt encoding could not be parsed."],
        }
    parser = urllib.robotparser.RobotFileParser()
    parser.set_url(robots_url)
    parser.parse(text.splitlines())
    sitemaps = [
        line.split(":", 1)[1].strip()
        for line in text.splitlines()
        if line.lower().startswith("sitemap:") and line.split(":", 1)[1].strip()
    ]
    return {
        "url": robots_url,
        "fetch_status": "available",
        "fetched_at": now,
        "policy_status": "parsed",
        "user_agent": user_agent,
        "crawl_delay": parser.crawl_delay(user_agent) or parser.crawl_delay("*"),
        "sitemaps": sitemaps[:20],
        "limitations": ["Only standard robots exclusion directives are interpreted."],
        "_parser": parser,
    }


def robots_status(policy: dict[str, Any], url: str) -> str:
    if policy["policy_status"] == "not_present":
        return "allowed"
    parser = policy.get("_parser")
    if parser is None:
        return "unknown"
    return "allowed" if parser.can_fetch(policy["user_agent"], url) else "disallowed"


def parse_sitemap(
    sitemap_url: str, response: FetchResponse, max_urls: int
) -> tuple[str, list[dict[str, Any]], bool]:
    body = response.body
    if sitemap_url.lower().endswith(".gz") or response.headers.get("content-type", "").startswith(
        "application/gzip"
    ):
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(body)) as archive:
                body = archive.read(response_limit := 2_000_001)
            if len(body) >= response_limit:
                raise DiscoveryError("SITEMAP_PARSE_FAILED", "Expanded sitemap exceeds its limit.")
        except (OSError, EOFError) as exception:
            raise DiscoveryError(
                "SITEMAP_PARSE_FAILED", "Gzipped sitemap is invalid."
            ) from exception
    if b"<!DOCTYPE" in body.upper():
        raise DiscoveryError("SITEMAP_PARSE_FAILED", "Sitemap document types are not supported.")
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exception:
        raise DiscoveryError("SITEMAP_PARSE_FAILED", "Sitemap XML is invalid.") from exception
    root_name = root.tag.rsplit("}", 1)[-1].lower()
    if root_name not in {"urlset", "sitemapindex"}:
        raise DiscoveryError("SITEMAP_PARSE_FAILED", "The XML is not a supported sitemap.")
    kind = "sitemap_index" if root_name == "sitemapindex" else "sitemap"
    entries = []
    for node in list(root)[:max_urls]:
        loc = next(
            (
                child.text.strip()
                for child in node
                if child.tag.rsplit("}", 1)[-1] == "loc" and child.text
            ),
            None,
        )
        lastmod = next(
            (
                child.text.strip()
                for child in node
                if child.tag.rsplit("}", 1)[-1] == "lastmod" and child.text
            ),
            None,
        )
        if loc:
            entries.append({"url": loc, "last_modified": lastmod})
    return kind, entries, len(list(root)) > max_urls


def classify_page(url: str, *, title: str | None = None, h1: str | None = None) -> dict[str, Any]:
    parsed = urllib.parse.urlsplit(url)
    path = parsed.path.lower().strip("/")
    text = " ".join((path.replace("-", " "), title or "", h1 or "")).lower()
    rules = [
        ("homepage", path == "", ["root_path"]),
        ("privacy_policy", "privacy" in text, ["privacy_indicator"]),
        ("terms_and_conditions", bool(re.search(r"\bterms\b", text)), ["terms_indicator"]),
        ("cookie_policy", "cookie" in text, ["cookie_indicator"]),
        ("contact", "contact" in text, ["contact_indicator"]),
        ("pricing", "pricing" in text or "plans" in text, ["pricing_indicator"]),
        ("careers", "career" in text or "jobs" in text, ["careers_indicator"]),
        ("faq", "faq" in text or "frequently asked" in text, ["faq_indicator"]),
        ("login", bool(re.search(r"\b(login|sign in)\b", text)), ["login_indicator"]),
        ("account", "account" in text, ["account_indicator"]),
        ("checkout", "checkout" in text, ["checkout_indicator"]),
        ("documentation", "docs" in text or "documentation" in text, ["documentation_indicator"]),
        ("support", "support" in text or "help" in text, ["support_indicator"]),
        ("about", bool(re.search(r"\babout\b", text)), ["about_indicator"]),
        ("blog_index", path in {"blog", "articles", "news"}, ["blog_index_path"]),
        (
            "blog_article",
            bool(re.search(r"(?:blog|articles|news)/[^/]+", path)),
            ["blog_article_path"],
        ),
        ("product", "product" in text, ["product_indicator"]),
        ("service", "service" in text, ["service_indicator"]),
        (
            "conversion",
            any(value in text for value in ("thank-you", "success", "confirmation")),
            ["conversion_indicator"],
        ),
    ]
    for page_type, matched, indicators in rules:
        if matched:
            confidence = 100 if page_type == "homepage" else 85 if path else 70
            return {
                "page_type": page_type,
                "confidence_percent": confidence,
                "indicators": [{"code": value} for value in indicators],
                "classification_version": CLASSIFICATION_VERSION,
            }
    return {
        "page_type": "unknown",
        "confidence_percent": 20,
        "indicators": [],
        "classification_version": CLASSIFICATION_VERSION,
    }


def discover_site(
    submitted_url: str,
    config: DiscoveryConfig,
    *,
    fetch: Fetch = safe_fetch,
    rendered_links: list[str] | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    submitted = normalize_url(submitted_url)
    root = urllib.parse.urlunsplit((*urllib.parse.urlsplit(submitted)[:2], "/", "", ""))
    candidates: dict[str, dict[str, Any]] = {}
    raw_link_occurrences = 0
    unique_candidates_before_limit = 0
    limit_reached = False
    url_cap_hit = False
    depth_blocked_urls: list[str] = []
    depth_blocked_total = 0
    query_variant_counts: dict[str, int] = {}
    query_variant_suppressed = 0
    errors: list[dict[str, str]] = []

    def bounded_fetch(url: str) -> FetchResponse:
        return fetch_with_bounded_retry(fetch, url, config)

    def add(url: str, source: str, source_page: str | None, depth: int) -> str | None:
        nonlocal raw_link_occurrences, unique_candidates_before_limit, limit_reached
        nonlocal query_variant_suppressed, url_cap_hit
        raw_link_occurrences += 1
        try:
            normalized = normalize_url(url, source_page or submitted)
        except DiscoveryError:
            return None
        is_new = normalized not in candidates
        if is_new:
            unique_candidates_before_limit += 1
            split = urllib.parse.urlsplit(normalized)
            if split.query:
                path_key = f"{split.scheme}://{split.netloc}{split.path}"
                seen_variants = query_variant_counts.get(path_key, 0)
                if seen_variants >= config.max_query_variants_per_path:
                    query_variant_suppressed += 1
                    if not any(item["code"] == "QUERY_VARIANT_LIMIT_REACHED" for item in errors):
                        errors.append(
                            {
                                "code": "QUERY_VARIANT_LIMIT_REACHED",
                                "message": (
                                    "A per-path query-parameter variant limit protected "
                                    "against an unbounded URL space; excess variants for at "
                                    "least one path were not enqueued."
                                ),
                            }
                        )
                    return None
                query_variant_counts[path_key] = seen_variants + 1
        if is_new and len(candidates) >= config.max_discovered_urls:
            limit_reached = True
            url_cap_hit = True
            if not any(item["code"] == "PAGE_LIMIT_REACHED" for item in errors):
                errors.append(
                    {
                        "code": "PAGE_LIMIT_REACHED",
                        "message": "The discovered URL limit was reached.",
                    }
                )
            return None
        relation = origin_relation(normalized, submitted, config.include_verified_subdomains)
        reason = destructive_path_reason(normalized)
        resource = classify_resource(
            normalized,
            origin_relation=relation,
            eligibility_status="eligible",
        )
        if resource.classification in {
            ResourceClassification.DOCUMENT_ASSET,
            ResourceClassification.MEDIA_STATIC_ASSET,
        }:
            reason = resource.classification.value
        eligibility = (
            "excluded" if relation in {"external", "same_domain"} or reason else "eligible"
        )
        exclusion = (
            "external_url"
            if relation == "external"
            else "subdomain_not_enabled"
            if relation == "same_domain"
            else reason
        )
        now = datetime.now(UTC).isoformat()
        evidence = {
            "source": source,
            "source_page_url": source_page,
            "crawl_depth": depth,
            "discovered_at": now,
            "original_url": url[:2048],
        }
        if normalized in candidates:
            candidates[normalized]["discovery_evidence"].append(evidence)
            candidates[normalized]["crawl_depth"] = min(
                candidates[normalized]["crawl_depth"], depth
            )
        else:
            candidates[normalized] = {
                "normalized_url": normalized,
                "original_url": url[:2048],
                "final_url": None,
                "canonical_url": None,
                "page_title": None,
                **classify_page(normalized),
                "discovery_source": source,
                "discovery_evidence": [evidence],
                "source_page_url": source_page,
                "crawl_depth": depth,
                "origin_relation": relation,
                "robots_status": "unknown",
                "eligibility_status": eligibility,
                "exclusion_reason": exclusion,
                "skip_reason": None,
            }
        return normalized

    add(submitted, "submitted_url", None, 0)
    robots_url = urllib.parse.urljoin(root, "robots.txt")
    try:
        robots_response = bounded_fetch(robots_url)
    except (DiscoveryError, UrlSafetyError, OSError):
        robots_response = None
        errors.append(
            {
                "code": "ROBOTS_FETCH_FAILED",
                "message": (
                    "robots.txt was unavailable after bounded retries; crawl permissions "
                    "remain unknown."
                ),
            }
        )
    policy = parse_robots(robots_url, robots_response)
    policy["fetch_attempts"] = (
        robots_response.attempts if robots_response else config.max_fetch_attempts
    )
    sitemap_queue: deque[tuple[str, int, str]] = deque(
        [(url, 0, "robots_sitemap") for url in policy["sitemaps"]]
        + [(urllib.parse.urljoin(root, "sitemap.xml"), 0, "sitemap")]
    )
    seen_sitemaps: set[str] = set()
    sitemap_records: list[dict[str, Any]] = []
    while sitemap_queue and len(seen_sitemaps) < config.max_sitemap_files:
        if time.monotonic() - started > config.deadline_seconds:
            errors.append(
                {
                    "code": "DISCOVERY_DEADLINE_EXCEEDED",
                    "message": "The discovery deadline was reached during sitemap processing.",
                }
            )
            break
        sitemap_url, depth, source = sitemap_queue.popleft()
        try:
            normalized_sitemap = normalize_url(sitemap_url, root)
            if normalized_sitemap in seen_sitemaps:
                continue
            seen_sitemaps.add(normalized_sitemap)
            if (
                origin_relation(normalized_sitemap, submitted, config.include_verified_subdomains)
                == "external"
            ):
                sitemap_records.append(
                    {
                        "url": normalized_sitemap,
                        "type": "unknown",
                        "fetch_status": "rejected",
                        "rejected": 1,
                        "reason": "external_sitemap",
                    }
                )
                continue
            response = bounded_fetch(normalized_sitemap)
            if response.status == 404:
                sitemap_records.append(
                    {"url": normalized_sitemap, "type": "unknown", "fetch_status": "missing"}
                )
                continue
            kind, entries, url_limit_reached = parse_sitemap(
                normalized_sitemap, response, config.max_discovered_urls
            )
            accepted = rejected = deduplicated = 0
            for entry in entries:
                entry_url = entry["url"]
                if kind == "sitemap_index":
                    if depth < config.max_sitemap_depth:
                        sitemap_queue.append((entry_url, depth + 1, "sitemap_index"))
                    else:
                        rejected += 1
                    continue
                before = len(candidates)
                result = add(entry_url, source, normalized_sitemap, 0)
                if result is None:
                    rejected += 1
                elif len(candidates) == before:
                    deduplicated += 1
                else:
                    accepted += 1
            sitemap_records.append(
                {
                    "url": normalized_sitemap,
                    "type": kind,
                    "fetch_status": "available",
                    "declared": len(entries),
                    "accepted": accepted,
                    "rejected": rejected,
                    "deduplicated": deduplicated,
                    "last_modified": response.headers.get("last-modified"),
                    "size_limit_reached": response.size_limited,
                    "url_limit_reached": url_limit_reached,
                    "fetch_attempts": response.attempts,
                }
            )
        except (DiscoveryError, UrlSafetyError, OSError) as exception:
            sitemap_records.append(
                {
                    "url": str(sitemap_url)[:2048],
                    "type": "unknown",
                    "fetch_status": "failed",
                    "parsing_error": getattr(exception, "code", "SITEMAP_FETCH_FAILED"),
                    "fetch_attempts": int(
                        getattr(exception, "attempts", config.max_fetch_attempts)
                    ),
                }
            )
            errors.append(
                {
                    "code": "SITEMAP_FETCH_FAILED",
                    "message": "A sitemap could not be processed after bounded retries.",
                }
            )
    if sitemap_queue:
        limit_reached = True
        errors.append(
            {"code": "SITEMAP_LIMIT_REACHED", "message": "The sitemap file limit was reached."}
        )
    for rendered in (rendered_links or [])[: config.max_links_per_page]:
        add(rendered, "rendered_dom", submitted, 1)

    html_queue: deque[tuple[str, int]] = deque([(submitted, 0)])
    fetched: set[str] = set()
    depth_blocked_seen: set[str] = set()
    maximum_depth = 0
    while html_queue and len(fetched) < config.max_html_pages:
        if time.monotonic() - started > config.deadline_seconds:
            if not any(item["code"] == "DISCOVERY_DEADLINE_EXCEEDED" for item in errors):
                errors.append(
                    {
                        "code": "DISCOVERY_DEADLINE_EXCEEDED",
                        "message": "The discovery deadline was reached during HTML crawling.",
                    }
                )
            break
        current, depth = html_queue.popleft()
        if current in fetched or depth > config.max_crawl_depth:
            continue
        page = candidates.get(current)
        if not page or page["eligibility_status"] != "eligible":
            continue
        robot_result = robots_status(policy, current)
        page["robots_status"] = robot_result
        if robot_result == "disallowed":
            page["eligibility_status"] = "excluded"
            page["exclusion_reason"] = "robots_disallowed"
            continue
        try:
            response = bounded_fetch(current)
            final_url = normalize_url(response.url)
            if (
                origin_relation(final_url, submitted, config.include_verified_subdomains)
                == "external"
            ):
                page["eligibility_status"] = "excluded"
                page["exclusion_reason"] = "unsafe_external_redirect"
                page["final_url"] = final_url
                continue
            content_type = response.headers.get("content-type", "")
            if response.status >= 400 or "html" not in content_type.lower():
                page["skip_reason"] = (
                    f"http_status_{response.status}"
                    if response.status >= 400
                    else "non_html_response"
                )
                page["eligibility_status"] = "skipped"
                continue
            parser = LinkParser(config.max_links_per_page)
            parser.feed(response.body.decode("utf-8", errors="replace"))
            page["final_url"] = final_url
            page["page_title"] = parser.title or None
            page["discovery_evidence"][-1]["fetch_attempts"] = response.attempts
            page["discovery_evidence"][-1]["fetch_status"] = "available"
            page.update(classify_page(final_url, title=parser.title, h1=parser.h1))
            if parser.canonical:
                canonical = add(parser.canonical, "canonical", current, depth)
                if (
                    canonical
                    and origin_relation(canonical, submitted, config.include_verified_subdomains)
                    != "external"
                ):
                    page["canonical_url"] = canonical
                    canonical_page = candidates[canonical]
                    if canonical_page["exclusion_reason"] == "subdomain_not_enabled":
                        canonical_page["eligibility_status"] = "eligible"
                        canonical_page["exclusion_reason"] = None
                        canonical_page["origin_relation"] = "verified_canonical_domain"
            fetched.add(current)
            maximum_depth = max(maximum_depth, depth)
            if depth >= config.max_crawl_depth:
                new_at_depth = 0
                for link in parser.links:
                    try:
                        norm_link = normalize_url(link, current)
                    except DiscoveryError:
                        continue
                    if (
                        norm_link not in candidates
                        and norm_link not in fetched
                        and norm_link not in depth_blocked_seen
                    ):
                        origin = origin_relation(
                            norm_link, submitted, config.include_verified_subdomains
                        )
                        if origin == "external" or destructive_path_reason(norm_link):
                            continue
                        depth_blocked_seen.add(norm_link)
                        new_at_depth += 1
                        depth_blocked_total += 1
                        if len(depth_blocked_urls) < 10:
                            depth_blocked_urls.append(norm_link)
                if new_at_depth > 0:
                    limit_reached = True
                    if not any(item["code"] == "CRAWL_DEPTH_LIMIT_REACHED" for item in errors):
                        errors.append(
                            {
                                "code": "CRAWL_DEPTH_LIMIT_REACHED",
                                "message": (
                                    "The crawl-depth safety bound "
                                    f"({config.max_crawl_depth} hops) was reached with "
                                    f"{new_at_depth} unique in-scope candidate(s) still "
                                    "unfollowed."
                                ),
                            }
                        )
                continue
            for link in parser.links:
                discovered = add(
                    link, "homepage_link" if depth == 0 else "page_link", current, depth + 1
                )
                if discovered and discovered not in fetched:
                    html_queue.append((discovered, depth + 1))
        except (DiscoveryError, UrlSafetyError, OSError) as exception:
            page["eligibility_status"] = "skipped"
            page["skip_reason"] = "discovery_page_fetch_failed"
            page["discovery_evidence"][-1]["fetch_attempts"] = int(
                getattr(exception, "attempts", config.max_fetch_attempts)
            )
            page["discovery_evidence"][-1]["fetch_status"] = "failed"
            errors.append(
                {
                    "code": "DISCOVERY_PAGE_FETCH_FAILED",
                    "message": (
                        "The submitted root page could not be fetched after bounded retries."
                        if depth == 0
                        else (
                            "An internal discovery page could not be fetched after bounded retries."
                        )
                    ),
                }
            )
    html_page_cap_hit = bool(html_queue) and len(fetched) >= config.max_html_pages
    if html_page_cap_hit:
        limit_reached = True
        if not any(item["code"] == "PAGE_LIMIT_REACHED" for item in errors):
            errors.append(
                {
                    "code": "PAGE_LIMIT_REACHED",
                    "message": "The HTML discovery-page limit was reached.",
                }
            )
    for page in candidates.values():
        if page["robots_status"] == "unknown" and page["eligibility_status"] == "eligible":
            page["robots_status"] = robots_status(policy, page["normalized_url"])
            if page["robots_status"] == "disallowed":
                page["eligibility_status"] = "excluded"
                page["exclusion_reason"] = "robots_disallowed"
    for normalized, page in list(candidates.items()):
        canonical = page.get("canonical_url")
        if not canonical or canonical == normalized or canonical not in candidates:
            continue
        target = candidates[canonical]
        target["discovery_evidence"].extend(page["discovery_evidence"])
        target["crawl_depth"] = min(target["crawl_depth"], page["crawl_depth"])
        target["original_url"] = page["original_url"]
        target["final_url"] = page["final_url"] or target["final_url"]
        target["page_title"] = page["page_title"] or target["page_title"]
        target["canonical_url"] = canonical
        if page["page_type"] != "unknown":
            target.update(
                {
                    key: page[key]
                    for key in (
                        "page_type",
                        "confidence_percent",
                        "indicators",
                        "classification_version",
                    )
                }
            )
        del candidates[normalized]
    robots_public = {key: value for key, value in policy.items() if key != "_parser"}
    pages = list(candidates.values())
    eligible_count = sum(page["eligibility_status"] == "eligible" for page in pages)
    excluded_count = sum(page["eligibility_status"] == "excluded" for page in pages)
    skipped_count = sum(page["eligibility_status"] == "skipped" for page in pages)
    document_count = sum(
        page["exclusion_reason"] == ResourceClassification.DOCUMENT_ASSET.value for page in pages
    )
    media_count = sum(
        page["exclusion_reason"] == ResourceClassification.MEDIA_STATIC_ASSET.value
        for page in pages
    )
    external_count = sum(page["origin_relation"] == "external" for page in pages)
    redirect_count = sum(
        bool(page["final_url"]) and page["final_url"] != page["normalized_url"] for page in pages
    )

    # A normal finite website terminates by frontier exhaustion. Discovery is only
    # "partial" when a genuine safety bound left unique, valid, in-scope candidates
    # unprocessed, or when a page we intended to crawl could not be fetched (so its
    # outgoing links are unknown). A high historical depth threshold on its own,
    # with nothing left to visit, never makes discovery partial.
    remaining_queue_urls = {
        url
        for url, _ in html_queue
        if url not in fetched
        and (candidates.get(url) or {}).get("eligibility_status") == "eligible"
    }
    remaining_sitemap_count = len(sitemap_queue)
    remaining_unique_candidate_count = (
        len(remaining_queue_urls) + depth_blocked_total + remaining_sitemap_count
    )
    fetch_incomplete = any(item["code"] == "DISCOVERY_PAGE_FETCH_FAILED" for item in errors)
    deadline_exceeded = any(item["code"] == "DISCOVERY_DEADLINE_EXCEEDED" for item in errors)
    partial_due_to_safety = remaining_unique_candidate_count > 0
    limit_reached = partial_due_to_safety
    status = "partial" if partial_due_to_safety or fetch_incomplete else "completed"

    if deadline_exceeded:
        safety_limit_type, safety_limit_value = "job_deadline_seconds", config.deadline_seconds
    elif url_cap_hit:
        safety_limit_type, safety_limit_value = "max_discovered_urls", config.max_discovered_urls
    elif html_page_cap_hit:
        safety_limit_type, safety_limit_value = "max_html_pages", config.max_html_pages
    elif depth_blocked_total > 0:
        safety_limit_type, safety_limit_value = "max_crawl_depth", config.max_crawl_depth
    elif remaining_sitemap_count > 0:
        safety_limit_type, safety_limit_value = "max_sitemap_files", config.max_sitemap_files
    else:
        safety_limit_type, safety_limit_value = None, None

    sample_remaining = (depth_blocked_urls + sorted(remaining_queue_urls))[:10]
    if partial_due_to_safety:
        reason = (
            f"{remaining_unique_candidate_count} unique in-scope candidate(s) remained "
            f"unprocessed when the {safety_limit_type} safety bound was reached."
        )
    elif fetch_incomplete:
        reason = "One or more intended pages could not be fetched after bounded retries."
    else:
        reason = "Frontier exhausted; all unique in-scope candidates were processed."
    safety_limits = {
        "safety_limit_type": safety_limit_type if partial_due_to_safety else None,
        "safety_limit_value": safety_limit_value if partial_due_to_safety else None,
        "remaining_unique_candidate_count": remaining_unique_candidate_count,
        "sample_remaining_urls": sample_remaining,
        "reason": reason,
        "resume_possible": remaining_unique_candidate_count > 0,
        "query_variant_suppressed": query_variant_suppressed,
    }
    return {
        "configuration": asdict(config),
        "pages": pages,
        "robots": robots_public,
        "sitemaps": sitemap_records,
        "errors": errors,
        "counts": {
            "raw_link_occurrences": raw_link_occurrences,
            "unique_candidates_encountered": unique_candidates_before_limit,
            "discovered": len(pages),
            "unique": len(pages),
            "eligible": eligible_count,
            "excluded": excluded_count,
            "skipped": skipped_count,
            "documents": document_count,
            "media": media_count,
            "external": external_count,
            "redirects": redirect_count,
            "sitemaps": len(seen_sitemaps),
        },
        "crawl_limit_reached": limit_reached,
        "depth_blocked_urls": depth_blocked_urls,
        "depth_blocked_count": depth_blocked_total,
        "remaining_frontier_count": len(remaining_queue_urls),
        "remaining_unique_candidate_count": remaining_unique_candidate_count,
        "safety_limits": safety_limits,
        "maximum_depth_reached": maximum_depth,
        "status": status,
    }
