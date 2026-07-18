import socket

import pytest
from worker_app.analysis.url_safety import (
    UrlSafetyError,
    validate_public_url,
    validate_redirect_chain,
)


def resolver_for(address: str):
    def resolve(hostname: str, port: int):
        del hostname, port
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]

    return resolve


def test_safe_public_url_is_accepted() -> None:
    assert (
        validate_public_url("https://example.com", resolver_for("93.184.216.34"))
        == "https://example.com/"
    )


@pytest.mark.parametrize(
    ("url", "code"),
    [
        ("http://localhost", "PRIVATE_NETWORK_TARGET"),
        ("http://127.0.0.1", "PRIVATE_NETWORK_TARGET"),
        ("http://10.0.0.1", "PRIVATE_NETWORK_TARGET"),
        ("ftp://example.com", "INVALID_ANALYSIS_URL"),
    ],
)
def test_unsafe_urls_are_rejected(url: str, code: str) -> None:
    with pytest.raises(UrlSafetyError) as captured:
        validate_public_url(url, resolver_for("93.184.216.34"))
    assert captured.value.code == code


def test_redirect_to_private_network_is_rejected() -> None:
    def resolver(hostname: str, port: int):
        del port
        address = "10.0.0.1" if hostname == "private.example" else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]

    with pytest.raises(UrlSafetyError) as captured:
        validate_redirect_chain(["https://public.example", "https://private.example"], resolver)
    assert captured.value.code == "PRIVATE_NETWORK_TARGET"
