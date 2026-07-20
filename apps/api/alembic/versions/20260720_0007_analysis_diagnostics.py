# ruff: noqa: E501

"""Add normalized analysis diagnostic groups.

Revision ID: 20260720_0007
Revises: 20260718_0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260720_0007"
down_revision: str | Sequence[str] | None = "20260718_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analysis_diagnostics",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("analysis_run_id", sa.Uuid(), nullable=False),
        sa.Column("group_name", sa.String(length=100), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["analysis_run_id"],
            ["analysis_runs.id"],
            name="fk_analysis_diagnostics_analysis_run_id_analysis_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_analysis_diagnostics"),
        sa.UniqueConstraint(
            "analysis_run_id", "group_name", name="uq_analysis_diagnostics_run_group"
        ),
    )
    op.create_index(
        "ix_analysis_diagnostics_analysis_run_id",
        "analysis_diagnostics",
        ["analysis_run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_analysis_diagnostics_analysis_run_id", table_name="analysis_diagnostics")
    op.drop_table("analysis_diagnostics")
