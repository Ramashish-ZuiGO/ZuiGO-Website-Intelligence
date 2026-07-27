import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    Boolean,
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
EXECUTION_STATUS_VALUES = (
    "pending",
    "running",
    "completed",
    "partial",
    "failed",
    "cancelled",
    "unavailable",
)
STATUS_VALUES = "', '".join(EXECUTION_STATUS_VALUES)
DEFAULT_EXECUTION_STATUS = "pending"

if TYPE_CHECKING:
    from app.models.analysis_run import AnalysisRun
    from app.models.project import Project


class AgentExecution(Base):
    __tablename__ = "agent_executions"
    __table_args__ = (
        UniqueConstraint("execution_id", name="uq_agent_executions_execution_id"),
        UniqueConstraint(
            "project_id",
            "workflow_id",
            "workflow_version",
            "idempotency_key",
            name="uq_agent_executions_project_workflow_idempotency",
        ),
        CheckConstraint(f"status IN ('{STATUS_VALUES}')", name="ck_agent_executions_status"),
        CheckConstraint("attempt >= 1", name="ck_agent_executions_attempt"),
        CheckConstraint("token_total >= 0", name="ck_agent_executions_token_total"),
        CheckConstraint("cost_total_usd >= 0", name="ck_agent_executions_cost_total"),
        Index("ix_agent_executions_project_created", "project_id", "created_at"),
        Index("ix_agent_executions_analysis_run", "analysis_run_id"),
        Index("ix_agent_executions_workflow_status", "workflow_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    execution_id: Mapped[uuid.UUID] = mapped_column(default=uuid.uuid4, nullable=False)
    workflow_id: Mapped[str] = mapped_column(String(100), nullable=False)
    workflow_version: Mapped[str] = mapped_column(String(50), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    analysis_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="SET NULL")
    )
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50),
        default=DEFAULT_EXECUTION_STATUS,
        server_default=DEFAULT_EXECUTION_STATUS,
        nullable=False,
    )
    attempt: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    structured_input: Mapped[dict[str, Any]] = mapped_column(
        json_type, default=dict, nullable=False
    )
    structured_output: Mapped[dict[str, Any]] = mapped_column(
        json_type, default=dict, nullable=False
    )
    evidence_references: Mapped[list[dict[str, Any]]] = mapped_column(
        json_type, default=list, nullable=False
    )
    provider_version_metadata: Mapped[dict[str, Any]] = mapped_column(
        json_type, default=dict, nullable=False
    )
    token_total: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    cost_total_usd: Mapped[float] = mapped_column(
        Float, default=0.0, server_default="0", nullable=False
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

    project: Mapped["Project"] = relationship()
    analysis_run: Mapped["AnalysisRun | None"] = relationship()
    runs: Mapped[list["AgentRun"]] = relationship(
        back_populates="execution",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AgentRun.created_at",
    )
    events: Mapped[list["AgentEvent"]] = relationship(
        back_populates="execution",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AgentEvent.sequence_number",
    )
    artifacts: Mapped[list["AgentArtifact"]] = relationship(
        back_populates="execution",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AgentArtifact.created_at",
    )
    checkpoints: Mapped[list["AgentCheckpoint"]] = relationship(
        back_populates="execution",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AgentCheckpoint.created_at",
    )


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        UniqueConstraint("agent_run_id", name="uq_agent_runs_agent_run_id"),
        UniqueConstraint(
            "execution_id",
            "agent_id",
            "idempotency_key",
            "attempt",
            name="uq_agent_runs_execution_agent_idempotency_attempt",
        ),
        CheckConstraint(f"status IN ('{STATUS_VALUES}')", name="ck_agent_runs_status"),
        CheckConstraint("attempt >= 1", name="ck_agent_runs_attempt"),
        CheckConstraint("token_total >= 0", name="ck_agent_runs_token_total"),
        CheckConstraint("cost_total_usd >= 0", name="ck_agent_runs_cost_total"),
        Index("ix_agent_runs_execution_created", "execution_id", "created_at"),
        Index("ix_agent_runs_agent_status", "agent_id", "status"),
        Index("ix_agent_runs_parent", "parent_agent_run_id"),
        Index("ix_agent_runs_dependency", "dependency_agent_run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    agent_run_id: Mapped[uuid.UUID] = mapped_column(default=uuid.uuid4, nullable=False)
    execution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_executions.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[str] = mapped_column(String(100), nullable=False)
    agent_version: Mapped[str] = mapped_column(String(50), nullable=False)
    parent_agent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL")
    )
    dependency_agent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL")
    )
    dependency_agent_run_ids: Mapped[list[str]] = mapped_column(
        json_type, default=list, nullable=False
    )
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50),
        default=DEFAULT_EXECUTION_STATUS,
        server_default=DEFAULT_EXECUTION_STATUS,
        nullable=False,
    )
    attempt: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    structured_input: Mapped[dict[str, Any]] = mapped_column(
        json_type, default=dict, nullable=False
    )
    structured_output: Mapped[dict[str, Any]] = mapped_column(
        json_type, default=dict, nullable=False
    )
    tool_activity_summary: Mapped[list[dict[str, Any]]] = mapped_column(
        json_type, default=list, nullable=False
    )
    evidence_references: Mapped[list[dict[str, Any]]] = mapped_column(
        json_type, default=list, nullable=False
    )
    provider_version_metadata: Mapped[dict[str, Any]] = mapped_column(
        json_type, default=dict, nullable=False
    )
    token_total: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    cost_total_usd: Mapped[float] = mapped_column(
        Float, default=0.0, server_default="0", nullable=False
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

    execution: Mapped["AgentExecution"] = relationship(back_populates="runs")
    parent_run: Mapped["AgentRun | None"] = relationship(
        remote_side="AgentRun.id",
        foreign_keys=[parent_agent_run_id],
    )
    dependency_run: Mapped["AgentRun | None"] = relationship(
        remote_side="AgentRun.id",
        foreign_keys=[dependency_agent_run_id],
    )
    steps: Mapped[list["AgentStep"]] = relationship(
        back_populates="agent_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AgentStep.sequence_number",
    )
    events: Mapped[list["AgentEvent"]] = relationship(back_populates="agent_run")
    artifacts: Mapped[list["AgentArtifact"]] = relationship(back_populates="agent_run")
    checkpoints: Mapped[list["AgentCheckpoint"]] = relationship(back_populates="agent_run")


class AgentStep(Base):
    __tablename__ = "agent_steps"
    __table_args__ = (
        UniqueConstraint("step_id", name="uq_agent_steps_step_id"),
        UniqueConstraint(
            "agent_run_id",
            "sequence_number",
            "attempt",
            name="uq_agent_steps_run_sequence_attempt",
        ),
        CheckConstraint(f"status IN ('{STATUS_VALUES}')", name="ck_agent_steps_status"),
        CheckConstraint("sequence_number >= 0", name="ck_agent_steps_sequence"),
        CheckConstraint("attempt >= 1", name="ck_agent_steps_attempt"),
        Index("ix_agent_steps_run_status", "agent_run_id", "status"),
        Index("ix_agent_steps_tool", "tool_id"),
        Index("ix_agent_steps_dependency", "dependency_step_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    step_id: Mapped[uuid.UUID] = mapped_column(default=uuid.uuid4, nullable=False)
    agent_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    dependency_step_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_steps.id", ondelete="SET NULL")
    )
    step_name: Mapped[str] = mapped_column(String(255), nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_id: Mapped[str | None] = mapped_column(String(100))
    tool_version: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(
        String(50),
        default=DEFAULT_EXECUTION_STATUS,
        server_default=DEFAULT_EXECUTION_STATUS,
        nullable=False,
    )
    attempt: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    structured_input: Mapped[dict[str, Any]] = mapped_column(
        json_type, default=dict, nullable=False
    )
    structured_output: Mapped[dict[str, Any]] = mapped_column(
        json_type, default=dict, nullable=False
    )
    tool_activity_summary: Mapped[dict[str, Any]] = mapped_column(
        json_type, default=dict, nullable=False
    )
    evidence_references: Mapped[list[dict[str, Any]]] = mapped_column(
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

    agent_run: Mapped["AgentRun"] = relationship(back_populates="steps")
    dependency_step: Mapped["AgentStep | None"] = relationship(
        remote_side="AgentStep.id",
        foreign_keys=[dependency_step_id],
    )
    events: Mapped[list["AgentEvent"]] = relationship(back_populates="agent_step")
    artifacts: Mapped[list["AgentArtifact"]] = relationship(back_populates="agent_step")
    checkpoints: Mapped[list["AgentCheckpoint"]] = relationship(back_populates="agent_step")


class AgentEvent(Base):
    __tablename__ = "agent_events"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_agent_events_event_id"),
        UniqueConstraint(
            "execution_id",
            "sequence_number",
            name="uq_agent_events_execution_sequence",
        ),
        CheckConstraint(f"status IN ('{STATUS_VALUES}')", name="ck_agent_events_status"),
        CheckConstraint("sequence_number >= 0", name="ck_agent_events_sequence"),
        Index("ix_agent_events_execution_created", "execution_id", "created_at"),
        Index("ix_agent_events_run", "agent_run_id"),
        Index("ix_agent_events_step", "agent_step_id"),
        Index("ix_agent_events_type", "event_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(default=uuid.uuid4, nullable=False)
    execution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_executions.id", ondelete="CASCADE"), nullable=False
    )
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL")
    )
    agent_step_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_steps.id", ondelete="SET NULL")
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    structured_payload: Mapped[dict[str, Any]] = mapped_column(
        json_type, default=dict, nullable=False
    )
    evidence_references: Mapped[list[dict[str, Any]]] = mapped_column(
        json_type, default=list, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    execution: Mapped["AgentExecution"] = relationship(back_populates="events")
    agent_run: Mapped["AgentRun | None"] = relationship(back_populates="events")
    agent_step: Mapped["AgentStep | None"] = relationship(back_populates="events")


class AgentArtifact(Base):
    __tablename__ = "agent_artifacts"
    __table_args__ = (
        UniqueConstraint("artifact_id", name="uq_agent_artifacts_artifact_id"),
        UniqueConstraint(
            "execution_id",
            "artifact_type",
            "content_hash",
            name="uq_agent_artifacts_execution_type_hash",
        ),
        Index("ix_agent_artifacts_execution_created", "execution_id", "created_at"),
        Index("ix_agent_artifacts_run", "agent_run_id"),
        Index("ix_agent_artifacts_step", "agent_step_id"),
        Index("ix_agent_artifacts_storage_reference", "storage_reference"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    artifact_id: Mapped[uuid.UUID] = mapped_column(default=uuid.uuid4, nullable=False)
    execution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_executions.id", ondelete="CASCADE"), nullable=False
    )
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL")
    )
    agent_step_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_steps.id", ondelete="SET NULL")
    )
    artifact_type: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_reference: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    media_type: Mapped[str] = mapped_column(String(255), nullable=False)
    artifact_metadata: Mapped[dict[str, Any]] = mapped_column(
        json_type, default=dict, nullable=False
    )
    evidence_references: Mapped[list[dict[str, Any]]] = mapped_column(
        json_type, default=list, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    execution: Mapped["AgentExecution"] = relationship(back_populates="artifacts")
    agent_run: Mapped["AgentRun | None"] = relationship(back_populates="artifacts")
    agent_step: Mapped["AgentStep | None"] = relationship(back_populates="artifacts")


class AgentCheckpoint(Base):
    __tablename__ = "agent_checkpoints"
    __table_args__ = (
        UniqueConstraint("checkpoint_id", name="uq_agent_checkpoints_checkpoint_id"),
        UniqueConstraint(
            "agent_run_id",
            "checkpoint_version",
            name="uq_agent_checkpoints_run_version",
        ),
        CheckConstraint(f"status IN ('{STATUS_VALUES}')", name="ck_agent_checkpoints_status"),
        CheckConstraint("checkpoint_version >= 1", name="ck_agent_checkpoints_version"),
        Index("ix_agent_checkpoints_execution_created", "execution_id", "created_at"),
        Index("ix_agent_checkpoints_run_created", "agent_run_id", "created_at"),
        Index("ix_agent_checkpoints_step", "agent_step_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    checkpoint_id: Mapped[uuid.UUID] = mapped_column(default=uuid.uuid4, nullable=False)
    execution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_executions.id", ondelete="CASCADE"), nullable=False
    )
    agent_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    agent_step_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_steps.id", ondelete="SET NULL")
    )
    checkpoint_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    resumable: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    state_summary: Mapped[dict[str, Any]] = mapped_column(json_type, default=dict, nullable=False)
    evidence_references: Mapped[list[dict[str, Any]]] = mapped_column(
        json_type, default=list, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    execution: Mapped["AgentExecution"] = relationship(back_populates="checkpoints")
    agent_run: Mapped["AgentRun"] = relationship(back_populates="checkpoints")
    agent_step: Mapped["AgentStep | None"] = relationship(back_populates="checkpoints")
