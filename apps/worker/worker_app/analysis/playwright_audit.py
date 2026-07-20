# ruff: noqa: E501

from typing import Any
from urllib.parse import urlsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from worker_app.analysis.errors import AnalysisFailure, FailureDetail
from worker_app.analysis.url_safety import UrlSafetyError, validate_public_url


def classify_failed_request(request: Any, main_document_url: str) -> str:
    failure = (request.failure or "").lower()
    if "aborted" in failure or "cancelled" in failure:
        return "expected_aborted"
    url = request.url.lower()
    if any(token in url for token in ("analytics", "doubleclick", "googletagmanager", "video")):
        return "non_critical"
    requested = urlsplit(request.url)
    main = urlsplit(main_document_url)
    if request.resource_type == "document" or (
        requested.netloc == main.netloc
        and request.resource_type in {"script", "stylesheet", "xhr", "fetch"}
    ):
        return "critical"
    return "unknown"


def inspect_page(
    requested_url: str,
    *,
    launch_timeout_ms: int,
    navigation_timeout_ms: int,
    dom_readiness_timeout_ms: int,
    stabilization_ms: int,
    collection_timeout_ms: int,
) -> dict[str, Any]:
    safe_url = validate_public_url(requested_url)
    console_errors: list[str] = []
    page_errors: list[str] = []
    failed_requests: list[dict[str, str]] = []
    redirect_urls: list[str] = []
    blocked_navigation: list[UrlSafetyError] = []

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
                        "classification": classify_failed_request(request, safe_url),
                    }
                ),
            )
            page.on(
                "response",
                lambda response: (
                    redirect_urls.append(response.url)
                    if response.request.resource_type == "document"
                    else None
                ),
            )
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
                    form_count: document.forms.length,
                    button_count: document.querySelectorAll('button, input[type="button"], input[type="submit"]').length,
                    responsive_viewport: document.documentElement.scrollWidth <= window.innerWidth,
                    technology_indicators: {
                      generator: document.querySelector('meta[name="generator"]')?.content || null,
                      nextjs: Boolean(document.querySelector('#__next') || window.__NEXT_DATA__),
                    },
                  };
                }
                    """
                )
                user_agent = page.evaluate("() => navigator.userAgent")
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
    failed_requests: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        **measurements,
        "requested_url": requested_url,
        "final_url": final_url,
        "http_status_code": http_status_code,
        "user_agent": user_agent,
        "console_errors": console_errors,
        "page_javascript_errors": page_errors,
        "failed_network_requests": failed_requests,
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
