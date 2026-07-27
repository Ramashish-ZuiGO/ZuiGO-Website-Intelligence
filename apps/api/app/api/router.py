from fastapi import APIRouter

from app.api.routes import (
    accessibility_router,
    action_plan_router,
    agent_platform_router,
    analysis_runs_router,
    discovery_router,
    health_router,
    metadata_router,
    page_analysis_router,
    performance_router,
    projects_router,
    report_delivery_router,
    repository_router,
    scoring_intelligence_router,
    site_diagnostics_router,
    websites_router,
    workflow_executions_router,
)

api_router = APIRouter()
api_router.include_router(health_router)

v1_router = APIRouter(prefix="/api/v1")
v1_router.include_router(agent_platform_router)
v1_router.include_router(action_plan_router)
v1_router.include_router(analysis_runs_router)
v1_router.include_router(discovery_router)
v1_router.include_router(page_analysis_router)
v1_router.include_router(projects_router)
v1_router.include_router(repository_router)
v1_router.include_router(report_delivery_router)
v1_router.include_router(metadata_router)
v1_router.include_router(performance_router)
v1_router.include_router(websites_router)
v1_router.include_router(accessibility_router)
v1_router.include_router(site_diagnostics_router)
v1_router.include_router(scoring_intelligence_router)
v1_router.include_router(workflow_executions_router)
api_router.include_router(v1_router)
