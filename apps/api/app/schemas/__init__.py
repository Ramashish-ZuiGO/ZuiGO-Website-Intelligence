from app.schemas.analysis_results import AnalysisReportResponse, AnalysisResultsResponse
from app.schemas.analysis_run import AnalysisResultSummary, AnalysisRunRead
from app.schemas.discovery import (
    CoverageSummary,
    DiscoveryRunRead,
    WebsitePageList,
    WebsitePageRead,
)
from app.schemas.page_analysis import (
    PageAnalysisActionRecommendation,
    PageAnalysisRunList,
    PageAnalysisRunRead,
    PageAnalysisSummary,
    PageLevelScore,
    SiteCoverageDetail,
)
from app.schemas.project import ProjectCreate, ProjectDetail, ProjectRead
from app.schemas.website import WebsiteCreate, WebsiteRead

__all__ = [
    "AnalysisResultSummary",
    "AnalysisReportResponse",
    "AnalysisResultsResponse",
    "AnalysisRunRead",
    "CoverageSummary",
    "DiscoveryRunRead",
    "PageAnalysisActionRecommendation",
    "PageAnalysisRunList",
    "PageAnalysisRunRead",
    "PageAnalysisSummary",
    "PageLevelScore",
    "ProjectCreate",
    "ProjectDetail",
    "ProjectRead",
    "SiteCoverageDetail",
    "WebsiteCreate",
    "WebsitePageList",
    "WebsitePageRead",
    "WebsiteRead",
]
