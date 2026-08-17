from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class BrowserUatTier0StartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=255)

    @field_validator("idempotency_key")
    @classmethod
    def normalize_key(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Idempotency key cannot be empty")
        return normalized


class BrowserUatTier0ExecutionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    execution_id: UUID
    website_id: UUID
    analysis_run_id: UUID
    lane: str
    status: str
    attempt: int
    requested_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class BrowserUatTier0ViewportResultRead(BaseModel):
    """Real per-viewport M3 structural evidence (responsive_assertions.js's
    output shape) -- see fetch_latest_tier0_structural_results, which builds
    the plain dicts this model validates from."""

    model_config = ConfigDict(from_attributes=True)

    viewport_name: str
    viewport_width: int
    viewport_height: int
    horizontal_overflow: bool | None
    critical_elements_outside_viewport: int
    overlapping_elements: int
    small_tap_targets: int
    tap_target_samples: list[dict[str, Any]]


class BrowserUatTier0PageResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    page_result_id: UUID
    url: str
    browser_channel: str
    platform: str
    browser_version: str | None
    status: str
    error_message: str | None
    viewport_results: list[BrowserUatTier0ViewportResultRead]


class BrowserUatTier0ResultsRead(BaseModel):
    """Structural results from the most recent usable Tier 0 execution for
    an analysis run -- empty page_results means no usable execution exists
    yet (still pending/running, or none has been requested), which is
    distinct from a 404: the analysis run is real, there's simply no
    evidence to show yet. Callers should check GET .../tier0 for execution
    status separately to tell those two cases apart."""

    page_results: list[BrowserUatTier0PageResultRead]
