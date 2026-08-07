from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AnalysisJourneyStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=255)
    repository_connection_id: UUID | None = None
    page_analysis_execution_id: UUID | None = None
    max_concurrency: int = Field(default=3, ge=1, le=8)

    @field_validator("idempotency_key")
    @classmethod
    def normalize_key(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Idempotency key cannot be empty")
        return normalized


class RealWebsiteAnalysisStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    website_url: str = Field(min_length=1, max_length=2048)
    idempotency_key: str = Field(min_length=1, max_length=255)
    maximum_pages: int | None = Field(
        default=None,
        ge=1,
        le=10000,
        json_schema_extra={"deprecated": True},
    )
    browser_engines: list[Literal["chromium", "firefox", "webkit"]] = Field(
        default_factory=lambda: ["chromium", "firefox", "webkit"],
        min_length=1,
        max_length=3,
    )
    include_mobile: bool = True
    max_concurrency: int = Field(default=3, ge=1, le=8)

    @field_validator("website_url", "idempotency_key")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("This field cannot be empty")
        return normalized

    @field_validator("browser_engines")
    @classmethod
    def validate_browser_engines(
        cls,
        value: list[Literal["chromium", "firefox", "webkit"]],
    ) -> list[Literal["chromium", "firefox", "webkit"]]:
        if len(set(value)) != len(value):
            raise ValueError("Browser engines cannot be repeated")
        order = {"chromium": 0, "firefox": 1, "webkit": 2}
        return sorted(value, key=order.__getitem__)


class RealWebsiteAnalysisStartRead(BaseModel):
    project_id: UUID
    website_id: UUID
    analysis_run_id: UUID
    discovery_run_id: UUID
    page_analysis_execution_id: UUID
    workflow_execution_id: UUID
    submitted_url: str
    normalized_url: str
    analysis_status: str
    workflow_status: str
    reused: bool


class RecentRealAnalysisRead(BaseModel):
    project_id: UUID
    website_id: UUID
    analysis_run_id: UUID
    workflow_execution_id: UUID
    submitted_url: str
    normalized_url: str
    status: str
    created_at: datetime


class AnalysisJourneyStartRead(BaseModel):
    analysis_run_id: UUID
    workflow_execution_id: UUID
    analysis_status: str
    workflow_status: str
    reused: bool


class EvidenceCoverageRead(BaseModel):
    status: Literal["available", "partial", "unavailable"]
    numerator: int
    denominator: int
    percentage: float | None


class WorkflowProgressRead(BaseModel):
    execution_id: UUID
    analysis_run_id: UUID | None
    status: str
    current_stage: str
    completed_agent_ids: list[str]
    partial_agent_ids: list[str]
    pending_agent_ids: list[str]
    failed_agent_ids: list[str]
    unavailable_agent_ids: list[str]
    progress_percentage: float
    evidence_coverage: EvidenceCoverageRead
    attempt: int
    retry_available: bool
    resume_available: bool
    started_at: datetime
    completed_at: datetime | None
    elapsed_seconds: float
    unavailable_tools: list[str]
    unavailable_providers: list[str]
    safe_error_summaries: list[dict[str, str]]
    submitted_website: str | None = None
    page_coverage: dict[str, Any] = Field(default_factory=dict)
    browser_engine_progress: dict[str, Any] = Field(default_factory=dict)
    agent_states: list[dict[str, str]] = Field(default_factory=list)
    stages: list[dict[str, Any]] = Field(default_factory=list)
    completed_stage_ids: list[str] = Field(default_factory=list)
    active_stage_id: str | None = None
    pending_stage_ids: list[str] = Field(default_factory=list)
    failed_stage_id: str | None = None
    last_progress_update: datetime
    stale: bool = False
    business_error_message: str | None = None
    report_generation_available: bool = False


class ReportGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=255)
    workflow_execution_id: UUID | None = None
    report_type: str = Field(default="full_analysis", pattern=r"^[a-z][a-z0-9_]*$")

    @field_validator("idempotency_key")
    @classmethod
    def normalize_key(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Idempotency key cannot be empty")
        return normalized


class ReportSectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    section_id: UUID
    section_key: str
    position: int
    title: str
    status: str
    content: dict[str, Any]
    evidence_references: list[dict[str, Any]]
    unavailable_reason: str | None


class ReportArtifactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    artifact_id: UUID
    format: str
    media_type: str
    filename: str
    size_bytes: int
    checksum_sha256: str
    created_at: datetime


class ReportExecutionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    report_id: UUID
    project_id: UUID
    website_id: UUID
    analysis_run_id: UUID
    workflow_execution_id: UUID | None
    score_execution_id: UUID | None
    report_type: str
    report_version: str
    template_id: str
    template_version: str
    input_fingerprint: str
    idempotency_key: str
    status: str
    evidence_coverage_numerator: int
    evidence_coverage_denominator: int
    evidence_coverage_percentage: float | None
    confidence_percent: int | None
    unavailable_sections: list[str]
    provider_version_metadata: dict[str, Any]
    failure_details: dict[str, Any]
    partial_completion_details: dict[str, Any]
    started_at: datetime
    completed_at: datetime | None
    created_at: datetime
    sections: list[ReportSectionRead] = Field(default_factory=list)
    artifacts: list[ReportArtifactRead] = Field(default_factory=list)


class ReportStatusRead(BaseModel):
    report_id: UUID
    status: str
    completed_section_count: int
    total_section_count: int
    unavailable_sections: list[str]
    evidence_coverage: EvidenceCoverageRead
    started_at: datetime
    completed_at: datetime | None
    failure_details: dict[str, Any]
    partial_completion_details: dict[str, Any]


class PaginatedReports(BaseModel):
    items: list[ReportExecutionRead]
    total: int
    limit: int
    offset: int


class ReportArtifactList(BaseModel):
    items: list[ReportArtifactRead]
