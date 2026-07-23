import urllib.error
from unittest.mock import MagicMock, patch

from worker_app.analysis.page_analysis import (
    PAGE_ANALYSIS_REASON_CODES,
    _basic_accessibility_signals,
    _basic_seo_signals,
    _check_robots_directives,
    _check_structured_data,
    _detect_content_type,
    _detect_language,
    _extract_forms,
    _extract_heading_structure,
    _extract_images,
    _extract_links,
    _extract_meta_description,
    _extract_title,
    _security_observations,
    analyze_page_level_1,
)
from worker_app.analysis.url_safety import UrlSafetyError


class TestPageAnalysisHelpers:
    def test_extract_title(self) -> None:
        assert _extract_title("<html><head><title>My Page</title></head></html>") == "My Page"
        assert _extract_title("<html></html>") is None
        assert _extract_title("<title>   Spaces   </title>") == "Spaces"

    def test_extract_meta_description(self) -> None:
        html = '<meta name="description" content="Test description">'
        assert _extract_meta_description(html) == "Test description"
        assert _extract_meta_description("<html></html>") is None

    def test_extract_heading_structure(self) -> None:
        html = "<h1>Main</h1><h2>Sub</h2><h3>Detail</h3>"
        headings = _extract_heading_structure(html)
        assert len(headings) == 3
        assert headings[0] == {"level": 1, "text": "Main"}
        assert headings[1] == {"level": 2, "text": "Sub"}
        assert headings[2] == {"level": 3, "text": "Detail"}

    def test_extract_links(self) -> None:
        html = (
            '<a href="/internal">Int</a>'
            '<a href="https://external.com">Ext</a>'
            '<a href="#hash">Hash</a>'
        )
        internal, external = _extract_links(html, "https://example.com/")
        assert internal == 1
        assert external == 1

    def test_extract_images(self) -> None:
        html = '<img src="a.jpg"><img src="b.jpg" alt="B"><img src="c.jpg">'
        total, missing = _extract_images(html)
        assert total == 3
        assert missing == 2

    def test_extract_forms(self) -> None:
        html = "<form></form><form></form>"
        assert _extract_forms(html) == 2

    def test_structured_data(self) -> None:
        html = '<script type="application/ld+json">{}</script>'
        assert _check_structured_data(html)
        assert not _check_structured_data("<html></html>")

    def test_detect_content_type(self) -> None:
        assert _detect_content_type({"content-type": "text/html; charset=utf-8"}) == "text/html"
        assert _detect_content_type({}) is None

    def test_detect_language(self) -> None:
        html = '<html lang="en">'
        assert _detect_language(html, {}) == "en"
        assert _detect_language("<html>", {"content-language": "fr"}) == "fr"

    def test_check_robots_directives(self) -> None:
        html = '<meta name="robots" content="noindex">'
        result = _check_robots_directives(html, {})
        assert result["meta_robots"] == "noindex"

    def test_basic_seo_signals(self) -> None:
        signals = _basic_seo_signals("Title", "Desc", "https://example.com/", [], 0)
        assert signals["has_title"]
        assert signals["has_meta_description"]
        assert signals["has_canonical"]
        assert signals["no_h1"]
        assert not signals["multiple_h1"]

    def test_basic_accessibility_signals(self) -> None:
        signals = _basic_accessibility_signals(5, None, [{"level": 2, "text": "H2"}])
        assert signals["images_missing_alt"] == 5
        assert not signals["has_html_lang"]

    def test_security_observations(self) -> None:
        headers = {
            "strict-transport-security": "max-age=31536000",
            "content-security-policy": "default-src 'self'",
            "x-frame-options": "DENY",
            "x-content-type-options": "nosniff",
            "server": "nginx",
        }
        obs = _security_observations(headers, "https://example.com/")
        assert obs["https"]
        assert obs["strict_transport_security"] == "max-age=31536000"
        assert obs["x_content_type_options"] == "nosniff"

    def test_reason_codes_comprehensive(self) -> None:
        expected = {
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
        assert PAGE_ANALYSIS_REASON_CODES == expected


class TestAnalyzePageLevel1:
    def test_unsafe_url_rejected(self) -> None:
        result = analyze_page_level_1("not-a-url")
        assert result["status"] == "failed"
        assert result["failure_reason_code"] == "unsafe_url"

    def test_http_error_handling(self) -> None:
        result = analyze_page_level_1("http://0.0.0.0/test")
        assert result["status"] == "failed"
        assert result["failure_reason_code"] in ("connection_error", "timeout", "unsafe_url")

    def test_result_structure(self) -> None:
        result = analyze_page_level_1("http://0.0.0.0/")
        assert "requested_url" in result
        assert "final_url" in result
        assert "failure_reason_code" in result
        assert "failure_reason_text" in result
        assert "elapsed_ms" in result
        assert isinstance(result.get("elapsed_ms"), int)


class TestRedirectHandling:
    @patch("worker_app.analysis.page_analysis._OPENER.open")
    @patch("worker_app.analysis.page_analysis.validate_public_url")
    def test_same_origin_redirect(self, mock_validate: MagicMock, mock_open: MagicMock) -> None:
        resp_final = MagicMock()
        resp_final.status = 200
        resp_final.url = "https://example.com/new"
        resp_final.headers = {"Content-Type": "text/html"}
        resp_final.read.return_value = b"<html><title>OK</title></html>"

        mock_open.side_effect = [
            urllib.error.HTTPError(
                "https://example.com/old",
                302,
                "Found",
                {"Location": "/new"},
                None,
            ),
            resp_final,
        ]
        mock_validate.side_effect = lambda url, **kw: url

        result = analyze_page_level_1("https://example.com/old")
        assert result["status"] == "completed"
        assert result["final_url"] == "https://example.com/new"

    @patch("worker_app.analysis.page_analysis._OPENER.open")
    @patch("worker_app.analysis.page_analysis.validate_public_url")
    def test_cross_origin_redirect(self, mock_validate: MagicMock, mock_open: MagicMock) -> None:
        mock_open.side_effect = [
            urllib.error.HTTPError(
                "https://example.com/",
                302,
                "Found",
                {"Location": "https://other.com/"},
                None,
            ),
        ]
        mock_validate.side_effect = lambda url, **kw: url

        result = analyze_page_level_1("https://example.com/")
        assert result["status"] == "failed"
        assert result["failure_reason_code"] == "redirect_outside_origin"

    @patch("worker_app.analysis.page_analysis._OPENER.open")
    @patch("worker_app.analysis.page_analysis.validate_public_url")
    def test_redirect_to_private_ip(self, mock_validate: MagicMock, mock_open: MagicMock) -> None:
        mock_open.side_effect = [
            urllib.error.HTTPError(
                "https://example.com/",
                302,
                "Found",
                {"Location": "http://127.0.0.1/"},
                None,
            ),
        ]

        def validate_side_effect(url: str, **kw: object) -> str:
            if url.startswith("http://127.0.0.1"):
                msg = "Private network targets are not allowed."
                raise UrlSafetyError("PRIVATE_NETWORK_TARGET", msg)
            return url

        mock_validate.side_effect = validate_side_effect

        result = analyze_page_level_1("https://example.com/")
        assert result["status"] == "failed"
        assert result["failure_reason_code"] == "PRIVATE_NETWORK_TARGET"

    @patch("worker_app.analysis.page_analysis._OPENER.open")
    @patch("worker_app.analysis.page_analysis.validate_public_url")
    def test_excessive_redirects(self, mock_validate: MagicMock, mock_open: MagicMock) -> None:
        redirects = [
            urllib.error.HTTPError(
                f"https://example.com/step{i}",
                302,
                "Found",
                {"Location": f"https://example.com/step{i + 1}"},
                None,
            )
            for i in range(6)
        ]
        mock_open.side_effect = redirects
        mock_validate.side_effect = lambda url, **kw: url

        result = analyze_page_level_1("https://example.com/start", max_redirects=5)
        assert result["status"] == "failed"

    @patch("worker_app.analysis.page_analysis._OPENER.open")
    @patch("worker_app.analysis.page_analysis.validate_public_url")
    def test_relative_redirect(self, mock_validate: MagicMock, mock_open: MagicMock) -> None:
        resp_final = MagicMock()
        resp_final.status = 200
        resp_final.url = "https://example.com/b"
        resp_final.headers = {"Content-Type": "text/html"}
        resp_final.read.return_value = b"<html><title>B</title></html>"

        mock_open.side_effect = [
            urllib.error.HTTPError(
                "https://example.com/a",
                302,
                "Found",
                {"Location": "/b"},
                None,
            ),
            resp_final,
        ]
        mock_validate.side_effect = lambda url, **kw: url

        result = analyze_page_level_1("https://example.com/a")
        assert result["status"] == "completed"
        assert result["final_url"] == "https://example.com/b"

    @patch("worker_app.analysis.page_analysis._OPENER.open")
    @patch("worker_app.analysis.page_analysis.validate_public_url")
    def test_safe_final_url(self, mock_validate: MagicMock, mock_open: MagicMock) -> None:
        resp = MagicMock()
        resp.status = 200
        resp.url = "https://example.com/final"
        resp.headers = {"Content-Type": "text/html"}
        resp.read.return_value = b"<html><title>OK</title></html>"

        mock_open.return_value = resp
        mock_validate.side_effect = lambda url, **kw: url

        result = analyze_page_level_1("https://example.com/")
        assert result["status"] == "completed"
        assert result["final_url"] == "https://example.com/final"


def test_level2_skips_failed_l1_pages() -> None:
    from worker_app.tasks.page_analysis import select_level2_pages

    def p(pt: str, il: int, url: str, l1: str) -> dict:
        return {
            "page_type": pt,
            "internal_link_count": il,
            "normalized_url": url,
            "page_analysis_level_1_status": l1,
        }

    candidates = [
        p("product", 3, "/product", "completed"),
        p("blog", 2, "/blog", "partial"),
        p("homepage", 10, "/", "failed"),
        p("service", 5, "/service", "failed"),
        p("about", 1, "/about", "pending"),
        p("contact", 4, "/contact", "skipped"),
    ]

    eligible_l1 = [
        c for c in candidates if c.get("page_analysis_level_1_status") in ("completed", "partial")
    ]
    assert len(eligible_l1) == 2
    assert eligible_l1[0]["page_type"] == "product"
    assert eligible_l1[1]["page_type"] == "blog"

    selected = select_level2_pages(eligible_l1, max_lighthouse_pages=10)
    assert all(p.get("page_analysis_level_1_status") in ("completed", "partial") for p in selected)

    failed_only = [c for c in candidates if c.get("page_analysis_level_1_status") == "failed"]
    selected_failed = select_level2_pages(failed_only, max_lighthouse_pages=10)
    assert all(p.get("page_analysis_level_1_status") == "failed" for p in selected_failed)


def test_deterministic_level2_selection() -> None:
    from worker_app.tasks.page_analysis import select_level2_pages

    pages = [
        {"page_type": "service", "internal_link_count": 5, "normalized_url": "/service"},
        {"page_type": "homepage", "internal_link_count": 10, "normalized_url": "/"},
        {"page_type": "product", "internal_link_count": 3, "normalized_url": "/product"},
        {"page_type": "blog", "internal_link_count": 2, "normalized_url": "/blog"},
    ]
    selected = select_level2_pages(pages, max_lighthouse_pages=2)
    assert len(selected) == 2
    assert selected[0]["page_type"] == "homepage"
    assert selected[1]["page_type"] == "product"

    selected_all = select_level2_pages(pages, max_lighthouse_pages=10)
    assert len(selected_all) == 4
    assert selected_all[0]["page_type"] == "homepage"
    assert selected_all[1]["page_type"] == "product"
    assert selected_all[2]["page_type"] == "service"
    assert selected_all[3]["page_type"] == "blog"
