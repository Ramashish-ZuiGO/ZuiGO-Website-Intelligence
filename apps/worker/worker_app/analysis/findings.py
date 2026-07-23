from typing import Any

PERFORMANCE_SCORE_THRESHOLD = 50
QUALITY_SCORE_THRESHOLD = 90
LCP_POOR_MS = 4000
LCP_NEEDS_IMPROVEMENT_MS = 2500
CLS_POOR = 0.25
CLS_NEEDS_IMPROVEMENT = 0.1
TBT_POOR_MS = 600
TBT_NEEDS_IMPROVEMENT_MS = 200


def finding(
    code: str,
    category: str,
    title: str,
    description: str,
    severity: str,
    affected_url: str,
    evidence: dict[str, Any],
    source: str,
) -> dict[str, Any]:
    return {
        "finding_code": code,
        "category": category,
        "title": title,
        "description": description,
        "severity": severity,
        "affected_url": affected_url,
        "evidence": evidence,
        "source": source,
        "confidence_percent": 100,
    }


def generate_findings(
    playwright_data: dict[str, Any], lighthouse_metrics: dict[str, Any]
) -> list[dict[str, Any]]:
    url = str(playwright_data["final_url"])
    results: list[dict[str, Any]] = []
    failed_requests = playwright_data.get("failed_network_requests", [])
    css_mime_failures = [
        request
        for request in failed_requests
        if request.get("resource_type") == "stylesheet"
        and request.get("first_party")
        and any("mime" in str(message).lower() for message in request.get("console_evidence", []))
    ]
    script_failures = [
        request
        for request in failed_requests
        if request.get("resource_type") == "script"
        and request.get("first_party")
        and request.get("classification") == "critical"
    ]
    handled_request_urls = {
        str(request.get("url")) for request in [*css_mime_failures, *script_failures]
    }
    actionable_request_failures = [
        request
        for request in failed_requests
        if request.get("classification") in {"critical", "warning", "unknown", None}
        and str(request.get("url")) not in handled_request_urls
    ]

    direct_rules = [
        (
            not playwright_data.get("page_title"),
            "MISSING_PAGE_TITLE",
            "seo",
            "Missing page title",
            "The homepage has no page title.",
            "high",
            {"page_title": playwright_data.get("page_title")},
        ),
        (
            not playwright_data.get("meta_description"),
            "MISSING_META_DESCRIPTION",
            "seo",
            "Missing meta description",
            "The homepage has no meta description.",
            "medium",
            {"meta_description": playwright_data.get("meta_description")},
        ),
        (
            not playwright_data.get("canonical_url"),
            "MISSING_CANONICAL_URL",
            "seo",
            "Missing canonical URL",
            "The homepage has no canonical link.",
            "medium",
            {"canonical_url": playwright_data.get("canonical_url")},
        ),
        (
            not playwright_data.get("html_language"),
            "MISSING_HTML_LANGUAGE",
            "accessibility",
            "Missing HTML language",
            "The HTML document has no language declaration.",
            "medium",
            {"html_language": playwright_data.get("html_language")},
        ),
        (
            playwright_data.get("h1_count") == 0,
            "MISSING_H1",
            "seo",
            "Missing H1 heading",
            "The homepage has no H1 heading.",
            "medium",
            {"h1_count": playwright_data.get("h1_count")},
        ),
        (
            (playwright_data.get("h1_count") or 0) > 1,
            "MULTIPLE_H1",
            "seo",
            "Multiple H1 headings",
            "The homepage contains multiple H1 headings.",
            "low",
            {"h1_count": playwright_data.get("h1_count")},
        ),
        (
            (playwright_data.get("images_missing_alt") or 0) > 0,
            "IMAGES_MISSING_ALT",
            "accessibility",
            "Images missing alternative text",
            "One or more images have no useful alt text.",
            "medium",
            {
                "images_missing_alt": playwright_data.get("images_missing_alt"),
                "image_count": playwright_data.get("image_count"),
            },
        ),
        (
            bool(playwright_data.get("page_javascript_errors")),
            "JAVASCRIPT_RUNTIME_ERRORS",
            "technical",
            "JavaScript runtime errors",
            "The page emitted JavaScript runtime errors.",
            "high",
            {"errors": playwright_data.get("page_javascript_errors")},
        ),
        (
            not playwright_data.get("https_usage"),
            "NON_HTTPS_WEBSITE",
            "security",
            "Website is not using HTTPS",
            "The analyzed homepage was delivered without HTTPS.",
            "high",
            {"https_usage": playwright_data.get("https_usage")},
        ),
    ]
    for matched, code, category, title, description, severity, evidence in direct_rules:
        if matched:
            results.append(
                finding(code, category, title, description, severity, url, evidence, "playwright")
            )

    request_rules = [
        (
            css_mime_failures,
            "CSS_MIME_TYPE_FAILURE",
            "Stylesheet rejected because of its response content type",
            "A first-party stylesheet was rejected by Chromium because its MIME type was invalid.",
            "high",
        ),
        (
            script_failures,
            "FIRST_PARTY_JAVASCRIPT_FAILURE",
            "First-party rendering JavaScript failed",
            "A first-party script required by the page failed to load.",
            "critical",
        ),
        (
            actionable_request_failures,
            "FAILED_NETWORK_REQUESTS",
            "Failed network requests",
            "One or more actionable page requests failed.",
            "medium",
        ),
    ]
    for requests, code, title, description, severity in request_rules:
        if requests:
            results.append(
                finding(
                    code,
                    "technical",
                    title,
                    description,
                    severity,
                    url,
                    {"requests": requests[:20]},
                    "playwright",
                )
            )

    score_rules = [
        (
            "performance_score",
            PERFORMANCE_SCORE_THRESHOLD,
            "POOR_LIGHTHOUSE_PERFORMANCE",
            "performance",
            "Poor Lighthouse performance score",
        ),
        (
            "accessibility_score",
            QUALITY_SCORE_THRESHOLD,
            "POOR_LIGHTHOUSE_ACCESSIBILITY",
            "accessibility",
            "Poor Lighthouse accessibility score",
        ),
        (
            "seo_score",
            QUALITY_SCORE_THRESHOLD,
            "POOR_LIGHTHOUSE_SEO",
            "seo",
            "Poor Lighthouse SEO score",
        ),
        (
            "best_practices_score",
            QUALITY_SCORE_THRESHOLD,
            "POOR_LIGHTHOUSE_BEST_PRACTICES",
            "technical",
            "Poor Lighthouse best-practices score",
        ),
    ]
    for key, threshold, code, category, title in score_rules:
        value = lighthouse_metrics.get(key)
        if isinstance(value, (int, float)) and value < threshold:
            results.append(
                finding(
                    code,
                    category,
                    title,
                    f"The measured score is below {threshold}.",
                    "medium",
                    url,
                    {"score": value, "threshold": threshold},
                    "lighthouse",
                )
            )

    metric_rules = [
        (
            "largest_contentful_paint_ms",
            LCP_NEEDS_IMPROVEMENT_MS,
            LCP_POOR_MS,
            "HIGH_LCP",
            "Largest Contentful Paint is high",
        ),
        (
            "cumulative_layout_shift",
            CLS_NEEDS_IMPROVEMENT,
            CLS_POOR,
            "HIGH_CLS",
            "Cumulative Layout Shift is high",
        ),
        (
            "total_blocking_time_ms",
            TBT_NEEDS_IMPROVEMENT_MS,
            TBT_POOR_MS,
            "HIGH_TOTAL_BLOCKING_TIME",
            "Total Blocking Time is high",
        ),
    ]
    for key, medium_threshold, high_threshold, code, title in metric_rules:
        value = lighthouse_metrics.get(key)
        if isinstance(value, (int, float)) and value > medium_threshold:
            severity = "high" if value > high_threshold else "medium"
            metric_evidence: dict[str, Any] = {
                "value": value,
                "threshold": medium_threshold,
            }
            performance_evidence = lighthouse_metrics.get("performance_evidence")
            if isinstance(performance_evidence, dict):
                if code == "HIGH_LCP":
                    metric_evidence.update(
                        {
                            "lcp_element": performance_evidence.get("lcp_element"),
                            "render_blocking_resources": performance_evidence.get(
                                "render_blocking_resources", []
                            ),
                        }
                    )
                elif code == "HIGH_TOTAL_BLOCKING_TIME":
                    metric_evidence.update(
                        {
                            "long_tasks": performance_evidence.get("long_tasks", []),
                            "main_thread_work": performance_evidence.get("main_thread_work", []),
                            "script_execution": performance_evidence.get("script_execution", []),
                        }
                    )
            results.append(
                finding(
                    code,
                    "performance",
                    title,
                    "The measured value exceeds the documented threshold.",
                    severity,
                    url,
                    metric_evidence,
                    "lighthouse",
                )
            )

    return results
