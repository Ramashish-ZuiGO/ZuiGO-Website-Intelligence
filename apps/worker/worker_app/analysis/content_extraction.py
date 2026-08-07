"""Structured content extraction from raw HTML.

Extracts clean, meaningful content (title, sections, tables, FAQs,
images, links, downloads, structured data) from a page's raw HTML,
filtering out boilerplate (nav, footer, ads, icons, hidden elements).
"""

import logging
import re
from typing import Any
from urllib.parse import urljoin, urlsplit

import trafilatura
from lxml import html as lxml_html

logger = logging.getLogger(__name__)

DOWNLOAD_EXTENSIONS = frozenset(
    {
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".csv",
        ".ppt",
        ".pptx",
        ".zip",
        ".rar",
        ".7z",
        ".tar",
        ".gz",
    }
)

BOILERPLATE_TAGS = frozenset(
    {
        "nav",
        "footer",
        "header",
        "aside",
        "noscript",
        "script",
        "style",
        "iframe",
        "svg",
        "form",
    }
)

NOISE_ROLES = frozenset(
    {
        "navigation",
        "banner",
        "contentinfo",
        "complementary",
        "search",
    }
)


def extract_content(raw_html: str, url: str) -> dict[str, Any]:
    """Extract structured content from raw HTML."""
    if not raw_html or not raw_html.strip():
        return _empty_result(url)

    try:
        result = _do_extraction(raw_html, url)
        result["extraction_status"] = "completed"
        return result
    except Exception as exc:
        logger.warning("content_extraction_failed url=%s error=%s", url, type(exc).__name__)
        return {**_empty_result(url), "extraction_status": "failed"}


def _empty_result(url: str) -> dict[str, Any]:
    return {
        "url": url,
        "extraction_status": "empty",
        "title": None,
        "summary": None,
        "main_content": None,
        "sections": [],
        "headings": [],
        "paragraphs": [],
        "tables": [],
        "faqs": [],
        "images": [],
        "important_links": [],
        "downloadable_files": [],
        "structured_data": {},
        "metadata": {},
        "page_type_hint": "unknown",
        "content_stats": {},
    }


def _do_extraction(raw_html: str, url: str) -> dict[str, Any]:
    main_text = trafilatura.extract(
        raw_html,
        url=url,
        include_tables=True,
        include_links=True,
        include_images=True,
        include_comments=False,
        output_format="txt",
        favor_precision=True,
    )

    metadata = trafilatura.extract_metadata(raw_html, default_url=url)
    meta_dict = _metadata_to_dict(metadata) if metadata else {}

    try:
        tree = lxml_html.fromstring(raw_html)
        tree.make_links_absolute(url)
    except Exception:
        tree = None

    headings = _extract_headings(tree) if tree is not None else []
    sections = _build_sections(headings, main_text)
    tables = _extract_tables(tree) if tree is not None else []
    faqs = _extract_faqs(tree, raw_html) if tree is not None else []
    images = _extract_meaningful_images(tree, url) if tree is not None else []
    links = _extract_important_links(tree, url) if tree is not None else []
    downloads = _extract_downloads(tree, url) if tree is not None else []
    structured = _extract_structured_data(raw_html, url)
    page_type = _detect_page_type(url, meta_dict, headings, structured, faqs, tables)

    paragraphs = []
    if main_text:
        paragraphs = [
            p.strip() for p in main_text.split("\n\n") if p.strip() and len(p.strip()) > 20
        ]

    summary = meta_dict.get("description")
    if not summary and paragraphs:
        summary = paragraphs[0][:500]

    word_count = len(main_text.split()) if main_text else 0

    return {
        "url": url,
        "title": meta_dict.get("title") or _fallback_title(tree),
        "summary": summary,
        "main_content": main_text,
        "sections": sections,
        "headings": headings,
        "paragraphs": paragraphs[:100],
        "tables": tables[:50],
        "faqs": faqs[:50],
        "images": images[:100],
        "important_links": links[:200],
        "downloadable_files": downloads[:50],
        "structured_data": structured,
        "metadata": meta_dict,
        "page_type_hint": page_type,
        "content_stats": {
            "word_count": word_count,
            "paragraph_count": len(paragraphs),
            "heading_count": len(headings),
            "table_count": len(tables),
            "faq_count": len(faqs),
            "image_count": len(images),
            "link_count": len(links),
            "download_count": len(downloads),
        },
    }


def _metadata_to_dict(meta: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field in (
        "title",
        "author",
        "description",
        "sitename",
        "date",
        "url",
        "categories",
        "tags",
        "license",
    ):
        value = getattr(meta, field, None)
        if value:
            result[field] = value
    return result


def _fallback_title(tree: Any) -> str | None:
    if tree is None:
        return None
    title_el = tree.find(".//title")
    if title_el is not None and title_el.text:
        return title_el.text.strip()[:500]
    h1 = tree.find(".//h1")
    if h1 is not None:
        return (h1.text_content() or "").strip()[:500] or None
    return None


def _extract_headings(tree: Any) -> list[dict[str, Any]]:
    headings: list[dict[str, Any]] = []
    if tree is None:
        return headings
    for element in tree.iter("h1", "h2", "h3", "h4", "h5", "h6"):
        if _is_boilerplate_ancestor(element):
            continue
        text = (element.text_content() or "").strip()
        if not text or len(text) < 2:
            continue
        level = int(element.tag[1])
        headings.append({"level": level, "text": text[:300]})
        if len(headings) >= 100:
            break
    return headings


def _is_boilerplate_ancestor(element: Any) -> bool:
    for ancestor in element.iterancestors():
        if ancestor.tag in BOILERPLATE_TAGS:
            return True
        role = (ancestor.get("role") or "").lower()
        if role in NOISE_ROLES:
            return True
        classes = (ancestor.get("class") or "").lower()
        if any(kw in classes for kw in ("footer", "nav", "sidebar", "menu", "cookie", "banner")):
            return True
    return False


def _build_sections(headings: list[dict[str, Any]], main_text: str | None) -> list[dict[str, Any]]:
    if not headings:
        return []
    sections: list[dict[str, Any]] = []
    for heading in headings:
        sections.append(
            {
                "heading": heading["text"],
                "level": heading["level"],
            }
        )
    return sections[:50]


def _extract_tables(tree: Any) -> list[dict[str, Any]]:
    tables: list[dict[str, Any]] = []
    if tree is None:
        return tables
    for table_el in tree.iter("table"):
        if _is_boilerplate_ancestor(table_el):
            continue
        rows = table_el.findall(".//tr")
        if len(rows) < 2:
            continue
        headers: list[str] = []
        first_row = rows[0]
        for cell in first_row.findall("th"):
            headers.append((cell.text_content() or "").strip()[:200])
        if not headers:
            for cell in first_row.findall("td"):
                headers.append((cell.text_content() or "").strip()[:200])

        data_rows: list[list[str]] = []
        start = 1 if headers else 0
        for row in rows[start:50]:
            cells = []
            for cell in row.findall("td"):
                cells.append((cell.text_content() or "").strip()[:500])
            if not cells:
                for cell in row.findall("th"):
                    cells.append((cell.text_content() or "").strip()[:500])
            if cells:
                data_rows.append(cells)

        if data_rows:
            caption_el = table_el.find("caption")
            caption = (
                (caption_el.text_content() or "").strip()[:200] if caption_el is not None else None
            )
            tables.append(
                {
                    "caption": caption,
                    "headers": headers,
                    "rows": data_rows[:100],
                    "row_count": len(data_rows),
                }
            )
        if len(tables) >= 50:
            break
    return tables


def _extract_faqs(tree: Any, raw_html: str) -> list[dict[str, Any]]:
    faqs: list[dict[str, Any]] = []
    _extract_faqs_from_details(tree, faqs)
    _extract_faqs_from_schema(raw_html, faqs)
    _extract_faqs_from_patterns(tree, faqs)
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for faq in faqs:
        key = faq["question"].lower().strip()
        if key not in seen:
            seen.add(key)
            deduped.append(faq)
    return deduped


def _extract_faqs_from_details(tree: Any, faqs: list[dict[str, Any]]) -> None:
    for details in tree.iter("details"):
        summary = details.find("summary")
        if summary is None:
            continue
        question = (summary.text_content() or "").strip()
        if not question:
            continue
        answer_parts = []
        for child in details:
            if child.tag != "summary":
                text = (child.text_content() or "").strip()
                if text:
                    answer_parts.append(text)
        answer = " ".join(answer_parts)[:2000]
        if answer:
            faqs.append({"question": question[:500], "answer": answer, "source": "details_element"})


def _extract_faqs_from_schema(raw_html: str, faqs: list[dict[str, Any]]) -> None:
    try:
        import json

        for match in re.finditer(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            raw_html,
            re.S | re.I,
        ):
            try:
                data = json.loads(match.group(1))
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") == "FAQPage":
                        for entity in item.get("mainEntity", []):
                            q = entity.get("name", "")
                            a_obj = entity.get("acceptedAnswer", {})
                            a = a_obj.get("text", "") if isinstance(a_obj, dict) else ""
                            if q and a:
                                faqs.append(
                                    {
                                        "question": q[:500],
                                        "answer": a[:2000],
                                        "source": "schema_org",
                                    }
                                )
            except (json.JSONDecodeError, AttributeError):
                continue
    except Exception:
        pass


def _extract_faqs_from_patterns(tree: Any, faqs: list[dict[str, Any]]) -> None:
    faq_keywords = {"faq", "frequently asked", "common questions", "q&a"}
    for element in tree.iter("section", "div"):
        el_id = (element.get("id") or "").lower()
        el_class = (element.get("class") or "").lower()
        heading = element.find(".//h2")
        if heading is None:
            heading = element.find(".//h3")
        heading_text = (heading.text_content() or "").lower() if heading is not None else ""

        if not any(kw in text for kw in faq_keywords for text in (el_id, el_class, heading_text)):
            continue

        for h_tag in ("h3", "h4", "h5", "strong"):
            questions = element.findall(f".//{h_tag}")
            for q_el in questions:
                question = (q_el.text_content() or "").strip()
                if not question or len(question) < 5:
                    continue
                next_el = q_el.getnext()
                if next_el is not None:
                    answer = (next_el.text_content() or "").strip()[:2000]
                    if answer:
                        faqs.append(
                            {
                                "question": question[:500],
                                "answer": answer,
                                "source": "pattern_match",
                            }
                        )
        break


def _extract_meaningful_images(tree: Any, base_url: str) -> list[dict[str, Any]]:
    images: list[dict[str, Any]] = []
    if tree is None:
        return images
    for img in tree.iter("img"):
        if _is_boilerplate_ancestor(img):
            continue
        src = img.get("src") or img.get("data-src") or ""
        if not src or src.startswith("data:image/svg") or src.startswith("data:image/gif"):
            continue
        alt = (img.get("alt") or "").strip()
        width = img.get("width")
        height = img.get("height")
        try:
            w = int(re.sub(r"[^\d]", "", width)) if width else 0
            h = int(re.sub(r"[^\d]", "", height)) if height else 0
        except (ValueError, TypeError):
            w, h = 0, 0
        if w and h and (w < 20 or h < 20):
            continue
        classes = (img.get("class") or "").lower()
        if any(kw in classes for kw in ("icon", "logo", "avatar", "emoji", "badge", "spinner")):
            continue
        noise_kws = ("icon", "spinner", "pixel", "tracking", "spacer", "1x1")
        if any(kw in src.lower() for kw in noise_kws):
            continue

        abs_src = src if src.startswith(("http://", "https://")) else urljoin(base_url, src)
        images.append(
            {
                "src": abs_src,
                "alt": alt[:300] if alt else None,
                "width": w if w else None,
                "height": h if h else None,
            }
        )
        if len(images) >= 100:
            break
    return images


def _extract_important_links(tree: Any, base_url: str) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    if tree is None:
        return links
    base_host = urlsplit(base_url).hostname or ""
    main_content = tree.find(".//main")
    if main_content is None:
        main_content = tree.find('.//div[@role="main"]')
    if main_content is None:
        main_content = tree.find(".//article")
    search_root = main_content if main_content is not None else tree

    for a in search_root.iter("a"):
        href = a.get("href")
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        text = (a.text_content() or "").strip()
        if not text or len(text) < 2:
            continue
        abs_url = href if href.startswith(("http://", "https://")) else urljoin(base_url, href)
        if abs_url in seen_urls:
            continue
        seen_urls.add(abs_url)
        link_host = urlsplit(abs_url).hostname or ""
        is_internal = link_host == base_host
        links.append(
            {
                "url": abs_url,
                "text": text[:200],
                "is_internal": is_internal,
            }
        )
        if len(links) >= 200:
            break
    return links


def _extract_downloads(tree: Any, base_url: str) -> list[dict[str, Any]]:
    downloads: list[dict[str, Any]] = []
    seen: set[str] = set()
    if tree is None:
        return downloads
    for a in tree.iter("a"):
        href = a.get("href")
        if not href:
            continue
        path = urlsplit(href).path.lower()
        ext = "." + path.rsplit(".", 1)[-1] if "." in path else ""
        is_download = ext in DOWNLOAD_EXTENSIONS or a.get("download") is not None
        if not is_download:
            continue
        abs_url = href if href.startswith(("http://", "https://")) else urljoin(base_url, href)
        if abs_url in seen:
            continue
        seen.add(abs_url)
        text = (a.text_content() or "").strip()
        downloads.append(
            {
                "url": abs_url,
                "text": text[:200] if text else None,
                "file_type": ext.lstrip(".") if ext else None,
            }
        )
        if len(downloads) >= 50:
            break
    return downloads


def _extract_structured_data(raw_html: str, url: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    try:
        import extruct

        data = extruct.extract(
            raw_html,
            base_url=url,
            syntaxes=["json-ld", "opengraph", "microdata"],
            uniform=True,
        )
        if data.get("json-ld"):
            result["json_ld"] = data["json-ld"][:10]
        if data.get("opengraph"):
            result["opengraph"] = data["opengraph"][:5]
        if data.get("microdata"):
            result["microdata"] = data["microdata"][:10]
    except Exception as exc:
        logger.debug("structured_data_extraction_failed url=%s error=%s", url, exc)
    return result


def _detect_page_type(
    url: str,
    metadata: dict[str, Any],
    headings: list[dict[str, Any]],
    structured: dict[str, Any],
    faqs: list[dict[str, Any]],
    tables: list[dict[str, Any]],
) -> str:
    path = urlsplit(url).path.lower().strip("/")
    all_text = " ".join(
        [
            path.replace("-", " ").replace("/", " "),
            metadata.get("title", ""),
            metadata.get("description", ""),
        ]
    ).lower()

    json_ld = structured.get("json_ld", [])
    for item in json_ld:
        ld_type = item.get("@type", "")
        if ld_type == "Product":
            return "product"
        if ld_type in ("Article", "NewsArticle", "BlogPosting"):
            return "article"
        if ld_type == "FAQPage":
            return "faq"

    if not path or path == "/":
        return "homepage"
    if faqs:
        return "faq"
    if any(kw in all_text for kw in ("blog", "article", "post", "news")):
        return "article"
    if any(kw in all_text for kw in ("product", "price", "buy", "shop", "cart")):
        return "product"
    if any(kw in all_text for kw in ("doc", "documentation", "api", "guide", "reference")):
        return "documentation"
    if any(kw in all_text for kw in ("about", "team", "company", "who we are")):
        return "about"
    if any(kw in all_text for kw in ("contact", "get in touch", "reach us")):
        return "contact"
    if any(kw in all_text for kw in ("service", "solution", "what we do")):
        return "services"
    if any(kw in all_text for kw in ("pricing", "plan", "subscription")):
        return "pricing"
    return "general"
