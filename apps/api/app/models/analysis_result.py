import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.analysis_run import AnalysisRun

json_type = JSON().with_variant(JSONB(), "postgresql")


class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    analysis_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    requested_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    final_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    http_status_code: Mapped[int | None] = mapped_column(Integer)
    page_title: Mapped[str | None] = mapped_column(Text)
    meta_description: Mapped[str | None] = mapped_column(Text)
    lighthouse_version: Mapped[str | None] = mapped_column(String(50))
    user_agent: Mapped[str | None] = mapped_column(Text)
    analysis_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    analysis_completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_lighthouse_data: Mapped[dict[str, Any]] = mapped_column(json_type, nullable=False)
    raw_playwright_data: Mapped[dict[str, Any]] = mapped_column(json_type, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    analysis_run: Mapped["AnalysisRun"] = relationship(back_populates="result")
