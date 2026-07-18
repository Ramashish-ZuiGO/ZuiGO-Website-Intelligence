from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# Import models here so Alembic and application code share one complete metadata registry.
from app.models.analysis_finding import AnalysisFinding  # noqa: E402, F401
from app.models.analysis_result import AnalysisResult  # noqa: E402, F401
from app.models.analysis_run import AnalysisRun  # noqa: E402, F401
from app.models.project import Project  # noqa: E402, F401
from app.models.website import Website  # noqa: E402, F401
