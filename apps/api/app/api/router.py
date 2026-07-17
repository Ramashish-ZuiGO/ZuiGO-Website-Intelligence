from fastapi import APIRouter

from app.api.routes.health import router as health_router

api_router = APIRouter()
api_router.include_router(health_router)

v1_router = APIRouter(prefix="/api/v1")
api_router.include_router(v1_router)
