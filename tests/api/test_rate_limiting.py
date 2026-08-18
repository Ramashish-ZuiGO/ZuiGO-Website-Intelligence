"""M2 (docs/REPORT_QUALITY_INITIATIVE.md): abuse protection.

Builds small standalone Starlette apps rather than reusing the shared
`app` singleton, so each test controls its own limiter thresholds without
interfering with -- or being interfered with by -- the rest of the suite
(the real app's limits are relaxed for tests, see tests/conftest.py).
"""

from app.middleware.rate_limiting import (
    RateLimitMiddleware,
    RequestSizeLimitMiddleware,
    _FixedWindowLimiter,
    _is_expensive_endpoint,
)
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient


def _rate_limited_app(*, general_per_minute: int, expensive_per_minute: int) -> FastAPI:
    application = FastAPI()

    @application.post("/api/v1/workflow-executions")
    def start_analysis() -> dict[str, bool]:
        return {"ok": True}

    @application.get("/api/v1/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    application.add_middleware(
        RateLimitMiddleware,
        general_per_minute=general_per_minute,
        expensive_per_minute=expensive_per_minute,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["https://allowed.example"],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    return application


class TestFixedWindowLimiter:
    def test_allows_up_to_the_limit(self) -> None:
        limiter = _FixedWindowLimiter(3)
        assert limiter.allow("client-a") is True
        assert limiter.allow("client-a") is True
        assert limiter.allow("client-a") is True

    def test_denies_beyond_the_limit(self) -> None:
        limiter = _FixedWindowLimiter(2)
        assert limiter.allow("client-a") is True
        assert limiter.allow("client-a") is True
        assert limiter.allow("client-a") is False

    def test_resets_after_the_window_elapses(self) -> None:
        limiter = _FixedWindowLimiter(1)
        assert limiter.allow("client-a", now=1000.0) is True
        assert limiter.allow("client-a", now=1030.0) is False
        assert limiter.allow("client-a", now=1061.0) is True

    def test_tracks_clients_independently(self) -> None:
        limiter = _FixedWindowLimiter(1)
        assert limiter.allow("client-a") is True
        assert limiter.allow("client-b") is True

    def test_evicts_oldest_client_once_over_the_safety_cap(self) -> None:
        limiter = _FixedWindowLimiter(1_000_000)
        limiter._counts["oldest"] = (1, 0.0)
        for index in range(10_000 - 1):
            limiter.allow(f"client-{index}", now=100.0 + index)
        assert "oldest" in limiter._counts
        limiter.allow("newest", now=100_000.0)
        assert "oldest" not in limiter._counts
        assert len(limiter._counts) == 10_000


class TestIsExpensiveEndpoint:
    def test_start_workflow_execution_is_expensive(self) -> None:
        assert _is_expensive_endpoint("POST", "/api/v1/workflow-executions") is True

    def test_get_on_the_same_path_is_not_expensive(self) -> None:
        assert _is_expensive_endpoint("GET", "/api/v1/workflow-executions") is False

    def test_discovery_run_start_is_expensive(self) -> None:
        assert _is_expensive_endpoint("POST", "/api/v1/websites/abc/discovery-runs") is True

    def test_resume_is_expensive(self) -> None:
        assert _is_expensive_endpoint("POST", "/api/v1/workflow-executions/abc/resume") is True

    def test_retry_is_expensive(self) -> None:
        assert _is_expensive_endpoint("POST", "/api/v1/agent-runs/abc/retry") is True

    def test_reanalyse_is_expensive(self) -> None:
        assert _is_expensive_endpoint("POST", "/api/v1/analysis-runs/abc/reanalyse") is True

    def test_cancel_is_not_expensive(self) -> None:
        assert _is_expensive_endpoint("POST", "/api/v1/workflow-executions/abc/cancel") is False

    def test_unrelated_get_is_not_expensive(self) -> None:
        assert _is_expensive_endpoint("GET", "/api/v1/websites") is False


class TestRateLimitMiddleware:
    def test_general_limit_allows_requests_under_the_threshold(self) -> None:
        client = TestClient(_rate_limited_app(general_per_minute=5, expensive_per_minute=5))
        for _ in range(5):
            response = client.get("/api/v1/health")
            assert response.status_code == 200

    def test_general_limit_returns_429_over_the_threshold(self) -> None:
        client = TestClient(_rate_limited_app(general_per_minute=2, expensive_per_minute=100))
        client.get("/api/v1/health")
        client.get("/api/v1/health")
        response = client.get("/api/v1/health")
        assert response.status_code == 429
        body = response.json()
        assert body["error"]["code"] == "RATE_LIMIT_EXCEEDED"
        assert body["error"]["request_id"]

    def test_expensive_endpoint_has_its_own_stricter_limit(self) -> None:
        client = TestClient(_rate_limited_app(general_per_minute=1000, expensive_per_minute=1))
        first = client.post("/api/v1/workflow-executions")
        assert first.status_code == 200
        second = client.post("/api/v1/workflow-executions")
        assert second.status_code == 429
        assert second.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"

    def test_rate_limited_response_still_carries_cors_headers(self) -> None:
        """Real bug caught before shipping: raw-ASGI middleware placed
        outside CORSMiddleware produces responses with no CORS headers, so a
        legitimate browser caller sees a misleading CORS error instead of
        the real 429. Registered inside CORS specifically to avoid this
        (mirrors UnexpectedErrorEnvelopeMiddleware's existing placement).
        """
        client = TestClient(_rate_limited_app(general_per_minute=1, expensive_per_minute=100))
        client.get("/api/v1/health", headers={"Origin": "https://allowed.example"})
        response = client.get("/api/v1/health", headers={"Origin": "https://allowed.example"})
        assert response.status_code == 429
        assert response.headers["access-control-allow-origin"] == "https://allowed.example"


def _size_limited_app(*, max_bytes: int) -> FastAPI:
    application = FastAPI()

    @application.post("/echo")
    async def echo(payload: dict) -> dict:
        return payload

    application.add_middleware(RequestSizeLimitMiddleware, max_bytes=max_bytes)
    return application


class TestRequestSizeLimitMiddleware:
    def test_allows_a_body_within_the_limit(self) -> None:
        client = TestClient(_size_limited_app(max_bytes=1_000))
        response = client.post("/echo", json={"a": "b"})
        assert response.status_code == 200
        assert response.json() == {"a": "b"}

    def test_rejects_via_content_length_header_without_reading_the_body(self) -> None:
        client = TestClient(_size_limited_app(max_bytes=10))
        response = client.post("/echo", json={"a": "b" * 100})
        assert response.status_code == 413
        body = response.json()
        assert body["error"]["code"] == "REQUEST_BODY_TOO_LARGE"

    def test_rejects_a_chunked_body_without_content_length(self) -> None:
        client = TestClient(_size_limited_app(max_bytes=10))

        def body_stream():
            yield b'{"a": "'
            yield b"b" * 100
            yield b'"}'

        response = client.post("/echo", content=body_stream())
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "REQUEST_BODY_TOO_LARGE"
