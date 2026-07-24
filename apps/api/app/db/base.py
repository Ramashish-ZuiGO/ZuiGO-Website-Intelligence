from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# Import models here so Alembic and application code share one complete metadata registry.
from app.models.action_plan import (  # noqa: E402
    ActionGenerationExecution,  # noqa: F401
    ActionGroup,  # noqa: F401
    ActionItem,  # noqa: F401
    ActionStatusHistory,  # noqa: F401
)
from app.models.analysis_diagnostic import AnalysisDiagnostic  # noqa: E402, F401
from app.models.analysis_finding import AnalysisFinding  # noqa: E402, F401
from app.models.analysis_interpretation import AnalysisInterpretation  # noqa: E402, F401
from app.models.analysis_result import AnalysisResult  # noqa: E402, F401
from app.models.analysis_run import AnalysisRun  # noqa: E402, F401
from app.models.analysis_score import AnalysisScore  # noqa: E402, F401
from app.models.discovery_run import DiscoveryRun  # noqa: E402, F401
from app.models.page_analysis_run import PageAnalysisRun  # noqa: E402, F401
from app.models.project import Project  # noqa: E402, F401
from app.models.repository import (  # noqa: E402, F401
    ActionMatchingExecution,  # noqa: F401
    ActionRepositoryMatch,  # noqa: F401
    DetectedTechnology,  # noqa: F401
    RepositoryConnection,  # noqa: F401
    RepositoryFileIndex,  # noqa: F401
    RepositoryScanExecution,  # noqa: F401
)
from app.models.website import Website  # noqa: E402, F401
from app.models.website_page import WebsitePage  # noqa: E402, F401
