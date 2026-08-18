"""M2 (docs/REPORT_QUALITY_INITIATIVE.md): abuse protection.

Zero rate limiting or request-size limiting existed anywhere in the API.
Combined with the (now-fixed) zero-auth gap, a caller with a valid token
could still trigger unbounded real Playwright/Lighthouse analysis runs, or
send arbitrarily large request bodies. Both middlewares below are in-memory
and per-process -- correct for this deployment's single uvicorn worker (see
Settings.rate_limit_general_per_minute); would need a shared store (Redis is
already a dependency) if the API ever scales to multiple worker processes.
"""

import json
import time
from http import HTTPStatus

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.request_context import get_or_create_request_id

_WINDOW_SECONDS = 60.0
_MAX_TRACKED_CLIENTS = 10_000


def _client_key(scope: Scope) -> str:
    client = scope.get("client")
    return client[0] if client else "unknown"


def _is_expensive_endpoint(method: str, path: str) -> bool:
    """Endpoints that dispatch a real, potentially hour-long analysis run."""
    if method != "POST":
        return False
    if path == "/api/v1/workflow-executions":
        return True
    return path.endswith(("/discovery-runs", "/resume", "/retry", "/reanalyse"))


class _FixedWindowLimiter:
    """Per-client fixed-window request counter.

    Evicts the oldest-seen client once the tracked-client count exceeds a
    safety cap, so a long-running process with many distinct callers can't
    grow unbounded memory.
    """

    def __init__(self, limit_per_minute: int) -> None:
        self._limit = limit_per_minute
        self._counts: dict[str, tuple[int, float]] = {}

    def allow(self, key: str, *, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        count, window_start = self._counts.get(key, (0, now))
        if now - window_start >= _WINDOW_SECONDS:
            count, window_start = 0, now
        count += 1
        if key not in self._counts and len(self._counts) >= _MAX_TRACKED_CLIENTS:
            oldest_key = min(self._counts, key=lambda k: self._counts[k][1])
            del self._counts[oldest_key]
        self._counts[key] = (count, window_start)
        return count <= self._limit


async def _send_json_error(
    scope: Scope, send: Send, *, status_code: int, code: str, message: str
) -> None:
    request_id = get_or_create_request_id(scope)
    body = json.dumps(
        {"error": {"code": code, "message": message, "details": None, "request_id": request_id}}
    ).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"x-request-id", request_id.encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class RateLimitMiddleware:
    """General per-client rate limit, plus a stricter one for expensive endpoints."""

    def __init__(self, app: ASGIApp, *, general_per_minute: int, expensive_per_minute: int) -> None:
        self.app = app
        self._general = _FixedWindowLimiter(general_per_minute)
        self._expensive = _FixedWindowLimiter(expensive_per_minute)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        key = _client_key(scope)
        method = scope.get("method", "")
        path = scope.get("path", "")

        if _is_expensive_endpoint(method, path) and not self._expensive.allow(key):
            await _send_json_error(
                scope,
                send,
                status_code=HTTPStatus.TOO_MANY_REQUESTS,
                code="RATE_LIMIT_EXCEEDED",
                message="Too many analysis-triggering requests. Please wait before retrying.",
            )
            return

        if not self._general.allow(key):
            await _send_json_error(
                scope,
                send,
                status_code=HTTPStatus.TOO_MANY_REQUESTS,
                code="RATE_LIMIT_EXCEEDED",
                message="Too many requests. Please slow down.",
            )
            return

        await self.app(scope, receive, send)


class RequestSizeLimitMiddleware:
    """Rejects request bodies over ``max_bytes``.

    Content-Length is checked first (rejects the common case without
    reading any body). For chunked/no-Content-Length requests, the body is
    buffered here up to ``max_bytes`` and replayed to the wrapped app --
    correct because these bodies are small JSON payloads, never uploads.
    """

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        declared_length = headers.get(b"content-length")
        if declared_length is not None:
            try:
                if int(declared_length) > self.max_bytes:
                    await self._reject(scope, send)
                    return
            except ValueError:
                pass

        buffered: list[bytes] = []
        total = 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                break
            chunk = message.get("body", b"")
            total += len(chunk)
            if total > self.max_bytes:
                await self._reject(scope, send)
                return
            buffered.append(chunk)
            if not message.get("more_body", False):
                break

        index = 0

        async def replay_receive() -> Message:
            nonlocal index
            if index < len(buffered):
                chunk = buffered[index]
                index += 1
                return {
                    "type": "http.request",
                    "body": chunk,
                    "more_body": index < len(buffered),
                }
            return {"type": "http.disconnect"}

        await self.app(scope, replay_receive, send)

    async def _reject(self, scope: Scope, send: Send) -> None:
        await _send_json_error(
            scope,
            send,
            status_code=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            code="REQUEST_BODY_TOO_LARGE",
            message="Request body exceeds the maximum allowed size.",
        )
