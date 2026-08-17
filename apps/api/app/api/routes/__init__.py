from app.api.routes.accessibility import router as accessibility_router
from app.api.routes.action_plan import router as action_plan_router
from app.api.routes.agent_platform import router as agent_platform_router
from app.api.routes.analysis_comparison import router as analysis_comparison_router
from app.api.routes.analysis_runs import router as analysis_runs_router
from app.api.routes.auth import router as auth_router
from app.api.routes.browser_uat_tier0 import router as browser_uat_tier0_router
from app.api.routes.discovery import router as discovery_router
from app.api.routes.health import router as health_router
from app.api.routes.metadata import router as metadata_router
from app.api.routes.page_analysis import router as page_analysis_router
from app.api.routes.performance import router as performance_router
from app.api.routes.presentation_demo import router as presentation_demo_router
from app.api.routes.projects import router as projects_router
from app.api.routes.report_delivery import router as report_delivery_router
from app.api.routes.repository import router as repository_router
from app.api.routes.scoring_intelligence import router as scoring_intelligence_router
from app.api.routes.site_diagnostics import router as site_diagnostics_router
from app.api.routes.websites import router as websites_router
from app.api.routes.workflow_executions import router as workflow_executions_router

__all__ = [
    "action_plan_router",
    "agent_platform_router",
    "analysis_runs_router",
    "analysis_comparison_router",
    "auth_router",
    "browser_uat_tier0_router",
    "discovery_router",
    "health_router",
    "page_analysis_router",
    "performance_router",
    "presentation_demo_router",
    "projects_router",
    "repository_router",
    "report_delivery_router",
    "websites_router",
    "metadata_router",
    "accessibility_router",
    "site_diagnostics_router",
    "scoring_intelligence_router",
    "workflow_executions_router",
]
