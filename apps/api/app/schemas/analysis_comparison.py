from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ReanalysisSettingsRead(BaseModel):
    baseline_analysis_run_id: UUID
    website_id: UUID
    website_url: str
    baseline_created_at: datetime
    maximum_pages: int | None
    browser_engines: list[Literal["chromium", "firefox", "webkit"]]
    include_mobile: bool
    max_concurrency: int


class ReanalysisStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed: Literal[True]
    idempotency_key: str = Field(min_length=1, max_length=255)
    maximum_pages: int | None = Field(
        default=None,
        ge=1,
        le=10000,
        json_schema_extra={"deprecated": True},
    )
    browser_engines: list[Literal["chromium", "firefox", "webkit"]] = Field(
        min_length=1,
        max_length=3,
    )
    include_mobile: bool = True
    max_concurrency: int = Field(default=3, ge=1, le=8)

    @field_validator("idempotency_key")
    @classmethod
    def normalize_key(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Idempotency key cannot be empty")
        return normalized

    @field_validator("browser_engines")
    @classmethod
    def normalize_engines(
        cls,
        value: list[Literal["chromium", "firefox", "webkit"]],
    ) -> list[Literal["chromium", "firefox", "webkit"]]:
        if len(set(value)) != len(value):
            raise ValueError("Browser engines cannot be repeated")
        order = {"chromium": 0, "firefox": 1, "webkit": 2}
        return sorted(value, key=order.__getitem__)


class ReanalysisStartRead(BaseModel):
    baseline_analysis_run_id: UUID
    analysis_run_id: UUID
    discovery_run_id: UUID
    page_analysis_execution_id: UUID
    workflow_execution_id: UUID
    analysis_status: str
    workflow_status: str
    reused: bool


class ComparisonGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=255)

    @field_validator("idempotency_key")
    @classmethod
    def normalize_key(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Idempotency key cannot be empty")
        return normalized


class ComparisonArtifactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    artifact_id: UUID
    format: Literal["html", "pdf", "json"]
    media_type: str
    filename: str
    checksum_sha256: str
    created_at: datetime


class AnalysisComparisonRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    comparison_id: UUID
    project_id: UUID
    website_id: UUID
    baseline_analysis_run_id: UUID
    current_analysis_run_id: UUID
    comparison_version: str
    status: str
    result_payload: dict[str, Any]
    limitations: list[str]
    completed_at: datetime
    created_at: datetime
    artifacts: list[ComparisonArtifactRead] = Field(default_factory=list)


class ComparisonHistoryRead(BaseModel):
    items: list[AnalysisComparisonRead]
    total: int
    limit: int
    offset: int
