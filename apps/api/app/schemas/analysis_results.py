import uuid
from datetime import datetime
from typing import Literal

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
    diagnostics: dict[str, JsonValue]


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


class InterpretationObservationRead(BaseModel):
    text: str
    related_finding_codes: list[str]


class InterpretationRecommendationRead(BaseModel):
    recommendation_id: str
    title: str
    explanation: str
    related_finding_codes: list[str]
    priority: Literal["critical", "high", "medium", "low"]
    business_impact: str
    recommended_fix: str
    estimated_effort: str
    responsible_role: str
    expected_improvement: str
    confidence_percent: int


class InterpretationActionPlanRead(BaseModel):
    timeframe: Literal["immediate", "short_term", "medium_term"]
    recommendation_ids: list[str]


class AnalysisInterpretationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    generation_mode: Literal["ai", "deterministic_fallback"]
    provider: str
    model: str
    prompt_version: str
    executive_summary: str
    overall_assessment: str
    strengths: list[InterpretationObservationRead]
    weaknesses: list[InterpretationObservationRead]
    priority_recommendations: list[InterpretationRecommendationRead]
    action_plan: list[InterpretationActionPlanRead]
    limitations: list[str]
    fallback_reason: str | None
    generated_at: datetime


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
    interpretation: AnalysisInterpretationRead | None
    diagnostics: dict[str, JsonValue]
