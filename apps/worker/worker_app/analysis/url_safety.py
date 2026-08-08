import ipaddress
import socket
import ssl
from collections.abc import Iterable
from http.client import HTTPConnection, HTTPSConnection
from urllib.parse import urlsplit

from app.services.public_url_safety import (
    PublicURLSafetyError,
    Resolver,
    _resolve_and_filter_global,
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


def resolve_validated_global_ips(
    hostname: str,
    port: int,
    resolver: Resolver = resolve_host,
) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    return _resolve_and_filter_global(hostname, port, resolver)


class SafeConnectionFactory:
    """Create HTTP(S) connections pinned to validated global IPs.

    Resolves DNS through our safety layer and connects the underlying
    socket to a validated global address.  For HTTPS the TLS certificate
    is verified against the original hostname (SNI), not the IP literal,
    so legitimate certificates pass while DNS rebinding is blocked.
    """

    def __init__(self, resolver: Resolver = resolve_host) -> None:
        self._resolver = resolver

    def open(
        self,
        url: str,
        *,
        timeout: float = 15.0,
        method: str = "GET",
        headers: dict[str, str] | None = None,
    ) -> tuple[HTTPConnection, str]:
        """Return ``(connection, validated_url)`` with a ready-to-read response.

        The caller must close the connection.
        """
        validated = validate_public_url(url, self._resolver)
        parsed = urlsplit(validated)
        scheme = parsed.scheme
        hostname = parsed.hostname or ""
        port = parsed.port or (443 if scheme == "https" else 80)

        global_ips = resolve_validated_global_ips(hostname, port, self._resolver)
        target_ip = str(global_ips[0])

        raw_sock = socket.create_connection((target_ip, port), timeout=timeout)
        try:
            if scheme == "https":
                context = ssl.create_default_context()
                sock = context.wrap_socket(raw_sock, server_hostname=hostname)
            else:
                sock = raw_sock
        except BaseException:
            raw_sock.close()
            raise

        if scheme == "https":
            conn = HTTPSConnection(hostname, port)
        else:
            conn = HTTPConnection(hostname, port)
        conn.sock = sock
        conn.timeout = timeout

        request_headers = {"Host": hostname, **(headers or {})}
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        conn.request(method, path, headers=request_headers)
        return conn, validated
