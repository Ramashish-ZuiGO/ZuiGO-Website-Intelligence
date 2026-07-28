import ipaddress
import re
import socket
from collections.abc import Callable, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class PublicURLSafetyError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message


Resolver = Callable[[str, int], Iterable[tuple[object, object, object, object, tuple[object, ...]]]]
SENSITIVE_QUERY_PATTERN = re.compile(
    r"(?:^|_)(?:api_?key|auth|authorization|credential|password|secret|session|signature|token)(?:$|_)",
    re.IGNORECASE,
)
CLOUD_METADATA_HOSTS = {
    "instance-data",
    "metadata",
    "metadata.azure.internal",
    "metadata.google.internal",
}


def resolve_host(
    hostname: str,
    port: int,
) -> Iterable[tuple[object, object, object, object, tuple[object, ...]]]:
    return socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)


def _with_default_scheme(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise PublicURLSafetyError(
            "INVALID_WEBSITE_URL",
            "Enter a website URL.",
        )
    return normalized if "://" in normalized else f"https://{normalized}"


def validate_and_normalize_public_url(
    value: str,
    resolver: Resolver = resolve_host,
) -> str:
    raw_url = _with_default_scheme(value)
    try:
        parsed = urlsplit(raw_url)
        port = parsed.port
    except ValueError as exception:
        raise PublicURLSafetyError(
            "INVALID_WEBSITE_URL",
            "Enter a valid public website URL.",
        ) from exception
    scheme = parsed.scheme.casefold()
    if scheme not in {"http", "https"} or not parsed.hostname:
        raise PublicURLSafetyError(
            "INVALID_WEBSITE_URL",
            "Only public HTTP and HTTPS website URLs are supported.",
        )
    if parsed.username or parsed.password:
        raise PublicURLSafetyError(
            "INVALID_WEBSITE_URL",
            "Website URLs cannot contain usernames or passwords.",
        )
    hostname = parsed.hostname.rstrip(".").casefold()
    if (
        hostname == "localhost"
        or hostname.endswith(".localhost")
        or hostname in CLOUD_METADATA_HOSTS
        or hostname.endswith(".internal")
        or hostname.endswith(".local")
    ):
        raise PublicURLSafetyError(
            "PRIVATE_NETWORK_TARGET",
            "Local, private, and cloud-metadata addresses cannot be analysed.",
        )
    try:
        hostname = hostname.encode("idna").decode("ascii")
    except UnicodeError as exception:
        raise PublicURLSafetyError(
            "INVALID_WEBSITE_URL",
            "The website hostname is invalid.",
        ) from exception
    if any(SENSITIVE_QUERY_PATTERN.search(key) for key, _value in parse_qsl(parsed.query)):
        raise PublicURLSafetyError(
            "SENSITIVE_WEBSITE_URL",
            "Remove secret, session, authentication, or token parameters from the URL.",
        )

    target_port = port or (443 if scheme == "https" else 80)
    try:
        addresses = [ipaddress.ip_address(hostname)]
    except ValueError:
        try:
            resolved = resolver(hostname, target_port)
        except OSError as exception:
            raise PublicURLSafetyError(
                "DNS_RESOLUTION_FAILED",
                "The website hostname could not be resolved.",
            ) from exception
        addresses = []
        for item in resolved:
            try:
                addresses.append(ipaddress.ip_address(str(item[4][0])))
            except (IndexError, ValueError):
                continue
    if not addresses:
        raise PublicURLSafetyError(
            "DNS_RESOLUTION_FAILED",
            "The website hostname could not be resolved.",
        )
    if any(not address.is_global for address in addresses):
        raise PublicURLSafetyError(
            "PRIVATE_NETWORK_TARGET",
            "Local, private, and cloud-metadata addresses cannot be analysed.",
        )

    if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        port = None
    netloc = f"[{hostname}]" if ":" in hostname else hostname
    if port is not None:
        netloc = f"{netloc}:{port}"
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query = urlencode(parse_qsl(parsed.query, keep_blank_values=True), doseq=True)
    return urlunsplit((scheme, netloc, path, query, ""))


def validate_public_redirects(
    urls: Iterable[str],
    resolver: Resolver = resolve_host,
    *,
    maximum_redirects: int = 5,
) -> list[str]:
    values = list(urls)
    if len(values) > maximum_redirects + 1:
        raise PublicURLSafetyError(
            "REDIRECT_LIMIT_EXCEEDED",
            "The website redirected too many times.",
        )
    return [validate_and_normalize_public_url(item, resolver) for item in values]
