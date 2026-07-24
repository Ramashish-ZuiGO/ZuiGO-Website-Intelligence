from fastapi import APIRouter

from app.api.routes import (
    action_plan_router,
    analysis_runs_router,
    discovery_router,
    health_router,
    page_analysis_router,
    projects_router,
    repository_router,
)

api_router = APIRouter()
api_router.include_router(health_router)

v1_router = APIRouter(prefix="/api/v1")
v1_router.include_router(action_plan_router)
v1_router.include_router(analysis_runs_router)
v1_router.include_router(discovery_router)
v1_router.include_router(page_analysis_router)
v1_router.include_router(projects_router)
v1_router.include_router(repository_router)
api_router.include_router(v1_router)
