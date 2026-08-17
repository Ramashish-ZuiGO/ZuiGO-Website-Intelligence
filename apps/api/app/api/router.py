from fastapi import APIRouter, Depends

from app.api.routes import (
    accessibility_router,
    action_plan_router,
    agent_platform_router,
    analysis_comparison_router,
    analysis_runs_router,
    auth_router,
    browser_uat_tier0_router,
    discovery_router,
    health_router,
    metadata_router,
    page_analysis_router,
    performance_router,
    presentation_demo_router,
    projects_router,
    report_delivery_router,
    repository_router,
    scoring_intelligence_router,
    site_diagnostics_router,
    websites_router,
    workflow_executions_router,
)
from app.services.auth import require_bearer_auth

api_router = APIRouter()
api_router.include_router(health_router)

# Unprotected -- login itself can't require a token it hasn't issued yet.
# Kept as its own router group (not just excluded from v1_router's
# dependency) so the "which routes skip auth" answer is exactly "health and
# login," visible in one place, rather than an easy-to-miss exception list.
unauthenticated_v1_router = APIRouter(prefix="/api/v1")
unauthenticated_v1_router.include_router(auth_router)
api_router.include_router(unauthenticated_v1_router)

# M1 (docs/REPORT_QUALITY_INITIATIVE.md): every other route requires a
# valid bearer token, enforced once here rather than per-route -- a new
# route added to v1_router can never accidentally ship unprotected.
v1_router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_bearer_auth)])
v1_router.include_router(agent_platform_router)
v1_router.include_router(analysis_comparison_router)
v1_router.include_router(action_plan_router)
v1_router.include_router(analysis_runs_router)
v1_router.include_router(browser_uat_tier0_router)
v1_router.include_router(discovery_router)
v1_router.include_router(page_analysis_router)
v1_router.include_router(projects_router)
v1_router.include_router(repository_router)
v1_router.include_router(report_delivery_router)
v1_router.include_router(metadata_router)
v1_router.include_router(performance_router)
v1_router.include_router(presentation_demo_router)
v1_router.include_router(websites_router)
v1_router.include_router(accessibility_router)
v1_router.include_router(site_diagnostics_router)
v1_router.include_router(scoring_intelligence_router)
v1_router.include_router(workflow_executions_router)
api_router.include_router(v1_router)
