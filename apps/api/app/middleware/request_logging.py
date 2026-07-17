import logging
import re
from time import perf_counter

from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("app.request")
safe_request_id = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


class RequestLoggingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started_at = perf_counter()
        status_code = 500

        async def capture_status(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, capture_status)
        finally:
            duration_ms = (perf_counter() - started_at) * 1000
            method = scope.get("method", "UNKNOWN")
            path = scope.get("path", "")
            request_id = self._get_request_id(scope)
            request_id_field = f" request_id={request_id}" if request_id else ""
            log_level = logging.DEBUG if path == "/health" else logging.INFO
            logger.log(
                log_level,
                "http_request method=%s path=%r status=%d duration_ms=%.2f%s",
                method,
                path,
                status_code,
                duration_ms,
                request_id_field,
            )

    @staticmethod
    def _get_request_id(scope: Scope) -> str | None:
        for name, value in scope.get("headers", []):
            if name.lower() != b"x-request-id":
                continue
            candidate = value.decode("ascii", errors="ignore")
            if safe_request_id.fullmatch(candidate):
                return candidate
        return None
