"""Create analysis interpretations.

Revision ID: 20260718_0006
Revises: 20260718_0005
Create Date: 2026-07-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260718_0006"
down_revision: str | Sequence[str] | None = "20260718_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analysis_interpretations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("analysis_run_id", sa.Uuid(), nullable=False),
        sa.Column("generation_mode", sa.String(length=30), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("prompt_version", sa.String(length=50), nullable=False),
        sa.Column("executive_summary", sa.Text(), nullable=False),
        sa.Column("overall_assessment", sa.Text(), nullable=False),
        sa.Column("strengths", postgresql.JSONB(), nullable=False),
        sa.Column("weaknesses", postgresql.JSONB(), nullable=False),
        sa.Column("priority_recommendations", postgresql.JSONB(), nullable=False),
        sa.Column("action_plan", postgresql.JSONB(), nullable=False),
        sa.Column("limitations", postgresql.JSONB(), nullable=False),
        sa.Column("fallback_reason", sa.String(length=100), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "generation_mode IN ('ai', 'deterministic_fallback')",
            name="ck_analysis_interpretations_generation_mode",
        ),
        sa.ForeignKeyConstraint(
            ["analysis_run_id"],
            ["analysis_runs.id"],
            name="fk_analysis_interpretations_analysis_run_id_analysis_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_analysis_interpretations"),
        sa.UniqueConstraint("analysis_run_id", name="uq_analysis_interpretations_analysis_run_id"),
    )
    op.create_index(
        "ix_analysis_interpretations_analysis_run_id",
        "analysis_interpretations",
        ["analysis_run_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_analysis_interpretations_analysis_run_id",
        table_name="analysis_interpretations",
    )
    op.drop_table("analysis_interpretations")
