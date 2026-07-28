import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

json_type = JSON().with_variant(JSONB(), "postgresql")
SCORE_STATUSES = ("pending", "running", "completed", "partial", "failed", "unavailable")
STATUS_SQL = "', '".join(SCORE_STATUSES)


class ScoreExecution(Base):
    __tablename__ = "score_executions"
    __table_args__ = (
        UniqueConstraint("execution_id", name="uq_score_executions_execution_id"),
        UniqueConstraint(
            "analysis_run_id",
            "formula_id",
            "formula_version",
            "idempotency_key",
            name="uq_score_executions_run_formula_idempotency",
        ),
        CheckConstraint(f"status IN ('{STATUS_SQL}')", name="ck_score_executions_status"),
        CheckConstraint(
            "overall_score IS NULL OR overall_score BETWEEN 0 AND 100",
            name="ck_score_executions_overall",
        ),
        CheckConstraint(
            "confidence_percent IS NULL OR confidence_percent BETWEEN 0 AND 100",
            name="ck_score_executions_confidence",
        ),
        CheckConstraint(
            "evidence_coverage_percentage IS NULL OR "
            "evidence_coverage_percentage BETWEEN 0 AND 100",
            name="ck_score_executions_coverage",
        ),
        CheckConstraint(
            "evidence_coverage_numerator >= 0 AND evidence_coverage_denominator >= 0 "
            "AND evidence_coverage_numerator <= evidence_coverage_denominator",
            name="ck_score_executions_coverage_counts",
        ),
        Index("ix_score_executions_run_created", "analysis_run_id", "created_at"),
        Index("ix_score_executions_website_created", "website_id", "created_at"),
        Index("ix_score_executions_project_status", "project_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    execution_id: Mapped[uuid.UUID] = mapped_column(default=uuid.uuid4, nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    website_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("websites.id", ondelete="CASCADE"), nullable=False
    )
    analysis_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    formula_id: Mapped[str] = mapped_column(String(100), nullable=False)
    formula_version: Mapped[str] = mapped_column(String(50), nullable=False)
    scoring_profile_id: Mapped[str] = mapped_column(String(100), nullable=False)
    scoring_profile_version: Mapped[str] = mapped_column(String(50), nullable=False)
    metric_registry_version: Mapped[str] = mapped_column(String(50), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50), default="pending", server_default="pending", nullable=False
    )
    overall_score: Mapped[int | None] = mapped_column(Integer)
    confidence_percent: Mapped[int | None] = mapped_column(Integer)
    confidence_classification: Mapped[str] = mapped_column(String(50), nullable=False)
    evidence_coverage_numerator: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_coverage_denominator: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_coverage_percentage: Mapped[float | None] = mapped_column(Float)
    unavailable_metrics: Mapped[list[str]] = mapped_column(json_type, default=list, nullable=False)
    excluded_metrics: Mapped[list[dict[str, Any]]] = mapped_column(
        json_type, default=list, nullable=False
    )
    failure_details: Mapped[dict[str, Any]] = mapped_column(json_type, default=dict, nullable=False)
    partial_completion_details: Mapped[dict[str, Any]] = mapped_column(
        json_type, default=dict, nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    snapshot: Mapped["ScoreSnapshot | None"] = relationship(
        back_populates="execution", cascade="all, delete-orphan", passive_deletes=True
    )
    categories: Mapped[list["CategoryScore"]] = relationship(
        back_populates="execution",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CategoryScore.category_id",
    )
    contributions: Mapped[list["MetricContribution"]] = relationship(
        back_populates="execution",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="MetricContribution.metric_id",
    )
    explanation: Mapped["ScoreExplanation | None"] = relationship(
        back_populates="execution", cascade="all, delete-orphan", passive_deletes=True
    )


class ScoreSnapshot(Base):
    __tablename__ = "score_snapshots"
    __table_args__ = (
        UniqueConstraint("snapshot_id", name="uq_score_snapshots_snapshot_id"),
        UniqueConstraint("score_execution_id", name="uq_score_snapshots_execution"),
        CheckConstraint(
            "overall_score IS NULL OR overall_score BETWEEN 0 AND 100",
            name="ck_score_snapshots_overall",
        ),
        Index("ix_score_snapshots_created", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(default=uuid.uuid4, nullable=False)
    score_execution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("score_executions.id", ondelete="CASCADE"), nullable=False
    )
    overall_score: Mapped[int | None] = mapped_column(Integer)
    category_scores: Mapped[dict[str, int | None]] = mapped_column(json_type, nullable=False)
    confidence_percent: Mapped[int | None] = mapped_column(Integer)
    evidence_coverage_percentage: Mapped[float | None] = mapped_column(Float)
    unavailable_metrics: Mapped[list[str]] = mapped_column(json_type, nullable=False)
    excluded_metrics: Mapped[list[dict[str, Any]]] = mapped_column(json_type, nullable=False)
    evidence_references: Mapped[list[dict[str, Any]]] = mapped_column(json_type, nullable=False)
    calculation_details: Mapped[dict[str, Any]] = mapped_column(json_type, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    execution: Mapped[ScoreExecution] = relationship(back_populates="snapshot")


class CategoryScore(Base):
    __tablename__ = "category_scores"
    __table_args__ = (
        UniqueConstraint(
            "score_execution_id", "category_id", name="uq_category_scores_execution_category"
        ),
        CheckConstraint(
            "raw_score IS NULL OR raw_score BETWEEN 0 AND 100",
            name="ck_category_scores_raw",
        ),
        CheckConstraint(
            "final_score IS NULL OR final_score BETWEEN 0 AND 100",
            name="ck_category_scores_final",
        ),
        Index("ix_category_scores_execution", "score_execution_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    score_execution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("score_executions.id", ondelete="CASCADE"), nullable=False
    )
    category_id: Mapped[str] = mapped_column(String(100), nullable=False)
    raw_score: Mapped[int | None] = mapped_column(Integer)
    final_score: Mapped[int | None] = mapped_column(Integer)
    configured_weight: Mapped[float] = mapped_column(Float, nullable=False)
    normalized_weight: Mapped[float | None] = mapped_column(Float)
    contribution: Mapped[float | None] = mapped_column(Float)
    band: Mapped[str] = mapped_column(String(50), nullable=False)
    included: Mapped[bool] = mapped_column(nullable=False)
    exclusion_reason: Mapped[str | None] = mapped_column(String(255))
    thresholds: Mapped[dict[str, Any]] = mapped_column(json_type, nullable=False)
    deductions: Mapped[list[dict[str, Any]]] = mapped_column(json_type, nullable=False)
    adjustments: Mapped[list[dict[str, Any]]] = mapped_column(json_type, nullable=False)
    evidence_references: Mapped[list[dict[str, Any]]] = mapped_column(json_type, nullable=False)
    execution: Mapped[ScoreExecution] = relationship(back_populates="categories")


class MetricContribution(Base):
    __tablename__ = "metric_contributions"
    __table_args__ = (
        UniqueConstraint(
            "score_execution_id", "metric_id", name="uq_metric_contributions_execution_metric"
        ),
        Index("ix_metric_contributions_execution", "score_execution_id"),
        Index("ix_metric_contributions_metric", "metric_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    score_execution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("score_executions.id", ondelete="CASCADE"), nullable=False
    )
    category_score_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("category_scores.id", ondelete="SET NULL")
    )
    metric_id: Mapped[str] = mapped_column(String(100), nullable=False)
    raw_value: Mapped[dict[str, Any]] = mapped_column(json_type, nullable=False)
    normalized_value: Mapped[float | None] = mapped_column(Float)
    configured_weight: Mapped[float] = mapped_column(Float, nullable=False)
    normalized_weight: Mapped[float | None] = mapped_column(Float)
    contribution: Mapped[float | None] = mapped_column(Float)
    inclusion_status: Mapped[str] = mapped_column(String(50), nullable=False)
    exclusion_reason: Mapped[str | None] = mapped_column(String(255))
    threshold_decision: Mapped[dict[str, Any]] = mapped_column(json_type, nullable=False)
    deduction_or_adjustment: Mapped[dict[str, Any]] = mapped_column(json_type, nullable=False)
    evidence_references: Mapped[list[dict[str, Any]]] = mapped_column(json_type, nullable=False)
    execution: Mapped[ScoreExecution] = relationship(back_populates="contributions")


class ScoreExplanation(Base):
    __tablename__ = "score_explanations"
    __table_args__ = (
        UniqueConstraint("score_execution_id", name="uq_score_explanations_execution"),
        Index("ix_score_explanations_created", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    score_execution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("score_executions.id", ondelete="CASCADE"), nullable=False
    )
    formula_summary: Mapped[str] = mapped_column(Text, nullable=False)
    profile_summary: Mapped[str] = mapped_column(Text, nullable=False)
    normalization_decisions: Mapped[list[dict[str, Any]]] = mapped_column(json_type, nullable=False)
    caps_floors_deductions: Mapped[list[dict[str, Any]]] = mapped_column(json_type, nullable=False)
    limitations: Mapped[list[str]] = mapped_column(json_type, nullable=False)
    reproducibility_payload: Mapped[dict[str, Any]] = mapped_column(json_type, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    execution: Mapped[ScoreExecution] = relationship(back_populates="explanation")
