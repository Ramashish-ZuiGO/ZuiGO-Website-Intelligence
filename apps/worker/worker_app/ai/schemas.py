from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

INSUFFICIENT_EVIDENCE = "Insufficient verified evidence is available for this conclusion."


class GroundedObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text: str = Field(min_length=1, max_length=500)
    related_finding_codes: list[str] = Field(default_factory=list, max_length=20)


class Recommendation(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    recommendation_id: str = Field(pattern=r"^[A-Z0-9_-]{1,80}$")
    title: str = Field(min_length=1, max_length=200)
    explanation: str = Field(min_length=1, max_length=1000)
    related_finding_codes: list[str] = Field(min_length=1, max_length=20)
    priority: Literal["critical", "high", "medium", "low"]
    business_impact: str = Field(min_length=1, max_length=700)
    recommended_fix: str = Field(min_length=1, max_length=1000)
    estimated_effort: str = Field(min_length=1, max_length=100)
    responsible_role: str = Field(min_length=1, max_length=100)
    expected_improvement: str = Field(min_length=1, max_length=500)
    confidence_percent: int = Field(ge=0, le=100)

    @field_validator("related_finding_codes")
    @classmethod
    def unique_codes(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class ActionPlanItem(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    timeframe: Literal["immediate", "short_term", "medium_term"]
    recommendation_ids: list[str] = Field(min_length=1, max_length=20)


class InterpretationContent(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    executive_summary: str = Field(min_length=1, max_length=2000)
    overall_assessment: str = Field(min_length=1, max_length=1000)
    strengths: list[GroundedObservation] = Field(default_factory=list, max_length=20)
    weaknesses: list[GroundedObservation] = Field(default_factory=list, max_length=50)
    priority_recommendations: list[Recommendation] = Field(default_factory=list, max_length=50)
    action_plan: list[ActionPlanItem] = Field(default_factory=list, max_length=20)
    limitations: list[str] = Field(default_factory=list, max_length=20)


def validate_grounding(content: InterpretationContent, finding_codes: set[str]) -> None:
    recommendation_ids = {
        recommendation.recommendation_id for recommendation in content.priority_recommendations
    }
    referenced_codes = [
        code
        for item in [*content.strengths, *content.weaknesses]
        for code in item.related_finding_codes
    ] + [
        code
        for recommendation in content.priority_recommendations
        for code in recommendation.related_finding_codes
    ]
    unknown_codes = set(referenced_codes) - finding_codes
    if unknown_codes:
        raise ValueError("Interpretation references unknown finding codes.")
    for plan_item in content.action_plan:
        if not set(plan_item.recommendation_ids) <= recommendation_ids:
            raise ValueError("Action plan references unknown recommendations.")
