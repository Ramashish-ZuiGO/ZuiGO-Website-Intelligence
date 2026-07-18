import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.analysis_run import AnalysisStatus


class AnalysisResultSummary(BaseModel):
    final_url: str
    http_status_code: int | None
    page_title: str | None
    performance_score: int | None
    accessibility_score: int | None
    best_practices_score: int | None
    seo_score: int | None
    finding_count: int


class AnalysisRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    website_id: uuid.UUID
    status: AnalysisStatus
    progress_percent: int
    current_step: str | None
    started_at: datetime | None
    completed_at: datetime | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    result_summary: AnalysisResultSummary | None = None
