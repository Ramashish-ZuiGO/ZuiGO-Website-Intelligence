from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DemoRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=255)
    simulate_failure: bool = False

    @field_validator("idempotency_key")
    @classmethod
    def normalize_key(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Idempotency key cannot be empty")
        return normalized


class DemoAgentRead(BaseModel):
    agent_id: str
    name: str
    responsibility: str
    status: str
    processed_summary: str


class DemoStageRead(BaseModel):
    stage_id: str
    name: str
    agent_ids: list[str]
    parallel: bool
    status: str


class DemoFindingRead(BaseModel):
    title: str
    severity: str
    affected_page_count: int
    occurrence_count: int
    affected_browsers: list[str]
    works_in_browsers: list[str]
    plain_language_explanation: str
    technical_explanation: str
    why_it_matters: str
    business_impact: str
    technical_impact: str
    evidence_summary: str
    evidence_source: str
    evidence_timestamp: str
    example_pages: list[str]
    remaining_page_count: int
    recommended_fix: str
    responsible_role: str
    estimated_effort: str
    verification: str
    confidence: dict[str, Any]
    detecting_agent: str
    validating_agent: str
    limitations: str
    all_affected_pages: list[dict[str, Any]]


class DemoActionRead(BaseModel):
    priority_rank: int
    title: str
    priority_score: int
    responsible_role: str
    impact: str
    effort: str
    problem_being_solved: str
    affected_scope: dict[str, Any]
    affected_browsers: list[str]
    dependencies: list[Any]
    expected_measurable_outcome: str
    verification_method: str
    related_finding_ids: list[str]
    evidence_references: list[dict[str, Any]]


class DemoArtifactRead(BaseModel):
    kind: Literal[
        "presentation_html",
        "presentation_pdf",
        "technical_appendix",
        "evidence_json",
        "page_inventory",
    ]
    label: str
    filename: str
    size_bytes: int
    checksum_sha256: str
    download_url: str


class PresentationDemoRead(BaseModel):
    prepared: bool
    presentation_status: Literal["ready", "completed", "fallback", "not_prepared"]
    live_execution_status: str | None
    used_prepared_fallback: bool
    status_message: str
    project_id: UUID | None
    project_name: str | None
    website_id: UUID | None
    website_name: str | None
    website_url: str | None
    analysis_run_id: UUID | None
    workflow_execution_id: UUID | None
    report_id: UUID | None
    report_status: str | None
    report_ready: bool
    overall_score: int | None
    score_confidence_percent: int | None
    evidence_coverage_numerator: int
    evidence_coverage_denominator: int
    evidence_coverage_percentage: float | None
    page_coverage: dict[str, Any]
    page_inventory: list[dict[str, Any]]
    browser_compatibility: dict[str, Any]
    category_scores: list[dict[str, Any]]
    agents: list[DemoAgentRead]
    stages: list[DemoStageRead]
    top_findings: list[DemoFindingRead]
    top_actions: list[DemoActionRead]
    artifacts: list[DemoArtifactRead]
    reused: bool


class DemoResetRead(BaseModel):
    reset: bool
    deleted_project_count: int
    status_message: str
