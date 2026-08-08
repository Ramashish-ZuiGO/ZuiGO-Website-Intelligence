"""Security edge-case tests for URL safety and SSRF protection.

Covers: DNS rebinding simulation, redirect-to-private, mixed DNS results,
global-only IPv6, reserved/special addresses, IP literal bypass, and
connection-pinning verification.
"""

import ipaddress
import socket
import ssl
from unittest.mock import MagicMock, patch

import pytest
from app.services.public_url_safety import (
    PublicURLSafetyError,
    _resolve_and_filter_global,
    create_validated_socket,
    validate_and_normalize_public_url,
)

# ---------------------------------------------------------------------------
# Resolver fixtures
# ---------------------------------------------------------------------------


def _resolver_for(*addrs):
    """Build a resolver returning the given IP strings as AF_INET/AF_INET6."""

    def resolver(hostname, port):
        results = []
        for addr in addrs:
            ip = ipaddress.ip_address(addr)
            if ip.version == 4:
                results.append((socket.AF_INET, socket.SOCK_STREAM, 6, "", (addr, port)))
            else:
                results.append((socket.AF_INET6, socket.SOCK_STREAM, 6, "", (addr, port, 0, 0)))
        return results

    return resolver


def _rebinding_resolver(first_addrs, second_addrs):
    """Simulate DNS rebinding: first call returns first_addrs, then second_addrs."""
    call_count = {"n": 0}

    def resolver(hostname, port):
        call_count["n"] += 1
        addrs = first_addrs if call_count["n"] == 1 else second_addrs
        results = []
        for addr in addrs:
            ip = ipaddress.ip_address(addr)
            if ip.version == 4:
                results.append((socket.AF_INET, socket.SOCK_STREAM, 6, "", (addr, port)))
            else:
                results.append((socket.AF_INET6, socket.SOCK_STREAM, 6, "", (addr, port, 0, 0)))
        return results

    return resolver


# ---------------------------------------------------------------------------
# DNS classification edge cases
# ---------------------------------------------------------------------------


class TestDnsClassificationEdgeCases:
    def test_global_ipv4_only_accepted(self):
        result = validate_and_normalize_public_url(
            "https://example.com", _resolver_for("93.184.216.34")
        )
        assert result == "https://example.com/"

    def test_global_ipv6_only_accepted(self):
        result = validate_and_normalize_public_url(
            "https://example.com", _resolver_for("2606:2800:220:1:248:1893:25c8:1946")
        )
        assert result == "https://example.com/"

    def test_mixed_global_ipv4_and_ipv6_accepted(self):
        result = validate_and_normalize_public_url(
            "https://example.com",
            _resolver_for("93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"),
        )
        assert result == "https://example.com/"

    def test_mixed_global_and_linklocal_accepted(self):
        result = validate_and_normalize_public_url(
            "https://example.com", _resolver_for("fe80::1", "93.184.216.34")
        )
        assert result == "https://example.com/"

    def test_all_private_rejected(self):
        with pytest.raises(PublicURLSafetyError) as exc:
            validate_and_normalize_public_url(
                "https://example.com", _resolver_for("10.0.0.1", "192.168.1.1")
            )
        assert exc.value.code == "PRIVATE_NETWORK_TARGET"

    def test_loopback_only_rejected(self):
        with pytest.raises(PublicURLSafetyError) as exc:
            validate_and_normalize_public_url("https://example.com", _resolver_for("127.0.0.1"))
        assert exc.value.code == "PRIVATE_NETWORK_TARGET"

    def test_ipv6_loopback_only_rejected(self):
        with pytest.raises(PublicURLSafetyError) as exc:
            validate_and_normalize_public_url("https://example.com", _resolver_for("::1"))
        assert exc.value.code == "PRIVATE_NETWORK_TARGET"

    def test_linklocal_only_rejected(self):
        with pytest.raises(PublicURLSafetyError) as exc:
            validate_and_normalize_public_url("https://example.com", _resolver_for("fe80::1"))
        assert exc.value.code == "PRIVATE_NETWORK_TARGET"

    def test_carrier_grade_nat_rejected(self):
        with pytest.raises(PublicURLSafetyError) as exc:
            validate_and_normalize_public_url("https://example.com", _resolver_for("100.64.0.1"))
        assert exc.value.code == "PRIVATE_NETWORK_TARGET"

    def test_empty_dns_result_rejected(self):
        with pytest.raises(PublicURLSafetyError) as exc:
            validate_and_normalize_public_url("https://example.com", lambda h, p: [])
        assert exc.value.code == "DNS_RESOLUTION_FAILED"

    def test_dns_timeout_rejected(self):
        def failing(h, p):
            raise OSError("Name or service not known")

        with pytest.raises(PublicURLSafetyError) as exc:
            validate_and_normalize_public_url("https://example.com", failing)
        assert exc.value.code == "DNS_RESOLUTION_FAILED"


# ---------------------------------------------------------------------------
# IP literal SSRF bypass
# ---------------------------------------------------------------------------


class TestIpLiteralSsrfBypass:
    @pytest.mark.parametrize(
        "ip",
        [
            "127.0.0.1",
            "10.0.0.1",
            "172.16.0.1",
            "192.168.1.1",
            "169.254.169.254",
            "0.0.0.0",
        ],
    )
    def test_private_ipv4_literals_rejected(self, ip):
        with pytest.raises(PublicURLSafetyError) as exc:
            validate_and_normalize_public_url(f"http://{ip}", _resolver_for("93.184.216.34"))
        assert exc.value.code == "PRIVATE_NETWORK_TARGET"

    @pytest.mark.parametrize("ip", ["::1", "fe80::1", "fc00::1"])
    def test_private_ipv6_literals_rejected(self, ip):
        with pytest.raises(PublicURLSafetyError) as exc:
            validate_and_normalize_public_url(f"http://[{ip}]", _resolver_for("93.184.216.34"))
        assert exc.value.code == "PRIVATE_NETWORK_TARGET"

    def test_global_ipv4_literal_accepted(self):
        result = validate_and_normalize_public_url(
            "http://93.184.216.34", _resolver_for("93.184.216.34")
        )
        assert "93.184.216.34" in result


# ---------------------------------------------------------------------------
# DNS rebinding / TOCTOU
# ---------------------------------------------------------------------------


class TestDnsRebinding:
    def test_resolve_and_filter_returns_only_global(self):
        """_resolve_and_filter_global must return only global IPs for pinning."""
        addrs = _resolve_and_filter_global(
            "example.com",
            443,
            _resolver_for("fe80::1", "10.0.0.1", "93.184.216.34"),
        )
        for addr in addrs:
            assert addr.is_global, f"{addr} is not global but was returned"

    def test_create_validated_socket_pins_to_global_ip(self):
        """create_validated_socket must connect to the validated IP, not re-resolve."""
        resolver = _resolver_for("93.184.216.34")
        with patch("app.services.public_url_safety.socket.create_connection") as mock_conn:
            mock_sock = MagicMock()
            mock_conn.return_value = mock_sock
            with patch("app.services.public_url_safety.ssl.create_default_context") as mock_ctx:
                mock_tls = MagicMock()
                mock_ctx.return_value.wrap_socket.return_value = mock_tls
                create_validated_socket("example.com", 443, scheme="https", resolver=resolver)
        mock_conn.assert_called_once()
        connected_ip = mock_conn.call_args[0][0][0]
        assert connected_ip == "93.184.216.34"
        mock_ctx.return_value.wrap_socket.assert_called_once_with(
            mock_sock, server_hostname="example.com"
        )

    def test_rebinding_resolver_validation_uses_first_call(self):
        """If DNS changes between calls, validate_and_normalize uses first resolution."""
        resolver = _rebinding_resolver(["93.184.216.34"], ["127.0.0.1"])
        result = validate_and_normalize_public_url("https://example.com", resolver)
        assert result == "https://example.com/"

    def test_rebinding_resolver_second_call_private_is_caught_by_filter(self):
        """_resolve_and_filter_global rejects if all addresses on this call are private."""
        resolver = _rebinding_resolver(["93.184.216.34"], ["127.0.0.1"])
        validate_and_normalize_public_url("https://example.com", resolver)
        with pytest.raises(PublicURLSafetyError) as exc:
            _resolve_and_filter_global("example.com", 443, resolver)
        assert exc.value.code == "PRIVATE_NETWORK_TARGET"


# ---------------------------------------------------------------------------
# Redirect to private IP
# ---------------------------------------------------------------------------


class TestRedirectToPrivate:
    def test_redirect_to_private_ip_rejected(self):
        """A redirect target resolving to a private IP must be rejected."""
        with pytest.raises(PublicURLSafetyError) as exc:
            validate_and_normalize_public_url(
                "http://10.0.0.1/admin", _resolver_for("93.184.216.34")
            )
        assert exc.value.code == "PRIVATE_NETWORK_TARGET"

    def test_redirect_chain_with_private_target_rejected(self):
        from app.services.public_url_safety import validate_public_redirects

        with pytest.raises(PublicURLSafetyError) as exc:
            validate_public_redirects(
                ["https://legit.com", "http://192.168.1.1/secret"],
                _resolver_for("192.168.1.1"),
            )
        assert exc.value.code == "PRIVATE_NETWORK_TARGET"


# ---------------------------------------------------------------------------
# Cloud metadata hosts
# ---------------------------------------------------------------------------


class TestCloudMetadataBlocking:
    @pytest.mark.parametrize(
        "host",
        [
            "metadata.google.internal",
            "metadata.azure.internal",
            "metadata",
            "instance-data",
        ],
    )
    def test_cloud_metadata_hosts_rejected(self, host):
        with pytest.raises(PublicURLSafetyError) as exc:
            validate_and_normalize_public_url(
                f"http://{host}/latest/meta-data/",
                _resolver_for("169.254.169.254"),
            )
        assert exc.value.code == "PRIVATE_NETWORK_TARGET"


# ---------------------------------------------------------------------------
# Connection pinning verification
# ---------------------------------------------------------------------------


class TestConnectionPinning:
    def test_http_socket_connected_to_validated_ip(self):
        """HTTP connections must go to the validated global IP."""
        resolver = _resolver_for("93.184.216.34")
        with patch("app.services.public_url_safety.socket.create_connection") as mock_conn:
            mock_conn.return_value = MagicMock()
            create_validated_socket("example.com", 80, scheme="http", resolver=resolver)
        assert mock_conn.call_args[0][0] == ("93.184.216.34", 80)

    def test_https_tls_sni_uses_hostname_not_ip(self):
        """TLS SNI must verify against original hostname, not the IP."""
        resolver = _resolver_for("93.184.216.34")
        with patch("app.services.public_url_safety.socket.create_connection") as mock_conn:
            mock_sock = MagicMock()
            mock_conn.return_value = mock_sock
            with patch("app.services.public_url_safety.ssl.create_default_context") as mock_ctx:
                mock_ctx.return_value.wrap_socket.return_value = MagicMock()
                create_validated_socket("example.com", 443, scheme="https", resolver=resolver)
        mock_ctx.return_value.wrap_socket.assert_called_once_with(
            mock_sock, server_hostname="example.com"
        )

    def test_tls_failure_closes_raw_socket(self):
        """If TLS handshake fails, the raw socket must be closed."""
        resolver = _resolver_for("93.184.216.34")
        with patch("app.services.public_url_safety.socket.create_connection") as mock_conn:
            mock_sock = MagicMock()
            mock_conn.return_value = mock_sock
            with patch("app.services.public_url_safety.ssl.create_default_context") as mock_ctx:
                mock_ctx.return_value.wrap_socket.side_effect = ssl.SSLError("handshake failed")
                with pytest.raises(ssl.SSLError):
                    create_validated_socket("example.com", 443, scheme="https", resolver=resolver)
        mock_sock.close.assert_called_once()

    def test_private_ip_never_reaches_socket_creation(self):
        """A private-only DNS result must not even attempt socket.create_connection."""
        resolver = _resolver_for("10.0.0.1")
        with patch("app.services.public_url_safety.socket.create_connection") as mock_conn:
            with pytest.raises(PublicURLSafetyError):
                create_validated_socket("evil.example.com", 443, scheme="https", resolver=resolver)
        mock_conn.assert_not_called()


# ---------------------------------------------------------------------------
# Worker SafeConnectionFactory
# ---------------------------------------------------------------------------


class TestWorkerSafeConnectionFactory:
    def test_factory_pins_to_global_ip(self):
        """SafeConnectionFactory.open() must connect to validated global IP."""
        from worker_app.analysis.url_safety import SafeConnectionFactory

        resolver = _resolver_for("93.184.216.34")
        factory = SafeConnectionFactory(resolver=resolver)
        with patch("worker_app.analysis.url_safety.socket.create_connection") as mock_conn:
            mock_sock = MagicMock()
            mock_conn.return_value = mock_sock
            with patch("worker_app.analysis.url_safety.ssl.create_default_context") as mock_ctx:
                mock_tls = MagicMock()
                mock_ctx.return_value.wrap_socket.return_value = mock_tls
                conn, validated = factory.open("https://example.com")
        assert mock_conn.call_args[0][0][0] == "93.184.216.34"

    def test_factory_rejects_private_target(self):
        """SafeConnectionFactory must reject URLs resolving to private IPs."""
        from worker_app.analysis.url_safety import SafeConnectionFactory

        resolver = _resolver_for("10.0.0.1")
        factory = SafeConnectionFactory(resolver=resolver)
        with pytest.raises(PublicURLSafetyError) as exc:
            factory.open("https://evil.example.com")
        assert exc.value.code == "PRIVATE_NETWORK_TARGET"

    def test_factory_redirect_target_validated(self):
        """Each redirect in safe_fetch is re-validated through validate_public_url."""
        from worker_app.analysis.url_safety import validate_public_url

        resolver = _resolver_for("127.0.0.1")
        with pytest.raises(PublicURLSafetyError) as exc:
            validate_public_url("http://127.0.0.1/admin", resolver)
        assert exc.value.code == "PRIVATE_NETWORK_TARGET"
