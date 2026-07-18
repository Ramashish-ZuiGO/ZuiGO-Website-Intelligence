import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.analysis_run import AnalysisStatus


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
