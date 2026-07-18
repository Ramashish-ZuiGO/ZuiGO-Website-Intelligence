import ipaddress
import socket
from collections.abc import Callable, Iterable
from urllib.parse import urlsplit, urlunsplit


class UrlSafetyError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message


Resolver = Callable[[str, int], Iterable[tuple[object, object, object, object, tuple[object, ...]]]]


def resolve_host(
    hostname: str, port: int
) -> Iterable[tuple[object, object, object, object, tuple[object, ...]]]:
    return socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)


def is_public_ip(value: str) -> bool:
    address = ipaddress.ip_address(value)
    return address.is_global


def validate_public_url(url: str, resolver: Resolver = resolve_host) -> str:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exception:
        raise UrlSafetyError("INVALID_ANALYSIS_URL", "The website URL is invalid.") from exception

    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise UrlSafetyError("INVALID_ANALYSIS_URL", "Only valid HTTP and HTTPS URLs are allowed.")
    if parsed.username or parsed.password:
        raise UrlSafetyError("INVALID_ANALYSIS_URL", "URLs containing credentials are not allowed.")

    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise UrlSafetyError("PRIVATE_NETWORK_TARGET", "Private network targets are not allowed.")
    try:
        hostname.encode("idna")
    except UnicodeError as exception:
        raise UrlSafetyError(
            "INVALID_ANALYSIS_URL", "The website hostname is invalid."
        ) from exception

    target_port = port or (443 if parsed.scheme == "https" else 80)
    try:
        literal_address = ipaddress.ip_address(hostname)
        addresses = [literal_address]
    except ValueError:
        try:
            resolved = resolver(hostname, target_port)
        except OSError as exception:
            raise UrlSafetyError(
                "DNS_RESOLUTION_FAILED", "The website hostname could not be resolved."
            ) from exception
        addresses = []
        for item in resolved:
            try:
                addresses.append(ipaddress.ip_address(str(item[4][0])))
            except (IndexError, ValueError):
                continue

    if not addresses:
        raise UrlSafetyError("DNS_RESOLUTION_FAILED", "The website hostname could not be resolved.")
    if any(not address.is_global for address in addresses):
        raise UrlSafetyError("PRIVATE_NETWORK_TARGET", "Private network targets are not allowed.")

    netloc = hostname
    if ":" in hostname:
        netloc = f"[{hostname}]"
    if port is not None:
        netloc = f"{netloc}:{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path or "/", parsed.query, ""))


def validate_redirect_chain(urls: Iterable[str], resolver: Resolver = resolve_host) -> list[str]:
    validated = [validate_public_url(url, resolver) for url in urls]
    if len(validated) > 6:
        raise UrlSafetyError("WEBSITE_UNREACHABLE", "The website redirected too many times.")
    return validated
