"""Add immutable reanalysis comparison persistence.

Revision ID: 20260730_0019
Revises: 20260729_0018
Create Date: 2026-07-30 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260730_0019"
down_revision: str | None = "20260729_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.add_column(
        "analysis_runs",
        sa.Column("baseline_analysis_run_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_analysis_runs_baseline_analysis_run_id",
        "analysis_runs",
        "analysis_runs",
        ["baseline_analysis_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_analysis_runs_distinct_baseline",
        "analysis_runs",
        "baseline_analysis_run_id IS NULL OR baseline_analysis_run_id <> id",
    )
    op.create_index(
        "ix_analysis_runs_baseline_analysis_run_id",
        "analysis_runs",
        ["baseline_analysis_run_id"],
    )

    op.create_table(
        "analysis_comparisons",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("comparison_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("website_id", sa.UUID(), nullable=False),
        sa.Column("baseline_analysis_run_id", sa.UUID(), nullable=False),
        sa.Column("current_analysis_run_id", sa.UUID(), nullable=False),
        sa.Column("comparison_version", sa.String(50), nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("result_payload", json_type, nullable=False),
        sa.Column("limitations", json_type, nullable=False),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "baseline_analysis_run_id <> current_analysis_run_id",
            name="ck_analysis_comparisons_distinct_runs",
        ),
        sa.CheckConstraint(
            "status IN ('completed', 'partial', 'failed', 'unavailable')",
            name="ck_analysis_comparisons_status",
        ),
        sa.ForeignKeyConstraint(
            ["baseline_analysis_run_id"],
            ["analysis_runs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["current_analysis_run_id"],
            ["analysis_runs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["website_id"], ["websites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "baseline_analysis_run_id",
            "current_analysis_run_id",
            "idempotency_key",
            name="uq_analysis_comparisons_pair_idempotency",
        ),
        sa.UniqueConstraint(
            "comparison_id",
            name="uq_analysis_comparisons_comparison_id",
        ),
    )
    op.create_index(
        "ix_analysis_comparisons_website_created",
        "analysis_comparisons",
        ["website_id", "created_at"],
    )
    op.create_index(
        "ix_analysis_comparisons_current_created",
        "analysis_comparisons",
        ["current_analysis_run_id", "created_at"],
    )
    op.create_index(
        "ix_analysis_comparisons_baseline_created",
        "analysis_comparisons",
        ["baseline_analysis_run_id", "created_at"],
    )

    op.create_table(
        "analysis_comparison_artifacts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("artifact_id", sa.UUID(), nullable=False),
        sa.Column("comparison_id", sa.UUID(), nullable=False),
        sa.Column("format", sa.String(20), nullable=False),
        sa.Column("media_type", sa.String(100), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("checksum_sha256", sa.String(64), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "format IN ('html', 'pdf', 'json')",
            name="ck_analysis_comparison_artifacts_format",
        ),
        sa.ForeignKeyConstraint(
            ["comparison_id"],
            ["analysis_comparisons.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "artifact_id",
            name="uq_analysis_comparison_artifacts_artifact_id",
        ),
        sa.UniqueConstraint(
            "comparison_id",
            "format",
            name="uq_analysis_comparison_artifacts_format",
        ),
    )
    op.create_index(
        "ix_analysis_comparison_artifacts_comparison",
        "analysis_comparison_artifacts",
        ["comparison_id"],
    )
    op.create_index(
        "ix_analysis_comparison_artifacts_checksum",
        "analysis_comparison_artifacts",
        ["checksum_sha256"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_analysis_comparison_artifacts_checksum",
        table_name="analysis_comparison_artifacts",
    )
    op.drop_index(
        "ix_analysis_comparison_artifacts_comparison",
        table_name="analysis_comparison_artifacts",
    )
    op.drop_table("analysis_comparison_artifacts")
    op.drop_index(
        "ix_analysis_comparisons_baseline_created",
        table_name="analysis_comparisons",
    )
    op.drop_index(
        "ix_analysis_comparisons_current_created",
        table_name="analysis_comparisons",
    )
    op.drop_index(
        "ix_analysis_comparisons_website_created",
        table_name="analysis_comparisons",
    )
    op.drop_table("analysis_comparisons")
    op.drop_index(
        "ix_analysis_runs_baseline_analysis_run_id",
        table_name="analysis_runs",
    )
    op.drop_constraint(
        "ck_analysis_runs_distinct_baseline",
        "analysis_runs",
        type_="check",
    )
    op.drop_constraint(
        "fk_analysis_runs_baseline_analysis_run_id",
        "analysis_runs",
        type_="foreignkey",
    )
    op.drop_column("analysis_runs", "baseline_analysis_run_id")
