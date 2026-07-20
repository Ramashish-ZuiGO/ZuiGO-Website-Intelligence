import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.analysis_diagnostic import AnalysisDiagnostic
    from app.models.analysis_finding import AnalysisFinding
    from app.models.analysis_interpretation import AnalysisInterpretation
    from app.models.analysis_result import AnalysisResult
    from app.models.analysis_score import AnalysisScore
    from app.models.website import Website


class AnalysisStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    __table_args__ = (
        CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100",
            name="ck_analysis_runs_progress_percent_range",
        ),
        Index("ix_analysis_runs_status", "status"),
        Index("ix_analysis_runs_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    website_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("websites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[AnalysisStatus] = mapped_column(
        Enum(
            AnalysisStatus,
            name="analysis_run_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum_type: [item.value for item in enum_type],
        ),
        default=AnalysisStatus.QUEUED,
        nullable=False,
    )
    progress_percent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    current_step: Mapped[str | None] = mapped_column(String(200))
    celery_task_id: Mapped[str | None] = mapped_column(String(255))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    website: Mapped["Website"] = relationship(back_populates="analysis_runs")
    result: Mapped["AnalysisResult | None"] = relationship(
        back_populates="analysis_run", cascade="all, delete-orphan", passive_deletes=True
    )
    score: Mapped["AnalysisScore | None"] = relationship(
        back_populates="analysis_run", cascade="all, delete-orphan", passive_deletes=True
    )
    interpretation: Mapped["AnalysisInterpretation | None"] = relationship(
        back_populates="analysis_run", cascade="all, delete-orphan", passive_deletes=True
    )
    findings: Mapped[list["AnalysisFinding"]] = relationship(
        back_populates="analysis_run", cascade="all, delete-orphan", passive_deletes=True
    )
    diagnostics: Mapped[list["AnalysisDiagnostic"]] = relationship(
        back_populates="analysis_run", cascade="all, delete-orphan", passive_deletes=True
    )
