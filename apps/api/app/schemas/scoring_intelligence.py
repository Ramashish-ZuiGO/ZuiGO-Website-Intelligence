import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ScoreCalculateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=255)

    @field_validator("idempotency_key")
    @classmethod
    def normalize_key(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Idempotency key cannot be empty")
        return normalized


class ScoreExecutionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    execution_id: uuid.UUID
    project_id: uuid.UUID
    website_id: uuid.UUID
    analysis_run_id: uuid.UUID
    formula_id: str
    formula_version: str
    scoring_profile_id: str
    scoring_profile_version: str
    metric_registry_version: str
    input_fingerprint: str
    idempotency_key: str
    status: str
    overall_score: int | None
    confidence_percent: int | None
    confidence_classification: str
    evidence_coverage_numerator: int
    evidence_coverage_denominator: int
    evidence_coverage_percentage: float | None
    unavailable_metrics: list[str]
    excluded_metrics: list[dict[str, Any]]
    failure_details: dict[str, Any]
    partial_completion_details: dict[str, Any]
    started_at: datetime
    completed_at: datetime | None
    created_at: datetime


class ScoreExecutionWithTrend(ScoreExecutionRead):
    trend: dict[str, Any]


class PaginatedScoreExecutions(BaseModel):
    items: list[ScoreExecutionWithTrend]
    total: int
    limit: int
    offset: int


class CategoryScoreRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    category_id: str
    raw_score: int | None
    final_score: int | None
    configured_weight: float
    normalized_weight: float | None
    contribution: float | None
    band: str
    included: bool
    exclusion_reason: str | None
    thresholds: dict[str, Any]
    deductions: list[dict[str, Any]]
    adjustments: list[dict[str, Any]]
    evidence_references: list[dict[str, Any]]


class MetricContributionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    metric_id: str
    raw_value: dict[str, Any]
    normalized_value: float | None
    configured_weight: float
    normalized_weight: float | None
    contribution: float | None
    inclusion_status: str
    exclusion_reason: str | None
    threshold_decision: dict[str, Any]
    deduction_or_adjustment: dict[str, Any]
    evidence_references: list[dict[str, Any]]


class ScoreSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    snapshot_id: uuid.UUID
    overall_score: int | None
    category_scores: dict[str, int | None]
    confidence_percent: int | None
    evidence_coverage_percentage: float | None
    unavailable_metrics: list[str]
    excluded_metrics: list[dict[str, Any]]
    evidence_references: list[dict[str, Any]]
    calculation_details: dict[str, Any]
    created_at: datetime


class ScoreExplanationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    formula_summary: str
    profile_summary: str
    normalization_decisions: list[dict[str, Any]]
    caps_floors_deductions: list[dict[str, Any]]
    limitations: list[str]
    reproducibility_payload: dict[str, Any]


class ScoreBreakdownRead(BaseModel):
    execution: ScoreExecutionRead
    snapshot: ScoreSnapshotRead
    categories: list[CategoryScoreRead]
    contributions: list[MetricContributionRead]
    explanation: ScoreExplanationRead
    trend: dict[str, Any]


class ScoringFormulaRead(BaseModel):
    formula_id: str
    version: str
    category_weights: dict[str, int]
    rounding: str
    unavailable_behavior: str
    technical_quality_deductions: dict[str, int]
    limitations: list[str]
    llm_calculation_allowed: bool


class ScoringProfileRead(BaseModel):
    profile_id: str
    version: str
    name: str
    bands: dict[str, float]
    threshold_rules: list[dict[str, Any]]
    limitations: list[str]
