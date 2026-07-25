from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class RatingEnum(StrEnum):
    GOOD = "good"
    NEEDS_IMPROVEMENT = "needs_improvement"
    POOR = "poor"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "not_applicable"


class ComparisonDirectionEnum(StrEnum):
    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"


class EvidenceTypeEnum(StrEnum):
    FIELD = "field"
    LAB = "lab"
    AUTOMATED = "automated"
    MANUAL = "manual"
    MIXED = "mixed"


class OfficialSourceMetadata(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    authoritative_organization: str
    source_title: str
    standard_version: str | None = None
    publication_date: str | None = None
    url: str | None = None
    evidence_type: EvidenceTypeEnum
    review_date: str
    limitations: list[str] = Field(default_factory=list)


class ThresholdRule(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    metric_id: str
    good_threshold: float | None = None
    needs_improvement_threshold: float | None = None
    poor_threshold: float | None = None
    comparison_direction: ComparisonDirectionEnum
    unit: str | None = None
    evidence_type: EvidenceTypeEnum
    source_reference: OfficialSourceMetadata | None = None
    interpretation_text: str | None = None
    limitations: list[str] = Field(default_factory=list)


class ProfileDefinition(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    profile_id: str
    name: str
    version: str
    description: str
    intended_website_type: str
    country_jurisdiction: str | None = None
    applicable_standards: list[str] = Field(default_factory=list)
    source_references: list[OfficialSourceMetadata] = Field(default_factory=list)
    threshold_rules: list[ThresholdRule] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    is_default: bool = False
    registry_version: str = "1.0.0"


class MetricInterpretation(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    metric_id: str
    raw_value: float | str | None = None
    unit: str | None = None
    rating: RatingEnum
    selected_profile_id: str
    selected_profile_version: str
    thresholds_used: dict[str, float | None]
    evidence_type: EvidenceTypeEnum | None = None
    source_reference: OfficialSourceMetadata | None = None
    explanation: str | None = None
    limitations: list[str] = Field(default_factory=list)
