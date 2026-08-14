from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.config import get_settings
from app.errors.handlers import UnexpectedErrorEnvelopeMiddleware, register_error_handlers
from app.logging_config import configure_logging
from app.middleware.request_logging import RequestLoggingMiddleware


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    application = FastAPI(title="ZuiGO Website Intelligence API")

    # Registered before CORSMiddleware so it sits INSIDE the CORS layer:
    # sanitized 500s for unhandled exceptions then flow back out through CORS
    # and allowed origins receive proper headers instead of a misleading
    # browser CORS error.
    application.add_middleware(UnexpectedErrorEnvelopeMiddleware)
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
