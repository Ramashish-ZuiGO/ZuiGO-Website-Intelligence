from collections.abc import Iterable

from app.services.public_url_safety import (
    PublicURLSafetyError,
    Resolver,
    resolve_host,
    validate_and_normalize_public_url,
    validate_public_redirects,
)

UrlSafetyError = PublicURLSafetyError


def validate_public_url(url: str, resolver: Resolver = resolve_host) -> str:
    try:
        return validate_and_normalize_public_url(url, resolver)
    except PublicURLSafetyError as exception:
        if exception.code == "INVALID_WEBSITE_URL":
            exception.code = "INVALID_ANALYSIS_URL"
        raise


def validate_redirect_chain(urls: Iterable[str], resolver: Resolver = resolve_host) -> list[str]:
    try:
        return validate_public_redirects(urls, resolver, maximum_redirects=5)
    except PublicURLSafetyError as exception:
        if exception.code == "REDIRECT_LIMIT_EXCEEDED":
            exception.code = "WEBSITE_UNREACHABLE"
        raise
