from typing import Literal
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
    status: str
    contribution: str
    tool_ids: list[str]


class DemoStageRead(BaseModel):
    stage_id: str
    name: str
    agent_ids: list[str]
    parallel: bool
    status: str


class DemoFindingRead(BaseModel):
    finding_id: UUID
    title: str
    severity: str
    page_url: str
    evidence_state: str


class DemoActionRead(BaseModel):
    action_id: UUID
    title: str
    priority_score: int
    responsible_role: str
    verification: str


class DemoArtifactRead(BaseModel):
    format: Literal["html", "pdf", "json"]
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
