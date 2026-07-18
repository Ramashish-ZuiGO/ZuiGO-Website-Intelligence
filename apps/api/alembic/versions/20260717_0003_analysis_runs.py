"""Create analysis runs.

Revision ID: 20260717_0003
Revises: 20260717_0002
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260717_0003"
down_revision: str | Sequence[str] | None = "20260717_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analysis_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("website_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("progress_percent", sa.Integer(), nullable=False),
        sa.Column("current_step", sa.String(length=200), nullable=True),
        sa.Column("celery_task_id", sa.String(length=255), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')",
            name="ck_analysis_runs_analysis_run_status",
        ),
        sa.CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100",
            name="ck_analysis_runs_progress_percent_range",
        ),
        sa.ForeignKeyConstraint(
            ["website_id"],
            ["websites.id"],
            name="fk_analysis_runs_website_id_websites",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_analysis_runs"),
    )
    op.create_index("ix_analysis_runs_created_at", "analysis_runs", ["created_at"], unique=False)
    op.create_index("ix_analysis_runs_status", "analysis_runs", ["status"], unique=False)
    op.create_index("ix_analysis_runs_website_id", "analysis_runs", ["website_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_analysis_runs_website_id", table_name="analysis_runs")
    op.drop_index("ix_analysis_runs_status", table_name="analysis_runs")
    op.drop_index("ix_analysis_runs_created_at", table_name="analysis_runs")
    op.drop_table("analysis_runs")
