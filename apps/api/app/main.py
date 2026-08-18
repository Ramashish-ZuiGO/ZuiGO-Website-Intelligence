from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.config import get_settings
from app.errors.handlers import UnexpectedErrorEnvelopeMiddleware, register_error_handlers
from app.logging_config import configure_logging
from app.middleware.rate_limiting import RateLimitMiddleware, RequestSizeLimitMiddleware
from app.middleware.request_logging import RequestLoggingMiddleware


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    application = FastAPI(title="ZuiGO Website Intelligence API")

    # Registered before CORSMiddleware so they sit INSIDE the CORS layer:
    # their responses (sanitized 500s, 429s, 413s) then flow back out through
    # CORS and allowed origins receive proper headers instead of a misleading
    # browser CORS error.
    application.add_middleware(UnexpectedErrorEnvelopeMiddleware)
    application.add_middleware(
        RateLimitMiddleware,
        general_per_minute=settings.rate_limit_general_per_minute,
        expensive_per_minute=settings.rate_limit_expensive_per_minute,
    )
    application.add_middleware(
        RequestSizeLimitMiddleware, max_bytes=settings.max_request_body_bytes
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        # PATCH is required by the action-plan status and repository-connection
        # update endpoints; without it cross-origin preflight rejects them.
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["*"],
    )
    application.add_middleware(RequestLoggingMiddleware)
    register_error_handlers(application)
    application.include_router(api_router)

    return application


app = create_app()
