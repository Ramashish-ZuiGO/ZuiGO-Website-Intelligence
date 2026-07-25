"""performance_snapshots

Revision ID: 20260725_0013
Revises: 20260725_0012
Create Date: 2026-07-25 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260725_0013"
down_revision: str | None = "20260725_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "performance_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("execution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("website_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("analysis_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("url_or_origin", sa.String(length=2048), nullable=False),
        sa.Column("evidence_source", sa.String(length=50), nullable=False),
        sa.Column("evidence_type", sa.String(length=50), nullable=False),
        sa.Column("scope", sa.String(length=50), nullable=False),
        sa.Column("form_factor", sa.String(length=50), nullable=False),
        sa.Column("metric_id", sa.String(length=100), nullable=False),
        sa.Column("raw_value", sa.Float(), nullable=True),
        sa.Column("display_value", sa.String(length=100), nullable=True),
        sa.Column("numeric_unit", sa.String(length=50), nullable=True),
        sa.Column("percentile", sa.Float(), nullable=True),
        sa.Column("histogram_bins", sa.JSON(), nullable=True),
        sa.Column("rating", sa.String(length=50), nullable=True),
        sa.Column("profile_id", sa.String(length=100), nullable=True),
        sa.Column("profile_version", sa.String(length=50), nullable=True),
        sa.Column("collection_period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("collection_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observation_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider", sa.String(length=100), nullable=True),
        sa.Column("provider_metadata", sa.JSON(), nullable=True),
        sa.Column("availability_status", sa.String(length=50), nullable=False),
        sa.Column("unavailable_reason", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["analysis_run_id"], ["analysis_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["website_id"], ["websites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "execution_id",
            "website_id",
            "url_or_origin",
            "evidence_type",
            "metric_id",
            "form_factor",
            name="uq_performance_snapshots_execution_metric",
        ),
    )
    op.create_index(
        op.f("ix_performance_snapshots_analysis_run_id"),
        "performance_snapshots",
        ["analysis_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_performance_snapshots_metric_id"),
        "performance_snapshots",
        ["metric_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_performance_snapshots_url_or_origin"),
        "performance_snapshots",
        ["url_or_origin"],
        unique=False,
    )
    op.create_index(
        op.f("ix_performance_snapshots_website_id"),
        "performance_snapshots",
        ["website_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_performance_snapshots_website_id"), table_name="performance_snapshots")
    op.drop_index(
        op.f("ix_performance_snapshots_url_or_origin"), table_name="performance_snapshots"
    )
    op.drop_index(op.f("ix_performance_snapshots_metric_id"), table_name="performance_snapshots")
    op.drop_index(
        op.f("ix_performance_snapshots_analysis_run_id"), table_name="performance_snapshots"
    )
    op.drop_table("performance_snapshots")
