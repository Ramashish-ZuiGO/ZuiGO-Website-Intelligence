from unittest.mock import patch

import httpx
import pytest
from app.db.base import Base  # noqa: F401
from app.services.crux_provider import CruxProvider
from httpx import Response


@pytest.fixture
def crux_provider():
    return CruxProvider(api_key="test_key")


@pytest.mark.anyio
async def test_crux_url_lookup(crux_provider):
    mock_response = Response(
        200,
        request=httpx.Request("POST", "https://example.com"),
        json={"record": {"metrics": {"largest_contentful_paint": {"percentiles": {"p75": 1200}}}}},
    )
    with patch("httpx.AsyncClient.post", return_value=mock_response) as mock_post:
        result = await crux_provider.fetch_record(url="https://example.com")

        assert result["status"] == "success"
        assert (
            result["data"]["record"]["metrics"]["largest_contentful_paint"]["percentiles"]["p75"]
            == 1200
        )
        mock_post.assert_called_once()
        assert "url" in mock_post.call_args[1]["json"]
        assert mock_post.call_args[1]["json"]["url"] == "https://example.com"


@pytest.mark.anyio
async def test_crux_origin_fallback(crux_provider):
    mock_response = Response(
        200,
        request=httpx.Request("POST", "https://example.com"),
        json={"record": {"metrics": {"largest_contentful_paint": {"percentiles": {"p75": 1000}}}}},
    )
    with patch("httpx.AsyncClient.post", return_value=mock_response) as mock_post:
        result = await crux_provider.fetch_record(origin="https://example.com")

        assert result["status"] == "success"
        assert (
            result["data"]["record"]["metrics"]["largest_contentful_paint"]["percentiles"]["p75"]
            == 1000
        )
        mock_post.assert_called_once()
        assert "origin" in mock_post.call_args[1]["json"]
        assert mock_post.call_args[1]["json"]["origin"] == "https://example.com"


@pytest.mark.anyio
async def test_crux_no_api_key():
    provider = CruxProvider(api_key=None)
    with patch("app.services.crux_provider.get_settings") as mock_settings:
        mock_settings.return_value.crux_api_key = None
        result = await provider.fetch_record(url="https://example.com")
        assert result["status"] == "unavailable"


@pytest.mark.anyio
async def test_crux_no_record(crux_provider):
    mock_response = Response(404, request=httpx.Request("POST", "https://example.com"))
    with patch("httpx.AsyncClient.post", return_value=mock_response):
        result = await crux_provider.fetch_record(url="https://example.com/not-found")
        assert result["status"] == "no_record"


@pytest.mark.anyio
async def test_crux_http_error(crux_provider):
    mock_response = Response(500, request=httpx.Request("POST", "https://example.com"))
    with patch("httpx.AsyncClient.post", return_value=mock_response):
        result = await crux_provider.fetch_record(url="https://example.com")
        assert result["status"] == "error"
