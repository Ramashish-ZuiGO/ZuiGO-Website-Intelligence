import gzip

import pytest
from worker_app.discovery.engine import (
    DiscoveryConfig,
    DiscoveryError,
    FetchResponse,
    _decoded_response_body,
    classify_page,
    discover_site,
    fetch_with_bounded_retry,
    normalize_url,
    parse_robots,
    parse_sitemap,
    robots_status,
)


def response(
    url: str,
    body: str | bytes = "",
    *,
    status: int = 200,
    content_type: str = "text/html",
    size_limited: bool = False,
    headers: dict[str, str] | None = None,
) -> FetchResponse:
    return FetchResponse(
        url=url,
        status=status,
        headers={"content-type": content_type, **(headers or {})},
        body=body.encode() if isinstance(body, str) else body,
        redirects=[],
        size_limited=size_limited,
    )


def test_gzip_encoded_discovery_responses_are_decoded_before_parsing() -> None:
    config = DiscoveryConfig(max_response_bytes=100_000)
    html = b'<html><a href="/about">About</a></html>'
    robots = b"User-agent: *\nSitemap: https://example.com/sitemap.xml\n"
    sitemap = b"<urlset><url><loc>https://example.com/contact</loc></url></urlset>"
    for payload in (html, robots, sitemap):
        headers = {"content-encoding": "gzip"}
        decoded, limited = _decoded_response_body(gzip.compress(payload), headers, config)
        assert decoded == payload
        assert limited is False
        assert "content-encoding" not in headers


def test_discovery_fetch_retry_is_bounded_and_records_attempt_count() -> None:
    calls = 0

    def fetch(url: str, config: DiscoveryConfig) -> FetchResponse:
        nonlocal calls
        del config
        calls += 1
        if calls < 3:
            raise DiscoveryError("DISCOVERY_PAGE_FETCH_FAILED", "temporary network failure")
        return response(url)

    fetched = fetch_with_bounded_retry(
        fetch,
        "https://example.com/",
        DiscoveryConfig(max_fetch_attempts=3, retry_backoff_seconds=0),
    )

    assert calls == 3
    assert fetched.attempts == 3


def test_retried_gzip_discovery_retains_sources_and_finds_internal_pages() -> None:
    attempts: dict[str, int] = {}
    payloads = {
        "https://example.com/robots.txt": (
            "text/plain",
            b"User-agent: *\nSitemap: https://example.com/sitemap.xml\n",
        ),
        "https://example.com/sitemap.xml": (
            "application/xml",
            b"<urlset><url><loc>https://example.com/contact</loc></url></urlset>",
        ),
        "https://example.com/": (
            "text/html",
            b'<html><a href="/about">About</a></html>',
        ),
        "https://example.com/about": ("text/html", b"<html>About</html>"),
        "https://example.com/contact": ("text/html", b"<html>Contact</html>"),
    }

    def fetch(url: str, config: DiscoveryConfig) -> FetchResponse:
        attempts[url] = attempts.get(url, 0) + 1
        if attempts[url] == 1:
            raise DiscoveryError("DISCOVERY_PAGE_FETCH_FAILED", "transient")
        content_type, payload = payloads[url]
        headers = {"content-type": content_type, "content-encoding": "gzip"}
        decoded, limited = _decoded_response_body(gzip.compress(payload), headers, config)
        return FetchResponse(url, 200, headers, decoded, [], limited)

    result = discover_site(
        "https://example.com/",
        DiscoveryConfig(max_fetch_attempts=2, retry_backoff_seconds=0),
        fetch=fetch,
    )

    pages = {page["normalized_url"]: page for page in result["pages"]}
    assert result["status"] == "completed"
    assert {"https://example.com/", "https://example.com/about", "https://example.com/contact"} <= (
        pages.keys()
    )
    assert pages["https://example.com/about"]["discovery_source"] == "homepage_link"
    assert pages["https://example.com/contact"]["discovery_source"] in {
        "robots_sitemap",
        "sitemap",
    }
    assert all(page["discovery_evidence"] for page in pages.values())
    assert all(value == 2 for value in attempts.values())


def test_root_retry_exhaustion_preserves_evidence_and_marks_partial() -> None:
    def fetch(url: str, config: DiscoveryConfig) -> FetchResponse:
        del config
        if url.endswith("robots.txt") or url.endswith("sitemap.xml"):
            return response(url, status=404)
        raise DiscoveryError("DISCOVERY_PAGE_FETCH_FAILED", "transient")

    result = discover_site(
        "https://example.com/",
        DiscoveryConfig(max_fetch_attempts=2, retry_backoff_seconds=0),
        fetch=fetch,
    )

    assert result["status"] == "partial"
    assert result["counts"]["unique"] == 1
    assert result["pages"][0]["discovery_source"] == "submitted_url"
    assert result["pages"][0]["discovery_evidence"][0]["fetch_attempts"] == 2
    assert any(
        item["message"] == "The submitted root page could not be fetched after bounded retries."
        for item in result["errors"]
    )


def test_url_normalization_is_deterministic_and_preserves_meaningful_queries() -> None:
    assert normalize_url("HTTPS://Example.COM:443/path/#part") == "https://example.com/path"
    assert (
        normalize_url("https://example.com/products/?utm_source=x&id=42&fbclid=y&variant=blue")
        == "https://example.com/products?id=42&variant=blue"
    )
    assert normalize_url("http://example.com:80/") == "http://example.com/"
    assert normalize_url("https://example.com/a/") == "https://example.com/a"


@pytest.mark.parametrize(
    "url", ["mailto:test@example.com", "javascript:alert(1)", "ftp://example.com/a", "not a url"]
)
def test_url_normalization_rejects_unsafe_or_malformed_schemes(url: str) -> None:
    with pytest.raises(DiscoveryError, match="HTTP"):
        normalize_url(url)


def test_www_variants_remain_distinct_until_verified_canonical_deduplication() -> None:
    assert normalize_url("https://www.example.com/") != normalize_url("https://example.com/")


def test_robots_allowed_disallowed_missing_parse_failure_and_metadata() -> None:
    robots_url = "https://example.com/robots.txt"
    policy = parse_robots(
        robots_url,
        response(
            robots_url,
            "User-agent: *\nDisallow: /private\nAllow: /\nCrawl-delay: 5\n"
            "Sitemap: https://example.com/site.xml",
            content_type="text/plain",
        ),
    )
    assert robots_status(policy, "https://example.com/public") == "allowed"
    assert robots_status(policy, "https://example.com/private/a") == "disallowed"
    assert policy["crawl_delay"] == 5
    assert policy["sitemaps"] == ["https://example.com/site.xml"]
    missing = parse_robots(robots_url, response(robots_url, status=404))
    assert missing["fetch_status"] == "missing"
    assert robots_status(missing, "https://example.com/a") == "allowed"
    failed = parse_robots(robots_url, response(robots_url, b"\xff", content_type="text/plain"))
    assert failed["policy_status"] == "unknown"
    assert robots_status(failed, "https://example.com/a") == "unknown"


def test_standard_sitemap_index_gzip_limit_and_deduplication() -> None:
    xml = (
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<url><loc>https://example.com/a</loc><lastmod>2026-01-01</lastmod></url>"
        "<url><loc>https://example.com/b</loc></url></urlset>"
    )
    kind, entries, limited = parse_sitemap(
        "https://example.com/sitemap.xml",
        response("https://example.com/sitemap.xml", xml, content_type="application/xml"),
        1,
    )
    assert kind == "sitemap"
    assert entries == [{"url": "https://example.com/a", "last_modified": "2026-01-01"}]
    assert limited is True
    index = "<sitemapindex><sitemap><loc>https://example.com/one.xml</loc></sitemap></sitemapindex>"
    assert (
        parse_sitemap(
            "https://example.com/index.xml",
            response("https://example.com/index.xml", index),
            10,
        )[0]
        == "sitemap_index"
    )
    compressed = gzip.compress(xml.encode())
    assert (
        parse_sitemap(
            "https://example.com/sitemap.xml.gz",
            response(
                "https://example.com/sitemap.xml.gz",
                compressed,
                content_type="application/gzip",
            ),
            10,
        )[0]
        == "sitemap"
    )
    with pytest.raises(DiscoveryError):
        parse_sitemap(
            "https://example.com/sitemap.xml",
            response("https://example.com/sitemap.xml", "<urlset><url>", size_limited=True),
            10,
        )


def test_bounded_discovery_handles_internal_external_destructive_duplicates_and_canonical() -> None:
    homepage = """
    <html><head><title>Home</title></head><body>
      <a href="/contact/">Contact</a><a href="/contact?utm_source=x">Duplicate</a>
      <a href="/logout">Logout</a><a href="https://other.example/page">External</a>
      <a href="/alias">Alias</a>
    </body></html>
    """
    contact = "<html><head><title>Contact us</title></head><body></body></html>"
    alias = (
        '<html><head><title>Services</title><link rel="canonical" '
        'href="https://example.com/services"></head></html>'
    )
    mapping = {
        "https://example.com/robots.txt": response(
            "https://example.com/robots.txt", "User-agent: *\nDisallow: /private"
        ),
        "https://example.com/sitemap.xml": response("https://example.com/sitemap.xml", status=404),
        "https://example.com/": response("https://example.com/", homepage),
        "https://example.com/contact": response("https://example.com/contact", contact),
        "https://example.com/alias": response("https://example.com/alias", alias),
        "https://example.com/services": response(
            "https://example.com/services", "<html><title>Services</title></html>"
        ),
    }

    def fetch(url: str, config: DiscoveryConfig) -> FetchResponse:
        del config
        return mapping[url]

    result = discover_site(
        "https://example.com/",
        DiscoveryConfig(max_html_pages=10),
        fetch=fetch,
        rendered_links=["https://example.com/contact"],
    )
    pages = {item["normalized_url"]: item for item in result["pages"]}
    assert pages["https://example.com/contact"]["page_type"] == "contact"
    assert pages["https://example.com/logout"]["exclusion_reason"].startswith(
        "unsafe_state_changing_path"
    )
    assert pages["https://other.example/page"]["origin_relation"] == "external"
    assert "https://example.com/alias" not in pages
    assert pages["https://example.com/services"]["canonical_url"] == (
        "https://example.com/services"
    )
    contact_sources = {
        item["source"] for item in pages["https://example.com/contact"]["discovery_evidence"]
    }
    assert {"homepage_link", "rendered_dom"} <= contact_sources


def test_discovery_depth_page_limits_robots_and_partial_failures() -> None:
    def fetch(url: str, config: DiscoveryConfig) -> FetchResponse:
        del config
        if url.endswith("robots.txt"):
            return response(url, "User-agent: *\nDisallow: /blocked")
        if url.endswith("sitemap.xml"):
            return response(url, status=404)
        if url == "https://example.com/":
            return response(
                url,
                '<a href="/one">One</a><a href="/blocked">Blocked</a><a href="/broken">Broken</a>',
            )
        if url.endswith("/one"):
            return response(url, '<a href="/two">Two</a>')
        if url.endswith("/broken"):
            raise DiscoveryError("DISCOVERY_PAGE_FETCH_FAILED", "failed")
        raise AssertionError(url)

    result = discover_site(
        "https://example.com/",
        DiscoveryConfig(max_html_pages=3, max_crawl_depth=1, max_discovered_urls=10),
        fetch=fetch,
    )
    pages = {item["normalized_url"]: item for item in result["pages"]}
    assert pages["https://example.com/blocked"]["robots_status"] == "disallowed"
    assert pages["https://example.com/broken"]["eligibility_status"] == "skipped"
    assert result["status"] == "partial"
    assert result["crawl_limit_reached"] is True


def test_sitemap_loop_external_rejection_and_page_limit_are_bounded() -> None:
    index = (
        "<sitemapindex>"
        "<sitemap><loc>https://example.com/sitemap.xml</loc></sitemap>"
        "<sitemap><loc>https://outside.test/sitemap.xml</loc></sitemap>"
        "</sitemapindex>"
    )

    def fetch(url: str, config: DiscoveryConfig) -> FetchResponse:
        del config
        if url.endswith("robots.txt"):
            return response(url, "User-agent: *")
        if url.endswith("sitemap.xml"):
            return response(url, index, content_type="application/xml")
        if url == "https://example.com/":
            return response(url, '<a href="/one">One</a><a href="/two">Two</a>')
        raise AssertionError(url)

    result = discover_site(
        "https://example.com/",
        DiscoveryConfig(max_discovered_urls=2, max_html_pages=1),
        fetch=fetch,
    )
    assert result["counts"]["unique"] == 2
    assert result["crawl_limit_reached"] is True
    assert any(item["code"] == "PAGE_LIMIT_REACHED" for item in result["errors"])
    assert any(item.get("reason") == "external_sitemap" for item in result["sitemaps"])


def test_external_redirect_target_is_excluded_without_fetching_links() -> None:
    def fetch(url: str, config: DiscoveryConfig) -> FetchResponse:
        del config
        if url.endswith("robots.txt") or url.endswith("sitemap.xml"):
            return response(url, status=404)
        return response(
            "https://outside.test/landing",
            '<a href="https://outside.test/action">Action</a>',
        )

    result = discover_site("https://example.com/", DiscoveryConfig(), fetch=fetch)
    homepage = next(
        item for item in result["pages"] if item["normalized_url"] == "https://example.com/"
    )
    assert homepage["exclusion_reason"] == "unsafe_external_redirect"
    assert all(item["normalized_url"] != "https://outside.test/action" for item in result["pages"])


def make_fetch(
    pages: dict[str, str],
    *,
    robots: str = "User-agent: *\n",
    sitemap: dict[str, tuple[str, str]] | None = None,
):
    """Build a deterministic fetch over a fixed set of in-scope HTML pages."""
    mapping: dict[str, FetchResponse] = {
        "https://example.com/robots.txt": response(
            "https://example.com/robots.txt", robots, content_type="text/plain"
        )
    }
    if sitemap is None:
        mapping["https://example.com/sitemap.xml"] = response(
            "https://example.com/sitemap.xml", status=404
        )
    else:
        for url, (content_type, body) in sitemap.items():
            mapping[url] = response(url, body, content_type=content_type)
    for url, body in pages.items():
        mapping[url] = response(url, body)

    def fetch(url: str, config: DiscoveryConfig) -> FetchResponse:
        del config
        return mapping.get(url) or response(url, status=404)

    return fetch


def test_deep_finite_site_completes_beyond_old_depth_threshold() -> None:
    pages = {"https://example.com/": '<a href="/p1">1</a>'}
    for index in range(1, 15):
        pages[f"https://example.com/p{index}"] = f'<a href="/p{index + 1}">next</a>'
    pages["https://example.com/p15"] = "<html>end</html>"

    result = discover_site("https://example.com/", DiscoveryConfig(), fetch=make_fetch(pages))

    urls = {page["normalized_url"] for page in result["pages"]}
    assert result["status"] == "completed"
    assert "https://example.com/p15" in urls
    assert result["maximum_depth_reached"] == 15
    assert not any(item["code"] == "CRAWL_DEPTH_LIMIT_REACHED" for item in result["errors"])
    assert result["remaining_unique_candidate_count"] == 0
    assert result["safety_limits"]["resume_possible"] is False


def test_depth_safety_bound_marks_partial_only_with_remaining_candidates() -> None:
    pages = {"https://example.com/": '<a href="/p1">1</a>'}
    for index in range(1, 5):
        pages[f"https://example.com/p{index}"] = f'<a href="/p{index + 1}">next</a>'
    pages["https://example.com/p5"] = "<html>end</html>"

    result = discover_site(
        "https://example.com/", DiscoveryConfig(max_crawl_depth=2), fetch=make_fetch(pages)
    )

    assert result["status"] == "partial"
    assert result["crawl_limit_reached"] is True
    safety = result["safety_limits"]
    assert safety["safety_limit_type"] == "max_crawl_depth"
    assert safety["safety_limit_value"] == 2
    assert safety["remaining_unique_candidate_count"] >= 1
    assert safety["resume_possible"] is True
    assert safety["sample_remaining_urls"]


def test_cyclic_site_terminates_by_frontier_exhaustion() -> None:
    pages = {
        "https://example.com/": '<a href="/a">a</a>',
        "https://example.com/a": '<a href="/b">b</a><a href="/">home</a>',
        "https://example.com/b": '<a href="/a">a</a><a href="/">home</a>',
    }

    result = discover_site("https://example.com/", DiscoveryConfig(), fetch=make_fetch(pages))

    assert result["status"] == "completed"
    assert {page["normalized_url"] for page in result["pages"]} == {
        "https://example.com/",
        "https://example.com/a",
        "https://example.com/b",
    }


def test_duplicate_navigation_and_repeated_root_links_count_once() -> None:
    nav = '<a href="/">Home</a><a href="/about">About</a><a href="/contact">Contact</a>'
    pages = {
        "https://example.com/": nav + nav,
        "https://example.com/about": nav,
        "https://example.com/contact": nav,
    }

    result = discover_site("https://example.com/", DiscoveryConfig(), fetch=make_fetch(pages))

    counts = result["counts"]
    assert counts["unique"] == 3
    assert counts["raw_link_occurrences"] > counts["unique"]
    roots = [page for page in result["pages"] if page["normalized_url"] == "https://example.com/"]
    assert len(roots) == 1
    assert result["status"] == "completed"


def test_fragments_and_tracking_parameters_do_not_create_new_pages() -> None:
    pages = {
        "https://example.com/": (
            '<a href="/about#team">Team</a>'
            '<a href="/about?utm_source=x&fbclid=y">About</a>'
            '<a href="/about#top">Top</a>'
        ),
        "https://example.com/about": "<html>About</html>",
    }

    result = discover_site("https://example.com/", DiscoveryConfig(), fetch=make_fetch(pages))

    assert {page["normalized_url"] for page in result["pages"]} == {
        "https://example.com/",
        "https://example.com/about",
    }
    assert result["status"] == "completed"


def test_internal_redirect_does_not_consume_depth_or_mark_partial() -> None:
    def fetch(url: str, config: DiscoveryConfig) -> FetchResponse:
        del config
        if url.endswith("robots.txt"):
            return response(url, "User-agent: *")
        if url.endswith("sitemap.xml"):
            return response(url, status=404)
        if url == "https://example.com/":
            return response(url, '<a href="/old">Old</a>')
        if url == "https://example.com/old":
            return FetchResponse(
                "https://example.com/new",
                200,
                {"content-type": "text/html"},
                b"<html>New</html>",
                ["https://example.com/new"],
            )
        raise AssertionError(url)

    result = discover_site("https://example.com/", DiscoveryConfig(), fetch=fetch)

    assert result["status"] == "completed"
    old = next(
        page for page in result["pages"] if page["normalized_url"] == "https://example.com/old"
    )
    assert old["final_url"] == "https://example.com/new"
    assert result["counts"]["redirects"] >= 1


def test_nested_sitemap_index_pages_are_discovered_and_complete() -> None:
    index = (
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<sitemap><loc>https://example.com/sitemap-1.xml</loc></sitemap>"
        "</sitemapindex>"
    )
    child = (
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<url><loc>https://example.com/deep</loc></url></urlset>"
    )

    def fetch(url: str, config: DiscoveryConfig) -> FetchResponse:
        del config
        if url.endswith("robots.txt"):
            return response(url, "User-agent: *")
        if url == "https://example.com/sitemap.xml":
            return response(url, index, content_type="application/xml")
        if url == "https://example.com/sitemap-1.xml":
            return response(url, child, content_type="application/xml")
        if url == "https://example.com/":
            return response(url, "<html>home</html>")
        if url == "https://example.com/deep":
            return response(url, "<html>deep</html>")
        raise AssertionError(url)

    result = discover_site("https://example.com/", DiscoveryConfig(), fetch=fetch)

    urls = {page["normalized_url"] for page in result["pages"]}
    assert "https://example.com/deep" in urls
    assert result["status"] == "completed"


def test_rendered_dom_links_are_discovered() -> None:
    pages = {
        "https://example.com/": "<html>home</html>",
        "https://example.com/spa-route": "<html>route</html>",
    }

    result = discover_site(
        "https://example.com/",
        DiscoveryConfig(),
        fetch=make_fetch(pages),
        rendered_links=["https://example.com/spa-route"],
    )

    route = next(
        page
        for page in result["pages"]
        if page["normalized_url"] == "https://example.com/spa-route"
    )
    assert any(item["source"] == "rendered_dom" for item in route["discovery_evidence"])
    assert result["status"] == "completed"


def test_finite_pagination_is_fully_discovered() -> None:
    pages = {
        "https://example.com/": (
            '<a href="/blog?page=1">1</a><a href="/blog?page=2">2</a><a href="/blog?page=3">3</a>'
        ),
        "https://example.com/blog?page=1": "<html>1</html>",
        "https://example.com/blog?page=2": "<html>2</html>",
        "https://example.com/blog?page=3": "<html>3</html>",
    }

    result = discover_site("https://example.com/", DiscoveryConfig(), fetch=make_fetch(pages))

    urls = {page["normalized_url"] for page in result["pages"]}
    assert {
        "https://example.com/blog?page=1",
        "https://example.com/blog?page=2",
        "https://example.com/blog?page=3",
    } <= urls
    assert result["status"] == "completed"
    assert result["safety_limits"]["query_variant_suppressed"] == 0


def test_infinite_query_variant_space_is_bounded_without_false_partial() -> None:
    def fetch(url: str, config: DiscoveryConfig) -> FetchResponse:
        del config
        if url.endswith("robots.txt"):
            return response(url, "User-agent: *")
        if url.endswith("sitemap.xml"):
            return response(url, status=404)
        if url == "https://example.com/":
            return response(url, '<a href="/feed?page=1">1</a>')
        head, _, page_number = url.partition("?page=")
        if head == "https://example.com/feed" and page_number:
            return response(url, f'<a href="/feed?page={int(page_number) + 1}">next</a>')
        raise AssertionError(url)

    result = discover_site(
        "https://example.com/", DiscoveryConfig(max_query_variants_per_path=5), fetch=fetch
    )

    assert result["status"] == "completed"
    assert result["safety_limits"]["query_variant_suppressed"] >= 1
    feed_pages = [page for page in result["pages"] if "/feed" in page["normalized_url"]]
    assert len(feed_pages) == 5
    assert any(item["code"] == "QUERY_VARIANT_LIMIT_REACHED" for item in result["errors"])


def test_partial_only_when_unique_candidates_remain_with_proof() -> None:
    pages = {
        "https://example.com/": ('<a href="/a">a</a><a href="/b">b</a><a href="/c">c</a>'),
        "https://example.com/a": "<html>a</html>",
        "https://example.com/b": "<html>b</html>",
        "https://example.com/c": "<html>c</html>",
    }

    result = discover_site(
        "https://example.com/", DiscoveryConfig(max_html_pages=2), fetch=make_fetch(pages)
    )

    assert result["status"] == "partial"
    safety = result["safety_limits"]
    assert safety["safety_limit_type"] == "max_html_pages"
    assert safety["safety_limit_value"] == 2
    assert safety["remaining_unique_candidate_count"] >= 1
    assert safety["resume_possible"] is True
    assert safety["sample_remaining_urls"]


def test_frontier_exhaustion_reports_complete_with_zero_remaining() -> None:
    pages = {
        "https://example.com/": '<a href="/a">a</a>',
        "https://example.com/a": "<html>a</html>",
    }

    result = discover_site("https://example.com/", DiscoveryConfig(), fetch=make_fetch(pages))

    assert result["status"] == "completed"
    assert result["remaining_unique_candidate_count"] == 0
    assert result["crawl_limit_reached"] is False
    assert "exhausted" in result["safety_limits"]["reason"].lower()


def test_counts_separate_documents_media_and_external() -> None:
    pages = {
        "https://example.com/": (
            '<a href="/report.pdf">PDF</a>'
            '<a href="/logo.png">IMG</a>'
            '<a href="https://other.test/x">Ext</a>'
            '<a href="/about">About</a>'
        ),
        "https://example.com/about": "<html>About</html>",
    }

    result = discover_site("https://example.com/", DiscoveryConfig(), fetch=make_fetch(pages))

    counts = result["counts"]
    assert counts["documents"] == 1
    assert counts["media"] == 1
    assert counts["external"] == 1
    assert counts["eligible"] == 2


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://example.com/", "homepage"),
        ("https://example.com/contact", "contact"),
        ("https://example.com/services/design", "service"),
        ("https://example.com/products/widget", "product"),
        ("https://example.com/blog", "blog_index"),
        ("https://example.com/blog/article", "blog_article"),
        ("https://example.com/privacy", "privacy_policy"),
        ("https://example.com/terms", "terms_and_conditions"),
        ("https://example.com/login", "login"),
        ("https://example.com/arbitrary", "unknown"),
    ],
)
def test_page_classification(url: str, expected: str) -> None:
    result = classify_page(url)
    assert result["page_type"] == expected
    assert result["classification_version"] == "1.0.0"
