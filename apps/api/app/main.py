from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.config import get_settings
from app.errors.handlers import register_error_handlers
from app.logging_config import configure_logging
from app.middleware.request_logging import RequestLoggingMiddleware


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    application = FastAPI(title="ZuiGO Website Intelligence API")

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["*"],
    )
    application.add_middleware(RequestLoggingMiddleware)
    register_error_handlers(application)
    application.include_router(api_router)

    return application


app = create_app()
