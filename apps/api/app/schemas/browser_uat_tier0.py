from datetime import datetime
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
