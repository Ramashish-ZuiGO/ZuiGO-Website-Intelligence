"""Create analysis results and findings.

Revision ID: 20260718_0004
Revises: 20260717_0003
Create Date: 2026-07-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260718_0004"
down_revision: str | Sequence[str] | None = "20260717_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analysis_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("analysis_run_id", sa.Uuid(), nullable=False),
        sa.Column("requested_url", sa.String(length=2048), nullable=False),
        sa.Column("final_url", sa.String(length=2048), nullable=False),
        sa.Column("http_status_code", sa.Integer(), nullable=True),
        sa.Column("page_title", sa.Text(), nullable=True),
        sa.Column("meta_description", sa.Text(), nullable=True),
        sa.Column("lighthouse_version", sa.String(length=50), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("analysis_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("analysis_completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_lighthouse_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("raw_playwright_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["analysis_run_id"],
            ["analysis_runs.id"],
            name="fk_analysis_results_analysis_run_id_analysis_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_analysis_results"),
        sa.UniqueConstraint("analysis_run_id", name="uq_analysis_results_analysis_run_id"),
    )
    op.create_table(
        "analysis_findings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("analysis_run_id", sa.Uuid(), nullable=False),
        sa.Column("finding_code", sa.String(length=100), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("affected_url", sa.String(length=2048), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("confidence_percent", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "severity IN ('critical', 'high', 'medium', 'low', 'informational')",
            name="ck_analysis_findings_finding_severity",
        ),
        sa.CheckConstraint(
            "source IN ('lighthouse', 'playwright', 'http')",
            name="ck_analysis_findings_finding_source",
        ),
        sa.CheckConstraint(
            "confidence_percent >= 0 AND confidence_percent <= 100",
            name="ck_analysis_findings_confidence_percent_range",
        ),
        sa.ForeignKeyConstraint(
            ["analysis_run_id"],
            ["analysis_runs.id"],
            name="fk_analysis_findings_analysis_run_id_analysis_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_analysis_findings"),
        sa.UniqueConstraint(
            "analysis_run_id", "finding_code", name="uq_analysis_findings_run_code"
        ),
    )
    op.create_index(
        "ix_analysis_findings_analysis_run_id",
        "analysis_findings",
        ["analysis_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_analysis_findings_finding_code",
        "analysis_findings",
        ["finding_code"],
        unique=False,
    )
    op.create_index(
        "ix_analysis_findings_severity", "analysis_findings", ["severity"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_analysis_findings_severity", table_name="analysis_findings")
    op.drop_index("ix_analysis_findings_finding_code", table_name="analysis_findings")
    op.drop_index("ix_analysis_findings_analysis_run_id", table_name="analysis_findings")
    op.drop_table("analysis_findings")
    op.drop_table("analysis_results")
