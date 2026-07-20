import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.analysis_run import AnalysisRun

json_type = JSON().with_variant(JSONB(), "postgresql")


class AnalysisInterpretation(Base):
    __tablename__ = "analysis_interpretations"
    __table_args__ = (
        CheckConstraint(
            "generation_mode IN ('ai', 'deterministic_fallback')",
            name="ck_analysis_interpretations_generation_mode",
        ),
        Index("ix_analysis_interpretations_analysis_run_id", "analysis_run_id", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    analysis_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    generation_mode: Mapped[str] = mapped_column(String(30), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=False)
    executive_summary: Mapped[str] = mapped_column(Text, nullable=False)
    overall_assessment: Mapped[str] = mapped_column(Text, nullable=False)
    strengths: Mapped[list[dict[str, Any]]] = mapped_column(json_type, nullable=False)
    weaknesses: Mapped[list[dict[str, Any]]] = mapped_column(json_type, nullable=False)
    priority_recommendations: Mapped[list[dict[str, Any]]] = mapped_column(
        json_type, nullable=False
    )
    action_plan: Mapped[list[dict[str, Any]]] = mapped_column(json_type, nullable=False)
    limitations: Mapped[list[str]] = mapped_column(json_type, nullable=False)
    fallback_reason: Mapped[str | None] = mapped_column(String(100))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    analysis_run: Mapped["AnalysisRun"] = relationship(back_populates="interpretation")
