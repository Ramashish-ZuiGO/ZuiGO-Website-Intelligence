import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

json_type = JSON().with_variant(JSONB(), "postgresql")
COMPARISON_STATUSES = ("completed", "partial", "failed", "unavailable")
COMPARISON_ARTIFACT_FORMATS = ("html", "pdf", "json")


class AnalysisComparison(Base):
    __tablename__ = "analysis_comparisons"
    __table_args__ = (
        UniqueConstraint("comparison_id", name="uq_analysis_comparisons_comparison_id"),
        UniqueConstraint(
            "baseline_analysis_run_id",
            "current_analysis_run_id",
            "idempotency_key",
            name="uq_analysis_comparisons_pair_idempotency",
        ),
        CheckConstraint(
            "baseline_analysis_run_id <> current_analysis_run_id",
            name="ck_analysis_comparisons_distinct_runs",
        ),
        CheckConstraint(
            f"status IN ({', '.join(repr(item) for item in COMPARISON_STATUSES)})",
            name="ck_analysis_comparisons_status",
        ),
        Index(
            "ix_analysis_comparisons_website_created",
            "website_id",
            "created_at",
        ),
        Index(
            "ix_analysis_comparisons_current_created",
            "current_analysis_run_id",
            "created_at",
        ),
        Index(
            "ix_analysis_comparisons_baseline_created",
            "baseline_analysis_run_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    comparison_id: Mapped[uuid.UUID] = mapped_column(default=uuid.uuid4, nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    website_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("websites.id", ondelete="CASCADE"), nullable=False
    )
    baseline_analysis_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    current_analysis_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    comparison_version: Mapped[str] = mapped_column(String(50), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    result_payload: Mapped[dict[str, Any]] = mapped_column(json_type, nullable=False)
    limitations: Mapped[list[str]] = mapped_column(json_type, nullable=False)
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    artifacts: Mapped[list["AnalysisComparisonArtifact"]] = relationship(
        back_populates="comparison",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AnalysisComparisonArtifact.format",
    )


class AnalysisComparisonArtifact(Base):
    __tablename__ = "analysis_comparison_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "artifact_id",
            name="uq_analysis_comparison_artifacts_artifact_id",
        ),
        UniqueConstraint(
            "comparison_id",
            "format",
            name="uq_analysis_comparison_artifacts_format",
        ),
        CheckConstraint(
            f"format IN ({', '.join(repr(item) for item in COMPARISON_ARTIFACT_FORMATS)})",
            name="ck_analysis_comparison_artifacts_format",
        ),
        Index("ix_analysis_comparison_artifacts_comparison", "comparison_id"),
        Index("ix_analysis_comparison_artifacts_checksum", "checksum_sha256"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    artifact_id: Mapped[uuid.UUID] = mapped_column(default=uuid.uuid4, nullable=False)
    comparison_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_comparisons.id", ondelete="CASCADE"), nullable=False
    )
    format: Mapped[str] = mapped_column(String(20), nullable=False)
    media_type: Mapped[str] = mapped_column(String(100), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    comparison: Mapped[AnalysisComparison] = relationship(back_populates="artifacts")
