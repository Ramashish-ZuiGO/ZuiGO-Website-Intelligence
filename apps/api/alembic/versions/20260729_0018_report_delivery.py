"""Add immutable report delivery persistence.

Revision ID: 20260729_0018
Revises: 20260728_0017
Create Date: 2026-07-29 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260729_0018"
down_revision: str | None = "20260728_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "report_executions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("report_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("website_id", sa.UUID(), nullable=False),
        sa.Column("analysis_run_id", sa.UUID(), nullable=False),
        sa.Column("workflow_execution_id", sa.UUID(), nullable=True),
        sa.Column("score_execution_id", sa.UUID(), nullable=True),
        sa.Column("report_type", sa.String(100), nullable=False),
        sa.Column("report_version", sa.String(50), nullable=False),
        sa.Column("template_id", sa.String(100), nullable=False),
        sa.Column("template_version", sa.String(50), nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("status", sa.String(50), server_default=sa.text("'pending'"), nullable=False),
        sa.Column(
            "evidence_coverage_numerator",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "evidence_coverage_denominator",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("evidence_coverage_percentage", sa.Float(), nullable=True),
        sa.Column("confidence_percent", sa.Integer(), nullable=True),
        sa.Column("unavailable_sections", json_type, nullable=False),
        sa.Column("provider_version_metadata", json_type, nullable=False),
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
        sa.CheckConstraint(
            "confidence_percent IS NULL OR confidence_percent BETWEEN 0 AND 100",
            name="ck_report_executions_confidence",
        ),
        sa.CheckConstraint(
            "evidence_coverage_percentage IS NULL OR "
            "evidence_coverage_percentage BETWEEN 0 AND 100",
            name="ck_report_executions_coverage",
        ),
        sa.CheckConstraint(
            "evidence_coverage_numerator >= 0 AND evidence_coverage_denominator >= 0 "
            "AND evidence_coverage_numerator <= evidence_coverage_denominator",
            name="ck_report_executions_coverage_counts",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'partial', 'failed', 'unavailable')",
            name="ck_report_executions_status",
        ),
        sa.ForeignKeyConstraint(["analysis_run_id"], ["analysis_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workflow_execution_id"], ["agent_executions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["score_execution_id"], ["score_executions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["website_id"], ["websites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("report_id", name="uq_report_executions_report_id"),
        sa.UniqueConstraint(
            "analysis_run_id",
            "report_type",
            "report_version",
            "idempotency_key",
            name="uq_report_executions_run_type_idempotency",
        ),
    )
    op.create_index(
        "ix_report_executions_run_created",
        "report_executions",
        ["analysis_run_id", "created_at"],
    )
    op.create_index(
        "ix_report_executions_website_created",
        "report_executions",
        ["website_id", "created_at"],
    )
    op.create_index(
        "ix_report_executions_project_status",
        "report_executions",
        ["project_id", "status"],
    )
    op.create_index(
        "ix_report_executions_workflow",
        "report_executions",
        ["workflow_execution_id"],
    )

    op.create_table(
        "report_snapshots",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("snapshot_id", sa.UUID(), nullable=False),
        sa.Column("report_execution_id", sa.UUID(), nullable=False),
        sa.Column("snapshot_payload", json_type, nullable=False),
        sa.Column("evidence_references", json_type, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["report_execution_id"], ["report_executions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_id", name="uq_report_snapshots_snapshot_id"),
        sa.UniqueConstraint("report_execution_id", name="uq_report_snapshots_execution"),
    )
    op.create_index("ix_report_snapshots_created", "report_snapshots", ["created_at"])

    op.create_table(
        "report_sections",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("section_id", sa.UUID(), nullable=False),
        sa.Column("report_execution_id", sa.UUID(), nullable=False),
        sa.Column("section_key", sa.String(100), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("content", json_type, nullable=False),
        sa.Column("evidence_references", json_type, nullable=False),
        sa.Column("unavailable_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("position >= 1", name="ck_report_sections_position"),
        sa.CheckConstraint(
            "status IN ('passed', 'failed', 'available', 'unavailable', 'incomplete', 'excluded')",
            name="ck_report_sections_status",
        ),
        sa.ForeignKeyConstraint(
            ["report_execution_id"], ["report_executions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("section_id", name="uq_report_sections_section_id"),
        sa.UniqueConstraint(
            "report_execution_id",
            "section_key",
            name="uq_report_sections_execution_key",
        ),
        sa.UniqueConstraint(
            "report_execution_id",
            "position",
            name="uq_report_sections_execution_position",
        ),
    )
    op.create_index("ix_report_sections_execution", "report_sections", ["report_execution_id"])
    op.create_index("ix_report_sections_status", "report_sections", ["status"])

    op.create_table(
        "report_artifacts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("artifact_id", sa.UUID(), nullable=False),
        sa.Column("report_execution_id", sa.UUID(), nullable=False),
        sa.Column("format", sa.String(20), nullable=False),
        sa.Column("media_type", sa.String(100), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("checksum_sha256", sa.String(64), nullable=False),
        sa.Column("storage_location", sa.String(500), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "format IN ('html', 'pdf', 'json')",
            name="ck_report_artifacts_format",
        ),
        sa.CheckConstraint("size_bytes >= 0", name="ck_report_artifacts_size"),
        sa.ForeignKeyConstraint(
            ["report_execution_id"], ["report_executions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("artifact_id", name="uq_report_artifacts_artifact_id"),
        sa.UniqueConstraint(
            "report_execution_id",
            "format",
            name="uq_report_artifacts_execution_format",
        ),
    )
    op.create_index("ix_report_artifacts_execution", "report_artifacts", ["report_execution_id"])
    op.create_index("ix_report_artifacts_checksum", "report_artifacts", ["checksum_sha256"])


def downgrade() -> None:
    op.drop_index("ix_report_artifacts_checksum", table_name="report_artifacts")
    op.drop_index("ix_report_artifacts_execution", table_name="report_artifacts")
    op.drop_table("report_artifacts")
    op.drop_index("ix_report_sections_status", table_name="report_sections")
    op.drop_index("ix_report_sections_execution", table_name="report_sections")
    op.drop_table("report_sections")
    op.drop_index("ix_report_snapshots_created", table_name="report_snapshots")
    op.drop_table("report_snapshots")
    op.drop_index("ix_report_executions_workflow", table_name="report_executions")
    op.drop_index("ix_report_executions_project_status", table_name="report_executions")
    op.drop_index("ix_report_executions_website_created", table_name="report_executions")
    op.drop_index("ix_report_executions_run_created", table_name="report_executions")
    op.drop_table("report_executions")
