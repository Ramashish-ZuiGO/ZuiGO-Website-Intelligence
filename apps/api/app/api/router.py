from fastapi import APIRouter

from app.api.routes.analysis_runs import router as analysis_runs_router
from app.api.routes.discovery import router as discovery_router
from app.api.routes.health import router as health_router
from app.api.routes.projects import router as projects_router

api_router = APIRouter()
api_router.include_router(health_router)

v1_router = APIRouter(prefix="/api/v1")
v1_router.include_router(analysis_runs_router)
v1_router.include_router(discovery_router)
v1_router.include_router(projects_router)
api_router.include_router(v1_router)
