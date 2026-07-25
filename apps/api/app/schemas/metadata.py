from enum import StrEnum

from pydantic import BaseModel, Field


class MetricValueTypeEnum(StrEnum):
    SCORE = "score"
    PERCENTAGE = "percentage"
    COUNT = "count"
    DURATION = "duration"
    BYTES = "bytes"
    RATIO = "ratio"
    BOOLEAN = "boolean"
    STATUS = "status"
    TEXT = "text"
    UNAVAILABLE = "unavailable"


class MetricCategoryEnum(StrEnum):
    SITE_SCORE = "site_score"
    CATEGORY_SCORE = "category_score"
    PAGE_SCORE = "page_score"
    DIAGNOSTIC_SCORE = "diagnostic_score"
    ACTION_PLAN = "action_plan"
    COVERAGE = "coverage"
    REPOSITORY = "repository"
    PERFORMANCE = "performance"
    ACCESSIBILITY = "accessibility"
    SECURITY = "security"
    COMPATIBILITY = "compatibility"
    OTHER = "other"


class MetricDefinition(BaseModel):
    metric_id: str = Field(..., description="Stable metric ID")
    label: str = Field(..., description="Display label for the metric")
    category: MetricCategoryEnum = Field(..., description="Category of the metric")
    description: str = Field(..., description="Concise description")
    explanation: str = Field(..., description="Detailed explanation of what it measures")
    value_type: MetricValueTypeEnum = Field(..., description="Value type of the metric")
    unit: str | None = Field(None, description="Unit of measurement if applicable")
    display_scale: str | None = Field(None, description="Display scale e.g. x/100")
    min_value: float | None = Field(None, description="Minimum possible value")
    max_value: float | None = Field(None, description="Maximum possible value")
    higher_is_better: bool | None = Field(
        None, description="True if higher is better, False if lower is better, None if neither"
    )
    evidence_source: str = Field(..., description="Where the evidence comes from")
    calculation_summary: str = Field(
        ..., description="Summary of how it is calculated or aggregated"
    )
    interpretation_guidance: str = Field(..., description="Guidance on how to interpret the result")
    profile_reference: str | None = Field(
        None, description="Reference to a threshold/profile if available"
    )
    known_limitations: str = Field(..., description="Known limitations of this metric")
    confidence_applicability: str = Field(..., description="How confidence applies to this metric")
    methodology_version: str | None = Field(None, description="Version of the methodology used")
    registry_version: str = Field(
        default="1.0.0", description="Version of this metric definition in the registry"
    )
