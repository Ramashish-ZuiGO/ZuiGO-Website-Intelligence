import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, JsonValue

from app.models import FindingSeverity, FindingSource


class AnalysisFindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    finding_code: str
    category: str
    title: str
    description: str
    severity: FindingSeverity
    affected_url: str
    evidence: dict[str, JsonValue]
    source: FindingSource
    confidence_percent: int
    created_at: datetime


class AnalysisResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    analysis_run_id: uuid.UUID
    requested_url: str
    final_url: str
    http_status_code: int | None
    page_title: str | None
    meta_description: str | None
    lighthouse_version: str | None
    user_agent: str | None
    analysis_started_at: datetime
    analysis_completed_at: datetime


class AnalysisResultsResponse(BaseModel):
    result: AnalysisResultRead
    lighthouse_metrics: dict[str, JsonValue]
    playwright_measurements: dict[str, JsonValue]
    findings: list[AnalysisFindingRead]


class AnalysisScoreRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    formula_version: str
    overall_score: int | None
    performance_score: int | None
    accessibility_score: int | None
    best_practices_score: int | None
    seo_score: int | None
    technical_quality_score: int | None
    confidence_percent: int
    available_categories: list[str]
    unavailable_categories: list[str]
    weights: dict[str, int]
    deductions: list[dict[str, JsonValue]]
    calculation_details: dict[str, JsonValue]


class ReportWebsiteRead(BaseModel):
    id: uuid.UUID
    name: str | None
    url: str


class AnalysisReportResponse(BaseModel):
    report_id: uuid.UUID
    analysis_run_id: uuid.UUID
    analysis_status: str
    website: ReportWebsiteRead
    result: AnalysisResultRead
    score: AnalysisScoreRead
    lighthouse_metrics: dict[str, JsonValue]
    playwright_measurements: dict[str, JsonValue]
    findings: list[AnalysisFindingRead]
