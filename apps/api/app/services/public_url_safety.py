import ipaddress
import re
import socket
import ssl
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
DNS_TIMEOUT_SECONDS = 10.0
PREFLIGHT_TIMEOUT_SECONDS = 15.0


def resolve_host(
    hostname: str,
    port: int,
) -> Iterable[tuple[object, object, object, object, tuple[object, ...]]]:
    previous_timeout = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(DNS_TIMEOUT_SECONDS)
        return socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    finally:
        socket.setdefaulttimeout(previous_timeout)


def _with_default_scheme(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise PublicURLSafetyError(
            "INVALID_WEBSITE_URL",
            "Enter a website URL.",
        )
    return normalized if "://" in normalized else f"https://{normalized}"


def _resolve_and_filter_global(
    hostname: str,
    port: int,
    resolver: Resolver,
) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None
    if literal is not None:
        if not literal.is_global:
            raise PublicURLSafetyError(
                "PRIVATE_NETWORK_TARGET",
                "This URL resolves to a private or restricted network address "
                "and cannot be analysed.",
            )
        return [literal]
    try:
        resolved = resolver(hostname, port)
    except OSError as exception:
        raise PublicURLSafetyError(
            "DNS_RESOLUTION_FAILED",
            "Could not resolve the website hostname.",
        ) from exception
    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for item in resolved:
        try:
            addresses.append(ipaddress.ip_address(str(item[4][0])))
        except (IndexError, ValueError):
            continue
    if not addresses:
        raise PublicURLSafetyError(
            "DNS_RESOLUTION_FAILED",
            "Could not resolve the website hostname.",
        )
    global_addresses = [address for address in addresses if address.is_global]
    if not global_addresses:
        raise PublicURLSafetyError(
            "PRIVATE_NETWORK_TARGET",
            "This URL resolves to a private or restricted network address and cannot be analysed.",
        )
    return global_addresses


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
            "This URL resolves to a private or restricted network address and cannot be analysed.",
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
    _resolve_and_filter_global(hostname, target_port, resolver)

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


def create_validated_socket(
    hostname: str,
    port: int,
    *,
    scheme: str = "https",
    resolver: Resolver = resolve_host,
    timeout: float = PREFLIGHT_TIMEOUT_SECONDS,
) -> socket.socket:
    """Resolve DNS, validate all addresses, connect to a validated global IP.

    Returns a connected socket (TLS-wrapped for https) whose peer is
    guaranteed to be one of the validated global addresses.  The TLS
    certificate is verified against *hostname* (SNI), not the IP literal.
    """
    global_addresses = _resolve_and_filter_global(hostname, port, resolver)
    target_ip = str(global_addresses[0])
    raw_sock = socket.create_connection((target_ip, port), timeout=timeout)
    if scheme == "https":
        context = ssl.create_default_context()
        try:
            return context.wrap_socket(raw_sock, server_hostname=hostname)
        except BaseException:
            raw_sock.close()
            raise
    return raw_sock


def preflight_reachability(
    normalized_url: str,
    resolver: Resolver = resolve_host,
) -> None:
    """Non-blocking best-effort reachability check with IP-pinned connection.

    Connects to a validated global IP (no second DNS lookup).
    Raises ``PublicURLSafetyError`` only for genuine network / TLS failures
    — never for HTTP status codes, because HEAD support is not a requirement
    for analysis.
    """
    parsed = urlsplit(normalized_url)
    scheme = parsed.scheme
    hostname = parsed.hostname or ""
    port = parsed.port or (443 if scheme == "https" else 80)
    try:
        sock = create_validated_socket(
            hostname,
            port,
            scheme=scheme,
            resolver=resolver,
            timeout=PREFLIGHT_TIMEOUT_SECONDS,
        )
        sock.close()
    except PublicURLSafetyError:
        raise
    except ssl.SSLCertVerificationError as exception:
        raise PublicURLSafetyError(
            "WEBSITE_TLS_ERROR",
            "A secure connection to the website could not be established "
            "(invalid or expired certificate).",
        ) from exception
    except ssl.SSLError as exception:
        raise PublicURLSafetyError(
            "WEBSITE_TLS_ERROR",
            "A secure connection to the website could not be established.",
        ) from exception
    except ConnectionRefusedError as exception:
        raise PublicURLSafetyError(
            "WEBSITE_CONNECTION_REFUSED",
            "The website could not be reached from the analysis environment.",
        ) from exception
    except TimeoutError as exception:
        raise PublicURLSafetyError(
            "WEBSITE_TIMEOUT",
            "The website did not respond within the connection timeout.",
        ) from exception
    except OSError as exception:
        raise PublicURLSafetyError(
            "WEBSITE_UNREACHABLE",
            "The website could not be reached from the analysis environment.",
        ) from exception
