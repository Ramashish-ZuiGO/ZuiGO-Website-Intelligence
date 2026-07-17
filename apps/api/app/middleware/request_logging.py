import logging
from time import perf_counter

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.request_context import get_or_create_request_id

logger = logging.getLogger("app.request")


class RequestLoggingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started_at = perf_counter()
        status_code = 500
        request_id = get_or_create_request_id(scope)

        async def capture_status(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, capture_status)
        finally:
            duration_ms = (perf_counter() - started_at) * 1000
            method = scope.get("method", "UNKNOWN")
            path = scope.get("path", "")
            log_level = logging.DEBUG if path == "/health" else logging.INFO
            logger.log(
                log_level,
                "http_request method=%s path=%r status=%d duration_ms=%.2f request_id=%s",
                method,
                path,
                status_code,
                duration_ms,
                request_id,
            )
