# ruff: noqa: E501
"""Tests for the content extraction module."""

from worker_app.analysis.content_extraction import extract_content

SAMPLE_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <title>Best Running Shoes 2026 — SportGear Reviews</title>
    <meta name="description" content="Our expert review of the top running shoes for 2026.">
    <meta property="og:title" content="Best Running Shoes 2026">
    <script type="application/ld+json">
    {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "SuperRun Pro X",
        "description": "The fastest marathon shoe of 2026",
        "offers": {"@type": "Offer", "price": "199.99", "priceCurrency": "USD"}
    }
    </script>
</head>
<body>
    <nav>
        <ul>
            <li><a href="/">Home</a></li>
            <li><a href="/shoes">Shoes</a></li>
            <li><a href="/contact">Contact</a></li>
        </ul>
    </nav>
    <main>
        <article>
            <h1>Best Running Shoes 2026</h1>
            <p>We tested over 50 running shoes to find the best options for every type of runner.
               Our testing process involves 100 miles of road and trail running with each shoe.</p>
            <h2>Top Pick: SuperRun Pro X</h2>
            <p>The SuperRun Pro X combines lightweight carbon fiber with responsive foam for
               an unmatched running experience. At $199.99, it represents excellent value.</p>
            <table>
                <caption>Shoe Specifications</caption>
                <tr><th>Feature</th><th>Value</th></tr>
                <tr><td>Weight</td><td>198g</td></tr>
                <tr><td>Drop</td><td>6mm</td></tr>
                <tr><td>Stack Height</td><td>39.5mm</td></tr>
            </table>
            <h2>Runner-Up: AirGlide Ultra</h2>
            <p>For those seeking maximum cushioning, the AirGlide Ultra delivers exceptional
               comfort on long runs without sacrificing speed.</p>
            <img src="https://example.com/shoes/superrun.jpg" alt="SuperRun Pro X side view" width="800" height="600">
            <img src="https://example.com/icon-star.svg" alt="" width="16" height="16" class="icon">
            <h2>Frequently Asked Questions</h2>
            <details>
                <summary>How long do running shoes last?</summary>
                <p>Most running shoes last 300-500 miles depending on running style and terrain.</p>
            </details>
            <details>
                <summary>Should I size up for running shoes?</summary>
                <p>Yes, most runners benefit from going half a size up for proper toe room.</p>
            </details>
            <a href="https://example.com/files/shoe-guide.pdf">Download our full shoe guide (PDF)</a>
            <a href="https://example.com/reviews/airglide">Read the AirGlide Ultra full review</a>
        </article>
    </main>
    <footer>
        <p>© 2026 SportGear Reviews</p>
        <a href="/privacy">Privacy</a>
        <a href="/terms">Terms</a>
        <span class="footer-dot">·</span>
        <small>All rights reserved</small>
    </footer>
</body>
</html>
"""


def test_extract_content_returns_structured_data():
    result = extract_content(SAMPLE_HTML, "https://example.com/shoes/best-running")
    assert result["extraction_status"] == "completed"
    assert result["title"] is not None
    assert result["url"] == "https://example.com/shoes/best-running"


def test_extract_content_finds_meaningful_headings():
    result = extract_content(SAMPLE_HTML, "https://example.com/shoes/best-running")
    headings = result["headings"]
    heading_texts = [h["text"] for h in headings]
    assert any("Running Shoes" in t for t in heading_texts)
    assert any("SuperRun" in t for t in heading_texts)


def test_extract_content_extracts_tables():
    result = extract_content(SAMPLE_HTML, "https://example.com/shoes/best-running")
    tables = result["tables"]
    assert len(tables) >= 1
    table = tables[0]
    assert "headers" in table
    assert "rows" in table
    assert len(table["rows"]) >= 3


def test_extract_content_finds_faqs():
    result = extract_content(SAMPLE_HTML, "https://example.com/shoes/best-running")
    faqs = result["faqs"]
    assert len(faqs) >= 2
    questions = [f["question"] for f in faqs]
    assert any("running shoes last" in q.lower() for q in questions)
    assert all(f["answer"] for f in faqs)


def test_extract_content_filters_noise_images():
    result = extract_content(SAMPLE_HTML, "https://example.com/shoes/best-running")
    images = result["images"]
    srcs = [img["src"] for img in images]
    assert any("superrun" in s for s in srcs)
    assert not any("icon" in s for s in srcs)


def test_extract_content_finds_downloads():
    result = extract_content(SAMPLE_HTML, "https://example.com/shoes/best-running")
    downloads = result["downloadable_files"]
    assert len(downloads) >= 1
    assert any(d["file_type"] == "pdf" for d in downloads)


def test_extract_content_detects_structured_data():
    result = extract_content(SAMPLE_HTML, "https://example.com/shoes/best-running")
    structured = result["structured_data"]
    assert "json_ld" in structured or "opengraph" in structured


def test_extract_content_detects_page_type():
    result = extract_content(SAMPLE_HTML, "https://example.com/shoes/best-running")
    assert result["page_type_hint"] == "product"


def test_extract_content_provides_stats():
    result = extract_content(SAMPLE_HTML, "https://example.com/shoes/best-running")
    stats = result["content_stats"]
    assert stats["word_count"] > 0
    assert stats["heading_count"] > 0
    assert stats["table_count"] > 0


def test_extract_content_has_paragraphs():
    result = extract_content(SAMPLE_HTML, "https://example.com/shoes/best-running")
    paragraphs = result["paragraphs"]
    assert len(paragraphs) > 0
    assert all(len(p) > 20 for p in paragraphs)


def test_extract_content_filters_nav_footer_links():
    result = extract_content(SAMPLE_HTML, "https://example.com/shoes/best-running")
    links = result["important_links"]
    link_texts = [link["text"].lower() for link in links]
    assert "privacy" not in link_texts
    assert "terms" not in link_texts


def test_extract_content_handles_empty_html():
    result = extract_content("", "https://example.com")
    assert result["extraction_status"] == "empty"
    assert result["title"] is None
    assert result["paragraphs"] == []


def test_extract_content_handles_minimal_html():
    result = extract_content("<html><body><p>Hello world</p></body></html>", "https://example.com")
    assert result["extraction_status"] == "completed"


def test_extract_blog_page_type():
    blog_html = """
    <html><head><title>How to Start Running - Blog</title></head>
    <body><main><article>
    <h1>How to Start Running: A Beginner's Guide</h1>
    <p>Starting a running routine can transform your health and fitness.</p>
    </article></main></body></html>
    """
    result = extract_content(blog_html, "https://example.com/blog/start-running")
    assert result["page_type_hint"] in ("article", "general")


def test_extract_documentation_page_type():
    doc_html = """
    <html><head><title>API Documentation</title></head>
    <body><main>
    <h1>REST API Reference</h1>
    <h2>Authentication</h2>
    <p>Use Bearer tokens for all API calls.</p>
    <h2>Endpoints</h2>
    <table><tr><th>Method</th><th>Path</th></tr>
    <tr><td>GET</td><td>/api/users</td></tr></table>
    </main></body></html>
    """
    result = extract_content(doc_html, "https://example.com/docs/api")
    assert result["page_type_hint"] == "documentation"
