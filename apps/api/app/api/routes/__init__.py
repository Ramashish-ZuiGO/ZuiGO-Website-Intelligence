from app.api.routes.action_plan import router as action_plan_router
from app.api.routes.analysis_runs import router as analysis_runs_router
from app.api.routes.discovery import router as discovery_router
from app.api.routes.health import router as health_router
from app.api.routes.page_analysis import router as page_analysis_router
from app.api.routes.projects import router as projects_router
from app.api.routes.repository import router as repository_router

__all__ = [
    "action_plan_router",
    "analysis_runs_router",
    "discovery_router",
    "health_router",
    "page_analysis_router",
    "projects_router",
    "repository_router",
]
