import gzip

import pytest
from worker_app.discovery.engine import (
    DiscoveryConfig,
    DiscoveryError,
    FetchResponse,
    classify_page,
    discover_site,
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
) -> FetchResponse:
    return FetchResponse(
        url=url,
        status=status,
        headers={"content-type": content_type},
        body=body.encode() if isinstance(body, str) else body,
        redirects=[],
        size_limited=size_limited,
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
