import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.analysis_run import AnalysisRun

json_type = JSON().with_variant(JSONB(), "postgresql")


class AnalysisScore(Base):
    __tablename__ = "analysis_scores"
    __table_args__ = (
        CheckConstraint("overall_score BETWEEN 0 AND 100", name="ck_analysis_scores_overall"),
        CheckConstraint(
            "performance_score BETWEEN 0 AND 100", name="ck_analysis_scores_performance"
        ),
        CheckConstraint(
            "accessibility_score BETWEEN 0 AND 100",
            name="ck_analysis_scores_accessibility",
        ),
        CheckConstraint(
            "best_practices_score BETWEEN 0 AND 100",
            name="ck_analysis_scores_best_practices",
        ),
        CheckConstraint("seo_score BETWEEN 0 AND 100", name="ck_analysis_scores_seo"),
        CheckConstraint(
            "technical_quality_score BETWEEN 0 AND 100",
            name="ck_analysis_scores_technical_quality",
        ),
        CheckConstraint(
            "confidence_percent BETWEEN 0 AND 100",
            name="ck_analysis_scores_confidence",
        ),
        Index("ix_analysis_scores_analysis_run_id", "analysis_run_id", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    analysis_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    formula_version: Mapped[str] = mapped_column(String(50), nullable=False)
    overall_score: Mapped[int | None] = mapped_column(Integer)
    performance_score: Mapped[int | None] = mapped_column(Integer)
    accessibility_score: Mapped[int | None] = mapped_column(Integer)
    best_practices_score: Mapped[int | None] = mapped_column(Integer)
    seo_score: Mapped[int | None] = mapped_column(Integer)
    technical_quality_score: Mapped[int | None] = mapped_column(Integer)
    confidence_percent: Mapped[int] = mapped_column(Integer, nullable=False)
    available_categories: Mapped[list[str]] = mapped_column(json_type, nullable=False)
    unavailable_categories: Mapped[list[str]] = mapped_column(json_type, nullable=False)
    weights: Mapped[dict[str, int]] = mapped_column(json_type, nullable=False)
    deductions: Mapped[list[dict[str, Any]]] = mapped_column(json_type, nullable=False)
    calculation_details: Mapped[dict[str, Any]] = mapped_column(json_type, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    analysis_run: Mapped["AnalysisRun"] = relationship(back_populates="score")
