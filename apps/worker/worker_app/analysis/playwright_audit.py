# ruff: noqa: E501

from typing import Any
from urllib.parse import urlsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from worker_app.analysis.errors import AnalysisFailure, FailureDetail
from worker_app.analysis.url_safety import UrlSafetyError, validate_public_url


def _classify_failed_request(
    url: str,
    failure: str,
    resource_type: str,
    main_document_url: str,
    *,
    console_errors: list[str] | None = None,
    navigation_shutting_down: bool = False,
) -> str:
    failure_lower = failure.lower()
    url_lower = url.lower()
    console_text = "\n".join(console_errors or []).lower()
    requested = urlsplit(url)
    main = urlsplit(main_document_url)
    first_party = requested.hostname == main.hostname
    mime_rejection = "mime" in console_text and (
        url_lower in console_text or requested.path.lower() in console_text
    )
    if any(
        token in url_lower
        for token in ("google-analytics", "doubleclick", "googletagmanager", "/collect?")
    ):
        return "non_critical"
    if resource_type in {"media", "video"} or any(
        token in url_lower for token in (".mp4", ".webm", "autoplay")
    ):
        return "expected_aborted" if "abort" in failure_lower else "non_critical"
    if navigation_shutting_down and ("aborted" in failure_lower or "cancelled" in failure_lower):
        return "expected_aborted"
    if resource_type == "document":
        return "critical"
    if first_party and resource_type == "script":
        return "critical"
    if first_party and resource_type == "stylesheet":
        return "critical" if mime_rejection else "warning"
    if first_party and resource_type in {"xhr", "fetch"}:
        return "critical"
    return "unknown"


def classify_failed_request(
    request: Any,
    main_document_url: str,
    *,
    console_errors: list[str] | None = None,
    navigation_shutting_down: bool = False,
) -> str:
    return _classify_failed_request(
        request.url,
        request.failure or "",
        request.resource_type,
        main_document_url,
        console_errors=console_errors,
        navigation_shutting_down=navigation_shutting_down,
    )


def normalize_failed_requests(
    failed_requests: list[dict[str, Any]],
    main_document_url: str,
    console_errors: list[str],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for request in failed_requests:
        url = str(request.get("url") or "")
        failure = str(request.get("failure") or "Request failed")
        resource_type = str(request.get("resource_type") or "other")
        related_console = [
            message[:500]
            for message in console_errors
            if url.lower() in message.lower()
            or (urlsplit(url).path and urlsplit(url).path.lower() in message.lower())
        ][:3]
        classification = _classify_failed_request(
            url,
            failure,
            resource_type,
            main_document_url,
            console_errors=related_console,
            navigation_shutting_down=bool(request.get("navigation_shutting_down")),
        )
        key = (url, classification)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(
            {
                "url": url,
                "failure": failure,
                "resource_type": resource_type,
                "first_party": urlsplit(url).hostname == urlsplit(main_document_url).hostname,
                "classification": classification,
                "console_evidence": related_console,
                "navigation_shutting_down": bool(request.get("navigation_shutting_down")),
            }
        )
    return normalized


def detect_technology(measurements: dict[str, Any]) -> dict[str, Any]:
    raw = measurements.get("technology_evidence", {})
    indicators: list[dict[str, str]] = []
    for code, value in (
        ("next_asset_path", raw.get("next_asset_path")),
        ("next_data", raw.get("next_data")),
        ("next_build_id", raw.get("next_build_id")),
        ("next_root", raw.get("next_root")),
        ("next_header", raw.get("next_header")),
    ):
        if value:
            indicators.append({"code": code, "evidence": str(value)[:200]})
    strong_codes = {"next_data", "next_build_id", "next_header"}
    strong_count = sum(item["code"] in strong_codes for item in indicators)
    path_and_marker = {"next_asset_path", "next_root"} <= {item["code"] for item in indicators}
    if strong_count or path_and_marker:
        status = "detected"
        confidence = min(100, 75 + max(0, len(indicators) - 1) * 8)
    elif indicators:
        status = "uncertain"
        confidence = 45
    else:
        status = "not_detected"
        confidence = 80
    return {
        "status": status,
        "confidence_percent": confidence,
        "indicators": indicators[:10],
        "explanation": (
            "Multiple or framework-specific Next.js indicators were verified."
            if status == "detected"
            else "A weak Next.js-related signal was observed without corroboration."
            if status == "uncertain"
            else "No verified Next.js indicators were observed in the bounded homepage inspection."
        ),
    }


def inspect_page(
    requested_url: str,
    *,
    launch_timeout_ms: int,
    navigation_timeout_ms: int,
    dom_readiness_timeout_ms: int,
    stabilization_ms: int,
    collection_timeout_ms: int,
    max_resources: int,
    responsive_viewports: list[tuple[str, int, int]],
) -> dict[str, Any]:
    safe_url = validate_public_url(requested_url)
    console_errors: list[str] = []
    page_errors: list[str] = []
    failed_requests: list[dict[str, Any]] = []
    redirect_urls: list[str] = []
    blocked_navigation: list[UrlSafetyError] = []
    resource_samples: list[dict[str, Any]] = []
    resource_sample_candidates = 0
    network_urls: list[str] = []

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True, timeout=launch_timeout_ms)
        except PlaywrightError as exception:
            raise AnalysisFailure(
                FailureDetail(
                    "BROWSER_LAUNCH_FAILED",
                    "The browser could not start.",
                    "preparing_browser",
                    True,
                    internal_detail=str(exception),
                )
            ) from exception
        try:
            context = browser.new_context(
                viewport={"width": 1440, "height": 900},
                ignore_https_errors=False,
            )
            page = context.new_page()
            page.set_default_timeout(collection_timeout_ms)
            crashed = False
            navigation_shutting_down = False

            def record_crash() -> None:
                nonlocal crashed
                crashed = True

            def validate_request(route: Any) -> None:
                if route.request.resource_type == "document":
                    try:
                        validate_public_url(route.request.url)
                    except UrlSafetyError as exception:
                        blocked_navigation.append(exception)
                        route.abort()
                        return
                route.continue_()

            page.route("**/*", validate_request)
            page.on(
                "console",
                lambda message: (
                    console_errors.append(message.text) if message.type == "error" else None
                ),
            )
            page.on("pageerror", lambda exception: page_errors.append(str(exception)))
            page.on("crash", record_crash)
            page.on(
                "requestfailed",
                lambda request: failed_requests.append(
                    {
                        "url": request.url,
                        "failure": request.failure or "Request failed",
                        "resource_type": request.resource_type,
                        "navigation_shutting_down": navigation_shutting_down,
                    }
                ),
            )

            def record_response(response: Any) -> None:
                nonlocal resource_sample_candidates
                network_urls.append(response.url)
                if response.request.resource_type == "document":
                    redirect_urls.append(response.url)
                    return
                response_url = urlsplit(response.url)
                main_url = urlsplit(safe_url)
                first_party_hosts = {
                    main_url.hostname,
                    *(urlsplit(url).hostname for url in redirect_urls),
                }
                if (
                    response_url.hostname in first_party_hosts
                    and response.request.resource_type in {"script", "stylesheet", "image", "font"}
                ):
                    resource_sample_candidates += 1
                    if len(resource_samples) >= max_resources:
                        return
                    resource_samples.append(
                        {
                            "url": response.url,
                            "resource_type": response.request.resource_type,
                            "headers": {
                                key.lower(): value for key, value in response.headers.items()
                            },
                        }
                    )

            page.on("response", record_response)
            try:
                response = page.goto(
                    safe_url, wait_until="domcontentloaded", timeout=navigation_timeout_ms
                )
                try:
                    page.wait_for_load_state("load", timeout=dom_readiness_timeout_ms)
                except PlaywrightTimeoutError:
                    pass
                if stabilization_ms:
                    page.wait_for_timeout(stabilization_ms)
            except PlaywrightTimeoutError as exception:
                if blocked_navigation:
                    raise blocked_navigation[0] from exception
                raise UrlSafetyError(
                    "NAVIGATION_TIMEOUT", "The website took too long to load."
                ) from exception
            except PlaywrightError as exception:
                if blocked_navigation:
                    raise blocked_navigation[0] from exception
                raise UrlSafetyError(
                    "MAIN_DOCUMENT_FAILED", "The website could not be loaded."
                ) from exception
            if crashed:
                raise AnalysisFailure(
                    FailureDetail(
                        "PAGE_CRASHED", "The page crashed during analysis.", "loading_website", True
                    )
                )
            if response is None or response.status >= 400:
                raise AnalysisFailure(
                    FailureDetail(
                        "MAIN_DOCUMENT_FAILED",
                        "The website could not be loaded.",
                        "loading_website",
                        response is None or response.status >= 500,
                        internal_detail=f"status={response.status if response else 'none'}",
                    )
                )
            final_url = validate_public_url(page.url)
            for redirect_url in redirect_urls:
                validate_public_url(redirect_url)
            if len(redirect_urls) > 6:
                raise UrlSafetyError(
                    "WEBSITE_UNREACHABLE", "The website redirected too many times."
                )

            try:
                measurements = page.evaluate(
                    """
                () => {
                  const links = [...document.querySelectorAll('a[href]')];
                  const origin = window.location.origin;
                  const images = [...document.images];
                  return {
                    page_title: document.title || null,
                    meta_description: document.querySelector('meta[name="description"]')?.content || null,
                    canonical_url: document.querySelector('link[rel="canonical"]')?.href || null,
                    html_language: document.documentElement.lang || null,
                    h1_texts: [...document.querySelectorAll('h1')].map((node) => node.textContent?.trim() || ''),
                    image_count: images.length,
                    images_missing_alt: images.filter((image) => !image.hasAttribute('alt') || !image.alt.trim()).length,
                    internal_link_count: links.filter((link) => { try { return new URL(link.href).origin === origin; } catch { return false; } }).length,
                    external_link_count: links.filter((link) => { try { return new URL(link.href).origin !== origin; } catch { return false; } }).length,
                    rendered_dom_links: links.map(link => link.href).filter(Boolean).slice(0, 500),
                    form_count: document.forms.length,
                    button_count: document.querySelectorAll('button, input[type="button"], input[type="submit"]').length,
                    responsive_viewport: document.documentElement.scrollWidth <= window.innerWidth,
                    technology_indicators: {
                      generator: document.querySelector('meta[name="generator"]')?.content || null,
                    },
                    technology_evidence: {
                      next_asset_path: [...document.querySelectorAll('script[src], link[href]')].map(node => node.src || node.href).find(url => /\\/_next\\//.test(url)) || null,
                      next_data: Boolean(window.__NEXT_DATA__ || document.querySelector('script#__NEXT_DATA__')),
                      next_build_id: window.__NEXT_DATA__?.buildId || document.querySelector('script#__NEXT_DATA__')?.textContent?.match(/"buildId"\\s*:\\s*"([^"]+)"/)?.[1] || null,
                      next_root: Boolean(document.querySelector('#__next')),
                    },
                    viewport_meta: document.querySelector('meta[name="viewport"]')?.content || null,
                    policy_links: Object.fromEntries(['privacy', 'terms', 'cookie'].map(kind => {
                      const link = links.find(node => (node.textContent || '').toLowerCase().includes(kind));
                      return [kind, link?.href || null];
                    })),
                    copyright_text: [...document.querySelectorAll('footer, body')].map(node => node.innerText).find(text => /(?:©|copyright).*(?:19|20)[0-9]{2}/i.test(text))?.match(/.{0,80}(?:©|copyright).{0,120}/i)?.[0] || null,
                    script_evidence: [...document.scripts].map(script => `${script.src || ''} ${script.textContent || ''}`).join('\\n').slice(0, 200000),
                    mixed_content_count: [...document.querySelectorAll('[src], link[href]')].filter(node => (node.src || node.href || '').startsWith('http://')).length,
                    consent_ui_detected: [...document.querySelectorAll('button, [role="button"]')].some(node => /accept|allow|consent|cookie/i.test(node.textContent || '')),
                  };
                }
                    """
                )
                user_agent = page.evaluate("() => navigator.userAgent")
                measurements["responsive_results"] = []
                for name, width, height in responsive_viewports:
                    try:
                        page.set_viewport_size({"width": width, "height": height})
                        viewport_result = page.evaluate(
                            """([name, width, height]) => {
                              const targets = [...document.querySelectorAll('button, a[href], input, select, textarea, [role="button"]')]
                                .map(node => ({ node, box: node.getBoundingClientRect() }))
                                .filter(item => {
                                  const style = getComputedStyle(item.node);
                                  return item.box.width > 0 && item.box.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                                });
                              const small = targets.filter(item => item.box.width < 24 || item.box.height < 24);
                              const samples = small.slice(0, 20).map(item => {
                                const padX = Math.max(0, (24 - item.box.width) / 2);
                                const padY = Math.max(0, (24 - item.box.height) / 2);
                                const expanded = { left: item.box.left - padX, right: item.box.right + padX, top: item.box.top - padY, bottom: item.box.bottom + padY };
                                const overlaps = targets.some(other => other.node !== item.node && !(other.box.right <= expanded.left || other.box.left >= expanded.right || other.box.bottom <= expanded.top || other.box.top >= expanded.bottom));
                                return {
                                  element_type: item.node.tagName.toLowerCase(),
                                  accessible_label: (item.node.getAttribute('aria-label') || item.node.getAttribute('title') || item.node.textContent || item.node.value || '').trim().slice(0, 120),
                                  width: item.box.width,
                                  height: item.box.height,
                                  spacing_exception: !overlaps,
                                };
                              });
                              return {
                                name, width, height, status: 'passed',
                                horizontal_overflow: document.documentElement.scrollWidth > width,
                                critical_elements_outside_viewport: [...document.querySelectorAll('nav, main, h1, button, input')].filter(node => { const box = node.getBoundingClientRect(); return box.right > width + 2 || box.left < -2; }).length,
                                responsive_navigation: Boolean(document.querySelector('nav, [aria-label*="navigation" i]')),
                                small_tap_targets: small.length,
                                tap_target_samples: samples,
                              };
                            }""",
                            [name, width, height],
                        )
                    except PlaywrightError:
                        viewport_result = {
                            "name": name,
                            "width": width,
                            "height": height,
                            "status": "failed",
                        }
                    measurements["responsive_results"].append(viewport_result)
                measurements["main_response_headers"] = {
                    key.lower(): value for key, value in response.headers.items()
                }
                next_header = next(
                    (
                        f"{key}: {value}"
                        for key, value in measurements["main_response_headers"].items()
                        if key in {"x-nextjs-cache", "x-powered-by"} and "next" in value.lower()
                    ),
                    None,
                )
                measurements["technology_evidence"]["next_header"] = next_header
                nextjs_detection = detect_technology(measurements)
                measurements["technology_indicators"]["nextjs_detection"] = nextjs_detection
                measurements["technology_indicators"]["nextjs"] = (
                    nextjs_detection["status"] == "detected"
                )
                measurements["resource_samples"] = resource_samples
                measurements["resource_sample_candidates"] = resource_sample_candidates
                measurements["resource_sample_limit"] = max_resources
                measurements["network_urls"] = network_urls[:200]
                measurements["_html"] = page.content()[:2_000_000]
            except PlaywrightError as exception:
                raise AnalysisFailure(
                    FailureDetail(
                        "PLAYWRIGHT_COLLECTION_FAILED",
                        "Page evidence could not be collected.",
                        "collecting_page_evidence",
                        False,
                        internal_detail=str(exception),
                    )
                ) from exception
            navigation_shutting_down = True
            context.close()
        finally:
            browser.close()

    return parse_playwright_measurements(
        measurements,
        requested_url=safe_url,
        final_url=final_url,
        http_status_code=response.status if response else None,
        user_agent=user_agent,
        console_errors=console_errors,
        page_errors=page_errors,
        failed_requests=failed_requests,
    )


def parse_playwright_measurements(
    measurements: dict[str, Any],
    *,
    requested_url: str,
    final_url: str,
    http_status_code: int | None,
    user_agent: str,
    console_errors: list[str],
    page_errors: list[str],
    failed_requests: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        **measurements,
        "requested_url": requested_url,
        "final_url": final_url,
        "http_status_code": http_status_code,
        "user_agent": user_agent,
        "console_errors": console_errors,
        "page_javascript_errors": page_errors,
        "failed_network_requests": normalize_failed_requests(
            failed_requests, final_url, console_errors
        ),
        "https_usage": urlsplit(final_url).scheme == "https",
        "h1_count": len(measurements.get("h1_texts", [])),
    }


def chromium_executable_path() -> str:
    with sync_playwright() as playwright:
        return playwright.chromium.executable_path


def normalize_playwright_error(exception: Exception) -> UrlSafetyError:
    if isinstance(exception, UrlSafetyError):
        return exception
    if isinstance(exception, PlaywrightError):
        return UrlSafetyError("PLAYWRIGHT_FAILED", "The browser inspection failed.")
    return UrlSafetyError("PLAYWRIGHT_FAILED", "The browser inspection failed.")
