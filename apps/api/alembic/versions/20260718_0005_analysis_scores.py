"""Create analysis scores.

Revision ID: 20260718_0005
Revises: 20260718_0004
Create Date: 2026-07-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260718_0005"
down_revision: str | Sequence[str] | None = "20260718_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analysis_scores",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("analysis_run_id", sa.Uuid(), nullable=False),
        sa.Column("formula_version", sa.String(length=50), nullable=False),
        sa.Column("overall_score", sa.Integer(), nullable=True),
        sa.Column("performance_score", sa.Integer(), nullable=True),
        sa.Column("accessibility_score", sa.Integer(), nullable=True),
        sa.Column("best_practices_score", sa.Integer(), nullable=True),
        sa.Column("seo_score", sa.Integer(), nullable=True),
        sa.Column("technical_quality_score", sa.Integer(), nullable=True),
        sa.Column("confidence_percent", sa.Integer(), nullable=False),
        sa.Column("available_categories", postgresql.JSONB(), nullable=False),
        sa.Column("unavailable_categories", postgresql.JSONB(), nullable=False),
        sa.Column("weights", postgresql.JSONB(), nullable=False),
        sa.Column("deductions", postgresql.JSONB(), nullable=False),
        sa.Column("calculation_details", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("overall_score BETWEEN 0 AND 100", name="ck_analysis_scores_overall"),
        sa.CheckConstraint(
            "performance_score BETWEEN 0 AND 100",
            name="ck_analysis_scores_performance",
        ),
        sa.CheckConstraint(
            "accessibility_score BETWEEN 0 AND 100",
            name="ck_analysis_scores_accessibility",
        ),
        sa.CheckConstraint(
            "best_practices_score BETWEEN 0 AND 100",
            name="ck_analysis_scores_best_practices",
        ),
        sa.CheckConstraint("seo_score BETWEEN 0 AND 100", name="ck_analysis_scores_seo"),
        sa.CheckConstraint(
            "technical_quality_score BETWEEN 0 AND 100",
            name="ck_analysis_scores_technical_quality",
        ),
        sa.CheckConstraint(
            "confidence_percent BETWEEN 0 AND 100", name="ck_analysis_scores_confidence"
        ),
        sa.ForeignKeyConstraint(
            ["analysis_run_id"],
            ["analysis_runs.id"],
            name="fk_analysis_scores_analysis_run_id_analysis_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_analysis_scores"),
        sa.UniqueConstraint("analysis_run_id", name="uq_analysis_scores_analysis_run_id"),
    )
    op.create_index(
        "ix_analysis_scores_analysis_run_id",
        "analysis_scores",
        ["analysis_run_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_analysis_scores_analysis_run_id", table_name="analysis_scores")
    op.drop_table("analysis_scores")
