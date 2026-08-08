import socket
from unittest.mock import ANY, MagicMock, patch

import pytest
from app.services.public_url_safety import (
    PublicURLSafetyError,
    preflight_reachability,
    validate_and_normalize_public_url,
    validate_public_redirects,
)


def _global_resolver(hostname: str, port: int):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]


def _private_resolver(hostname: str, port: int):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", port))]


def _mixed_global_and_linklocal_resolver(hostname: str, port: int):
    return [
        (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("fe80::1", port, 0, 0)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
    ]


def _mixed_global_and_private_resolver(hostname: str, port: int):
    return [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.1", port)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
    ]


def _all_private_resolver(hostname: str, port: int):
    return [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", port)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.1", port)),
        (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("fe80::1", port, 0, 0)),
    ]


def _loopback_resolver(hostname: str, port: int):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]


def _empty_resolver(hostname: str, port: int):
    return []


def _failing_resolver(hostname: str, port: int):
    raise OSError("Name or service not known")


# --- DNS / IP classification ---


class TestMixedDnsResults:
    def test_global_ipv4_with_linklocal_ipv6_is_accepted(self) -> None:
        result = validate_and_normalize_public_url(
            "https://example.com", _mixed_global_and_linklocal_resolver
        )
        assert result == "https://example.com/"

    def test_global_ipv4_with_private_ipv4_is_accepted(self) -> None:
        result = validate_and_normalize_public_url(
            "https://example.com", _mixed_global_and_private_resolver
        )
        assert result == "https://example.com/"

    def test_all_private_addresses_are_rejected(self) -> None:
        with pytest.raises(PublicURLSafetyError) as captured:
            validate_and_normalize_public_url("https://example.com", _all_private_resolver)
        assert captured.value.code == "PRIVATE_NETWORK_TARGET"

    def test_loopback_only_is_rejected(self) -> None:
        with pytest.raises(PublicURLSafetyError) as captured:
            validate_and_normalize_public_url("https://example.com", _loopback_resolver)
        assert captured.value.code == "PRIVATE_NETWORK_TARGET"

    def test_all_global_addresses_are_accepted(self) -> None:
        result = validate_and_normalize_public_url("https://example.com", _global_resolver)
        assert result == "https://example.com/"


class TestDnsResolution:
    def test_dns_failure_raises_specific_code(self) -> None:
        with pytest.raises(PublicURLSafetyError) as captured:
            validate_and_normalize_public_url("https://nonexistent.example", _failing_resolver)
        assert captured.value.code == "DNS_RESOLUTION_FAILED"
        assert "resolve" in captured.value.safe_message.lower()

    def test_empty_dns_result_raises_specific_code(self) -> None:
        with pytest.raises(PublicURLSafetyError) as captured:
            validate_and_normalize_public_url("https://empty.example", _empty_resolver)
        assert captured.value.code == "DNS_RESOLUTION_FAILED"

    def test_ip_literal_loopback_rejected(self) -> None:
        with pytest.raises(PublicURLSafetyError) as captured:
            validate_and_normalize_public_url("http://127.0.0.1", _global_resolver)
        assert captured.value.code == "PRIVATE_NETWORK_TARGET"

    def test_ip_literal_private_rejected(self) -> None:
        with pytest.raises(PublicURLSafetyError) as captured:
            validate_and_normalize_public_url("http://10.0.0.1", _global_resolver)
        assert captured.value.code == "PRIVATE_NETWORK_TARGET"


# --- Hostname blocklist ---


class TestHostnameBlocklist:
    @pytest.mark.parametrize(
        "url",
        [
            "http://localhost",
            "http://sub.localhost",
            "http://metadata.google.internal",
            "http://anything.internal",
            "http://myhost.local",
        ],
    )
    def test_blocked_hosts_rejected(self, url: str) -> None:
        with pytest.raises(PublicURLSafetyError) as captured:
            validate_and_normalize_public_url(url, _global_resolver)
        assert captured.value.code == "PRIVATE_NETWORK_TARGET"


# --- Scheme and credential checks ---


class TestSchemeAndCredentials:
    def test_ftp_rejected(self) -> None:
        with pytest.raises(PublicURLSafetyError) as captured:
            validate_and_normalize_public_url("ftp://example.com", _global_resolver)
        assert captured.value.code == "INVALID_WEBSITE_URL"

    def test_credentials_rejected(self) -> None:
        with pytest.raises(PublicURLSafetyError) as captured:
            validate_and_normalize_public_url("https://user:pass@example.com", _global_resolver)
        assert captured.value.code == "INVALID_WEBSITE_URL"

    def test_sensitive_query_rejected(self) -> None:
        with pytest.raises(PublicURLSafetyError) as captured:
            validate_and_normalize_public_url(
                "https://example.com/?access_token=secret", _global_resolver
            )
        assert captured.value.code == "SENSITIVE_WEBSITE_URL"


# --- Normalization ---


class TestNormalization:
    def test_default_scheme_prepended(self) -> None:
        result = validate_and_normalize_public_url("example.com", _global_resolver)
        assert result == "https://example.com/"

    def test_default_port_stripped(self) -> None:
        result = validate_and_normalize_public_url("https://example.com:443/", _global_resolver)
        assert result == "https://example.com/"

    def test_double_slashes_collapsed(self) -> None:
        result = validate_and_normalize_public_url(
            "https://example.com//path//to//page", _global_resolver
        )
        assert result == "https://example.com/path/to/page"

    def test_trailing_slash_stripped_except_root(self) -> None:
        assert (
            validate_and_normalize_public_url("https://example.com/page/", _global_resolver)
            == "https://example.com/page"
        )
        assert (
            validate_and_normalize_public_url("https://example.com/", _global_resolver)
            == "https://example.com/"
        )

    def test_fragment_dropped(self) -> None:
        result = validate_and_normalize_public_url(
            "https://example.com/page#section", _global_resolver
        )
        assert result == "https://example.com/page"

    def test_case_normalized(self) -> None:
        result = validate_and_normalize_public_url("HTTPS://EXAMPLE.COM/Page", _global_resolver)
        assert result == "https://example.com/Page"


# --- Redirect validation ---


class TestRedirectValidation:
    def test_valid_redirect_chain(self) -> None:
        result = validate_public_redirects(
            ["http://example.com", "https://example.com/final"], _global_resolver
        )
        assert result == ["http://example.com/", "https://example.com/final"]

    def test_excessive_redirects_rejected(self) -> None:
        with pytest.raises(PublicURLSafetyError, match="too many"):
            validate_public_redirects(["https://example.com"] * 7, _global_resolver)


# --- Preflight reachability ---


_PATCH_TARGET = "app.services.public_url_safety.create_validated_socket"


class TestPreflightReachability:
    def test_tls_error_raises_specific_code(self) -> None:
        import ssl

        err = ssl.SSLCertVerificationError("certificate verify failed")
        with patch(_PATCH_TARGET, side_effect=err):
            with pytest.raises(PublicURLSafetyError) as captured:
                preflight_reachability("https://bad-cert.example.com/")
            assert captured.value.code == "WEBSITE_TLS_ERROR"
            assert "invalid or expired" in captured.value.safe_message

    def test_ssl_error_raises_specific_code(self) -> None:
        import ssl

        with patch(_PATCH_TARGET, side_effect=ssl.SSLError("SSL handshake failed")):
            with pytest.raises(PublicURLSafetyError) as captured:
                preflight_reachability("https://ssl-broken.example.com/")
            assert captured.value.code == "WEBSITE_TLS_ERROR"

    def test_connection_refused_raises_specific_code(self) -> None:
        with patch(_PATCH_TARGET, side_effect=ConnectionRefusedError("Connection refused")):
            with pytest.raises(PublicURLSafetyError) as captured:
                preflight_reachability("https://refused.example.com/")
            assert captured.value.code == "WEBSITE_CONNECTION_REFUSED"

    def test_timeout_raises_specific_code(self) -> None:
        with patch(_PATCH_TARGET, side_effect=TimeoutError("timed out")):
            with pytest.raises(PublicURLSafetyError) as captured:
                preflight_reachability("https://slow.example.com/")
            assert captured.value.code == "WEBSITE_TIMEOUT"

    def test_generic_network_error_raises_unreachable(self) -> None:
        with patch(_PATCH_TARGET, side_effect=OSError("Network is unreachable")):
            with pytest.raises(PublicURLSafetyError) as captured:
                preflight_reachability("https://unreachable.example.com/")
            assert captured.value.code == "WEBSITE_UNREACHABLE"

    def test_safety_error_propagates(self) -> None:
        err = PublicURLSafetyError("PRIVATE_NETWORK_TARGET", "blocked")
        with patch(_PATCH_TARGET, side_effect=err):
            with pytest.raises(PublicURLSafetyError) as captured:
                preflight_reachability("https://evil.example.com/")
            assert captured.value.code == "PRIVATE_NETWORK_TARGET"

    def test_successful_preflight_passes(self) -> None:
        mock_sock = MagicMock()
        with patch(_PATCH_TARGET, return_value=mock_sock):
            preflight_reachability("https://healthy.example.com/")
        mock_sock.close.assert_called_once()

    def test_http_scheme_passes_correct_args(self) -> None:
        mock_sock = MagicMock()
        with patch(_PATCH_TARGET, return_value=mock_sock) as mock_create:
            preflight_reachability("http://example.com/")
        mock_create.assert_called_once_with(
            "example.com",
            80,
            scheme="http",
            resolver=ANY,
            timeout=ANY,
        )

    def test_https_scheme_passes_correct_args(self) -> None:
        mock_sock = MagicMock()
        with patch(_PATCH_TARGET, return_value=mock_sock) as mock_create:
            preflight_reachability("https://example.com/")
        mock_create.assert_called_once_with(
            "example.com",
            443,
            scheme="https",
            resolver=ANY,
            timeout=ANY,
        )

    def test_custom_port_preserved(self) -> None:
        mock_sock = MagicMock()
        with patch(_PATCH_TARGET, return_value=mock_sock) as mock_create:
            preflight_reachability("https://example.com:8443/")
        mock_create.assert_called_once_with(
            "example.com",
            8443,
            scheme="https",
            resolver=ANY,
            timeout=ANY,
        )
