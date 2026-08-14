"""Generic 500/CORS safety: unhandled exceptions must reach allowed origins
with CORS headers and a sanitized body, never as a misleading browser CORS
failure or a leaked stack trace."""

from app.main import create_app
from fastapi.testclient import TestClient


def _client_with_failing_route() -> TestClient:
    app = create_app()

    @app.get("/api/v1/__test_unexpected_error")
    def _boom() -> None:
        raise RuntimeError("internal secret detail that must never leak")

    return TestClient(app, raise_server_exceptions=False)


def test_unexpected_error_keeps_cors_headers_for_allowed_origin() -> None:
    client = _client_with_failing_route()
    response = client.get(
        "/api/v1/__test_unexpected_error",
        headers={"Origin": "http://localhost:3000"},
    )
    assert response.status_code == 500
    # The allowed origin receives CORS headers even on an internal error, so
    # browsers report the real 500 instead of a fake CORS failure.
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"
    body = response.json()
    assert body["error"]["code"] == "INTERNAL_SERVER_ERROR"
    assert body["error"]["message"] == "An unexpected error occurred."
    text = response.text
    assert "internal secret detail" not in text
    assert "RuntimeError" not in text
    assert "Traceback" not in text


def test_unexpected_error_without_origin_still_sanitized() -> None:
    client = _client_with_failing_route()
    response = client.get("/api/v1/__test_unexpected_error")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_SERVER_ERROR"
    assert "internal secret detail" not in response.text


def test_disallowed_origin_gets_no_cors_grant_on_error() -> None:
    client = _client_with_failing_route()
    response = client.get(
        "/api/v1/__test_unexpected_error",
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 500
    # CORS policy is unchanged: only configured origins are granted.
    assert response.headers.get("access-control-allow-origin") is None
