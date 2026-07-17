from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(title="ZuiGO Website Intelligence API")

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["*"],
    )
    application.include_router(api_router)

    return application


app = create_app()
