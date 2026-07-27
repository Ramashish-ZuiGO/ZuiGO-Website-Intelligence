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
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

json_type = JSON().with_variant(JSONB(), "postgresql")
REPORT_STATUSES = ("pending", "running", "completed", "partial", "failed", "unavailable")
SECTION_STATUSES = ("passed", "failed", "available", "unavailable", "incomplete", "excluded")
ARTIFACT_FORMATS = ("html", "pdf", "json")


class ReportExecution(Base):
    __tablename__ = "report_executions"
    __table_args__ = (
        UniqueConstraint("report_id", name="uq_report_executions_report_id"),
        UniqueConstraint(
            "analysis_run_id",
            "report_type",
            "report_version",
            "idempotency_key",
            name="uq_report_executions_run_type_idempotency",
        ),
        CheckConstraint(
            f"status IN ({', '.join(repr(item) for item in REPORT_STATUSES)})",
            name="ck_report_executions_status",
        ),
        CheckConstraint(
            "confidence_percent IS NULL OR confidence_percent BETWEEN 0 AND 100",
            name="ck_report_executions_confidence",
        ),
        CheckConstraint(
            "evidence_coverage_percentage IS NULL OR "
            "evidence_coverage_percentage BETWEEN 0 AND 100",
            name="ck_report_executions_coverage",
        ),
        CheckConstraint(
            "evidence_coverage_numerator >= 0 AND evidence_coverage_denominator >= 0 "
            "AND evidence_coverage_numerator <= evidence_coverage_denominator",
            name="ck_report_executions_coverage_counts",
        ),
        Index("ix_report_executions_run_created", "analysis_run_id", "created_at"),
        Index("ix_report_executions_website_created", "website_id", "created_at"),
        Index("ix_report_executions_project_status", "project_id", "status"),
        Index("ix_report_executions_workflow", "workflow_execution_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    report_id: Mapped[uuid.UUID] = mapped_column(default=uuid.uuid4, nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    website_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("websites.id", ondelete="CASCADE"), nullable=False
    )
    analysis_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    workflow_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_executions.id", ondelete="SET NULL")
    )
    score_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("score_executions.id", ondelete="SET NULL")
    )
    report_type: Mapped[str] = mapped_column(String(100), nullable=False)
    report_version: Mapped[str] = mapped_column(String(50), nullable=False)
    template_id: Mapped[str] = mapped_column(String(100), nullable=False)
    template_version: Mapped[str] = mapped_column(String(50), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50), default="pending", server_default="pending", nullable=False
    )
    evidence_coverage_numerator: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    evidence_coverage_denominator: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    evidence_coverage_percentage: Mapped[float | None] = mapped_column(Float)
    confidence_percent: Mapped[int | None] = mapped_column(Integer)
    unavailable_sections: Mapped[list[str]] = mapped_column(json_type, default=list, nullable=False)
    provider_version_metadata: Mapped[dict[str, Any]] = mapped_column(
        json_type, default=dict, nullable=False
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

    snapshot: Mapped["ReportSnapshot | None"] = relationship(
        back_populates="execution",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )
    sections: Mapped[list["ReportSection"]] = relationship(
        back_populates="execution",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ReportSection.position",
    )
    artifacts: Mapped[list["ReportArtifact"]] = relationship(
        back_populates="execution",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ReportArtifact.format",
    )


class ReportSnapshot(Base):
    __tablename__ = "report_snapshots"
    __table_args__ = (
        UniqueConstraint("snapshot_id", name="uq_report_snapshots_snapshot_id"),
        UniqueConstraint("report_execution_id", name="uq_report_snapshots_execution"),
        Index("ix_report_snapshots_created", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(default=uuid.uuid4, nullable=False)
    report_execution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("report_executions.id", ondelete="CASCADE"), nullable=False
    )
    snapshot_payload: Mapped[dict[str, Any]] = mapped_column(json_type, nullable=False)
    evidence_references: Mapped[list[dict[str, Any]]] = mapped_column(json_type, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    execution: Mapped[ReportExecution] = relationship(back_populates="snapshot")


class ReportSection(Base):
    __tablename__ = "report_sections"
    __table_args__ = (
        UniqueConstraint("section_id", name="uq_report_sections_section_id"),
        UniqueConstraint(
            "report_execution_id", "section_key", name="uq_report_sections_execution_key"
        ),
        UniqueConstraint(
            "report_execution_id", "position", name="uq_report_sections_execution_position"
        ),
        CheckConstraint("position >= 1", name="ck_report_sections_position"),
        CheckConstraint(
            f"status IN ({', '.join(repr(item) for item in SECTION_STATUSES)})",
            name="ck_report_sections_status",
        ),
        Index("ix_report_sections_execution", "report_execution_id"),
        Index("ix_report_sections_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    section_id: Mapped[uuid.UUID] = mapped_column(default=uuid.uuid4, nullable=False)
    report_execution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("report_executions.id", ondelete="CASCADE"), nullable=False
    )
    section_key: Mapped[str] = mapped_column(String(100), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(json_type, nullable=False)
    evidence_references: Mapped[list[dict[str, Any]]] = mapped_column(json_type, nullable=False)
    unavailable_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    execution: Mapped[ReportExecution] = relationship(back_populates="sections")


class ReportArtifact(Base):
    __tablename__ = "report_artifacts"
    __table_args__ = (
        UniqueConstraint("artifact_id", name="uq_report_artifacts_artifact_id"),
        UniqueConstraint(
            "report_execution_id", "format", name="uq_report_artifacts_execution_format"
        ),
        CheckConstraint(
            f"format IN ({', '.join(repr(item) for item in ARTIFACT_FORMATS)})",
            name="ck_report_artifacts_format",
        ),
        CheckConstraint("size_bytes >= 0", name="ck_report_artifacts_size"),
        Index("ix_report_artifacts_execution", "report_execution_id"),
        Index("ix_report_artifacts_checksum", "checksum_sha256"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    artifact_id: Mapped[uuid.UUID] = mapped_column(default=uuid.uuid4, nullable=False)
    report_execution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("report_executions.id", ondelete="CASCADE"), nullable=False
    )
    format: Mapped[str] = mapped_column(String(20), nullable=False)
    media_type: Mapped[str] = mapped_column(String(100), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_location: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    execution: Mapped[ReportExecution] = relationship(back_populates="artifacts")
