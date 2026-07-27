"""Add reusable agent-platform execution persistence.

Revision ID: 20260727_0016
Revises: 20260725_0015
Create Date: 2026-07-27 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260727_0016"
down_revision: str | None = "20260725_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
STATUS_CHECK = (
    "status IN ('pending', 'running', 'completed', 'partial', 'failed', 'cancelled', 'unavailable')"
)


def upgrade() -> None:
    op.create_table(
        "agent_executions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("execution_id", sa.UUID(), nullable=False),
        sa.Column("workflow_id", sa.String(length=100), nullable=False),
        sa.Column("workflow_version", sa.String(length=50), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("analysis_run_id", sa.UUID(), nullable=True),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            sa.String(length=50),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("attempt", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("structured_input", json_type, nullable=False),
        sa.Column("structured_output", json_type, nullable=False),
        sa.Column("evidence_references", json_type, nullable=False),
        sa.Column("provider_version_metadata", json_type, nullable=False),
        sa.Column("token_total", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("cost_total_usd", sa.Float(), server_default=sa.text("0"), nullable=False),
        sa.Column("failure_details", json_type, nullable=False),
        sa.Column("partial_completion_details", json_type, nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("attempt >= 1", name="ck_agent_executions_attempt"),
        sa.CheckConstraint("cost_total_usd >= 0", name="ck_agent_executions_cost_total"),
        sa.CheckConstraint(STATUS_CHECK, name="ck_agent_executions_status"),
        sa.CheckConstraint("token_total >= 0", name="ck_agent_executions_token_total"),
        sa.ForeignKeyConstraint(["analysis_run_id"], ["analysis_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("execution_id", name="uq_agent_executions_execution_id"),
        sa.UniqueConstraint(
            "project_id",
            "workflow_id",
            "workflow_version",
            "idempotency_key",
            name="uq_agent_executions_project_workflow_idempotency",
        ),
    )
    op.create_index(
        "ix_agent_executions_analysis_run",
        "agent_executions",
        ["analysis_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_agent_executions_project_created",
        "agent_executions",
        ["project_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_agent_executions_workflow_status",
        "agent_executions",
        ["workflow_id", "status"],
        unique=False,
    )

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("agent_run_id", sa.UUID(), nullable=False),
        sa.Column("execution_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.String(length=100), nullable=False),
        sa.Column("agent_version", sa.String(length=50), nullable=False),
        sa.Column("parent_agent_run_id", sa.UUID(), nullable=True),
        sa.Column("dependency_agent_run_id", sa.UUID(), nullable=True),
        sa.Column("dependency_agent_run_ids", json_type, nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            sa.String(length=50),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("attempt", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("structured_input", json_type, nullable=False),
        sa.Column("structured_output", json_type, nullable=False),
        sa.Column("tool_activity_summary", json_type, nullable=False),
        sa.Column("evidence_references", json_type, nullable=False),
        sa.Column("provider_version_metadata", json_type, nullable=False),
        sa.Column("token_total", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("cost_total_usd", sa.Float(), server_default=sa.text("0"), nullable=False),
        sa.Column("failure_details", json_type, nullable=False),
        sa.Column("partial_completion_details", json_type, nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("attempt >= 1", name="ck_agent_runs_attempt"),
        sa.CheckConstraint("cost_total_usd >= 0", name="ck_agent_runs_cost_total"),
        sa.CheckConstraint(STATUS_CHECK, name="ck_agent_runs_status"),
        sa.CheckConstraint("token_total >= 0", name="ck_agent_runs_token_total"),
        sa.ForeignKeyConstraint(
            ["dependency_agent_run_id"], ["agent_runs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["execution_id"], ["agent_executions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_agent_run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_run_id", name="uq_agent_runs_agent_run_id"),
        sa.UniqueConstraint(
            "execution_id",
            "agent_id",
            "idempotency_key",
            "attempt",
            name="uq_agent_runs_execution_agent_idempotency_attempt",
        ),
    )
    op.create_index(
        "ix_agent_runs_agent_status",
        "agent_runs",
        ["agent_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_agent_runs_dependency",
        "agent_runs",
        ["dependency_agent_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_agent_runs_execution_created",
        "agent_runs",
        ["execution_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_agent_runs_parent",
        "agent_runs",
        ["parent_agent_run_id"],
        unique=False,
    )

    op.create_table(
        "agent_steps",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("step_id", sa.UUID(), nullable=False),
        sa.Column("agent_run_id", sa.UUID(), nullable=False),
        sa.Column("dependency_step_id", sa.UUID(), nullable=True),
        sa.Column("step_name", sa.String(length=255), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("tool_id", sa.String(length=100), nullable=True),
        sa.Column("tool_version", sa.String(length=50), nullable=True),
        sa.Column(
            "status",
            sa.String(length=50),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("attempt", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("structured_input", json_type, nullable=False),
        sa.Column("structured_output", json_type, nullable=False),
        sa.Column("tool_activity_summary", json_type, nullable=False),
        sa.Column("evidence_references", json_type, nullable=False),
        sa.Column("failure_details", json_type, nullable=False),
        sa.Column("partial_completion_details", json_type, nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("attempt >= 1", name="ck_agent_steps_attempt"),
        sa.CheckConstraint("sequence_number >= 0", name="ck_agent_steps_sequence"),
        sa.CheckConstraint(STATUS_CHECK, name="ck_agent_steps_status"),
        sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["dependency_step_id"], ["agent_steps.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("step_id", name="uq_agent_steps_step_id"),
        sa.UniqueConstraint(
            "agent_run_id",
            "sequence_number",
            "attempt",
            name="uq_agent_steps_run_sequence_attempt",
        ),
    )
    op.create_index(
        "ix_agent_steps_dependency",
        "agent_steps",
        ["dependency_step_id"],
        unique=False,
    )
    op.create_index(
        "ix_agent_steps_run_status",
        "agent_steps",
        ["agent_run_id", "status"],
        unique=False,
    )
    op.create_index("ix_agent_steps_tool", "agent_steps", ["tool_id"], unique=False)

    op.create_table(
        "agent_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("execution_id", sa.UUID(), nullable=False),
        sa.Column("agent_run_id", sa.UUID(), nullable=True),
        sa.Column("agent_step_id", sa.UUID(), nullable=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("structured_payload", json_type, nullable=False),
        sa.Column("evidence_references", json_type, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("sequence_number >= 0", name="ck_agent_events_sequence"),
        sa.CheckConstraint(STATUS_CHECK, name="ck_agent_events_status"),
        sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["agent_step_id"], ["agent_steps.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["execution_id"], ["agent_executions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", name="uq_agent_events_event_id"),
        sa.UniqueConstraint(
            "execution_id",
            "sequence_number",
            name="uq_agent_events_execution_sequence",
        ),
    )
    op.create_index(
        "ix_agent_events_execution_created",
        "agent_events",
        ["execution_id", "created_at"],
        unique=False,
    )
    op.create_index("ix_agent_events_run", "agent_events", ["agent_run_id"], unique=False)
    op.create_index("ix_agent_events_step", "agent_events", ["agent_step_id"], unique=False)
    op.create_index("ix_agent_events_type", "agent_events", ["event_type"], unique=False)

    op.create_table(
        "agent_artifacts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("artifact_id", sa.UUID(), nullable=False),
        sa.Column("execution_id", sa.UUID(), nullable=False),
        sa.Column("agent_run_id", sa.UUID(), nullable=True),
        sa.Column("agent_step_id", sa.UUID(), nullable=True),
        sa.Column("artifact_type", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("storage_reference", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("media_type", sa.String(length=255), nullable=False),
        sa.Column("artifact_metadata", json_type, nullable=False),
        sa.Column("evidence_references", json_type, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["agent_step_id"], ["agent_steps.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["execution_id"], ["agent_executions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("artifact_id", name="uq_agent_artifacts_artifact_id"),
        sa.UniqueConstraint(
            "execution_id",
            "artifact_type",
            "content_hash",
            name="uq_agent_artifacts_execution_type_hash",
        ),
    )
    op.create_index(
        "ix_agent_artifacts_execution_created",
        "agent_artifacts",
        ["execution_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_agent_artifacts_run",
        "agent_artifacts",
        ["agent_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_agent_artifacts_step",
        "agent_artifacts",
        ["agent_step_id"],
        unique=False,
    )
    op.create_index(
        "ix_agent_artifacts_storage_reference",
        "agent_artifacts",
        ["storage_reference"],
        unique=False,
    )

    op.create_table(
        "agent_checkpoints",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("checkpoint_id", sa.UUID(), nullable=False),
        sa.Column("execution_id", sa.UUID(), nullable=False),
        sa.Column("agent_run_id", sa.UUID(), nullable=False),
        sa.Column("agent_step_id", sa.UUID(), nullable=True),
        sa.Column("checkpoint_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column(
            "resumable",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("state_summary", json_type, nullable=False),
        sa.Column("evidence_references", json_type, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(STATUS_CHECK, name="ck_agent_checkpoints_status"),
        sa.CheckConstraint("checkpoint_version >= 1", name="ck_agent_checkpoints_version"),
        sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_step_id"], ["agent_steps.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["execution_id"], ["agent_executions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("checkpoint_id", name="uq_agent_checkpoints_checkpoint_id"),
        sa.UniqueConstraint(
            "agent_run_id",
            "checkpoint_version",
            name="uq_agent_checkpoints_run_version",
        ),
    )
    op.create_index(
        "ix_agent_checkpoints_execution_created",
        "agent_checkpoints",
        ["execution_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_agent_checkpoints_run_created",
        "agent_checkpoints",
        ["agent_run_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_agent_checkpoints_step",
        "agent_checkpoints",
        ["agent_step_id"],
        unique=False,
    )


def downgrade() -> None:
    for index_name in (
        "ix_agent_checkpoints_step",
        "ix_agent_checkpoints_run_created",
        "ix_agent_checkpoints_execution_created",
    ):
        op.drop_index(index_name, table_name="agent_checkpoints")
    op.drop_table("agent_checkpoints")

    for index_name in (
        "ix_agent_artifacts_storage_reference",
        "ix_agent_artifacts_step",
        "ix_agent_artifacts_run",
        "ix_agent_artifacts_execution_created",
    ):
        op.drop_index(index_name, table_name="agent_artifacts")
    op.drop_table("agent_artifacts")

    for index_name in (
        "ix_agent_events_type",
        "ix_agent_events_step",
        "ix_agent_events_run",
        "ix_agent_events_execution_created",
    ):
        op.drop_index(index_name, table_name="agent_events")
    op.drop_table("agent_events")

    for index_name in (
        "ix_agent_steps_tool",
        "ix_agent_steps_run_status",
        "ix_agent_steps_dependency",
    ):
        op.drop_index(index_name, table_name="agent_steps")
    op.drop_table("agent_steps")

    for index_name in (
        "ix_agent_runs_parent",
        "ix_agent_runs_execution_created",
        "ix_agent_runs_dependency",
        "ix_agent_runs_agent_status",
    ):
        op.drop_index(index_name, table_name="agent_runs")
    op.drop_table("agent_runs")

    for index_name in (
        "ix_agent_executions_workflow_status",
        "ix_agent_executions_project_created",
        "ix_agent_executions_analysis_run",
    ):
        op.drop_index(index_name, table_name="agent_executions")
    op.drop_table("agent_executions")
