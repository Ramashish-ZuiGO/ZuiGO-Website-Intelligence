"""Add safe website discovery runs and normalized pages.

Revision ID: 20260723_0008
Revises: 20260720_0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260723_0008"
down_revision: str | Sequence[str] | None = "20260720_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "discovery_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("website_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("current_stage", sa.String(length=100)),
        sa.Column("progress_percent", sa.Integer(), nullable=False),
        sa.Column("celery_task_id", sa.String(length=255)),
        sa.Column("configuration", postgresql.JSONB(), nullable=False),
        sa.Column("robots_details", postgresql.JSONB(), nullable=False),
        sa.Column("sitemap_details", postgresql.JSONB(), nullable=False),
        sa.Column("urls_discovered", sa.Integer(), nullable=False),
        sa.Column("urls_unique", sa.Integer(), nullable=False),
        sa.Column("urls_eligible", sa.Integer(), nullable=False),
        sa.Column("urls_excluded", sa.Integer(), nullable=False),
        sa.Column("urls_skipped", sa.Integer(), nullable=False),
        sa.Column("sitemap_count", sa.Integer(), nullable=False),
        sa.Column("crawl_limit_reached", sa.Boolean(), nullable=False),
        sa.Column("maximum_depth_reached", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("failure_code", sa.String(length=100)),
        sa.Column("failure_message", sa.String(length=500)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100",
            name="ck_discovery_runs_progress_percent_range",
        ),
        sa.ForeignKeyConstraint(["website_id"], ["websites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_discovery_runs_website_created",
        "discovery_runs",
        ["website_id", "created_at"],
    )
    op.create_index("ix_discovery_runs_status", "discovery_runs", ["status"])

    op.create_table(
        "website_pages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("website_id", sa.Uuid(), nullable=False),
        sa.Column("normalized_url", sa.String(length=2048), nullable=False),
        sa.Column("original_url", sa.String(length=2048), nullable=False),
        sa.Column("final_url", sa.String(length=2048)),
        sa.Column("canonical_url", sa.String(length=2048)),
        sa.Column("page_title", sa.Text()),
        sa.Column("page_type", sa.String(length=50), nullable=False),
        sa.Column("page_type_confidence", sa.Integer(), nullable=False),
        sa.Column("page_type_indicators", postgresql.JSONB(), nullable=False),
        sa.Column("classification_version", sa.String(length=50), nullable=False),
        sa.Column("discovery_source", sa.String(length=50), nullable=False),
        sa.Column("discovery_evidence", postgresql.JSONB(), nullable=False),
        sa.Column("source_page_url", sa.String(length=2048)),
        sa.Column("crawl_depth", sa.Integer(), nullable=False),
        sa.Column("origin_relation", sa.String(length=30), nullable=False),
        sa.Column("robots_status", sa.String(length=30), nullable=False),
        sa.Column("eligibility_status", sa.String(length=30), nullable=False),
        sa.Column("exclusion_reason", sa.String(length=200)),
        sa.Column("skip_reason", sa.String(length=200)),
        sa.Column("last_discovery_run_id", sa.Uuid()),
        sa.Column("latest_analysis_run_id", sa.Uuid()),
        sa.Column("latest_analysis_status", sa.String(length=30), nullable=False),
        sa.Column("first_discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["website_id"], ["websites.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["last_discovery_run_id"], ["discovery_runs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["latest_analysis_run_id"], ["analysis_runs.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("website_id", "normalized_url", name="uq_website_pages_normalized_url"),
    )
    op.create_index(
        "ix_website_pages_website_eligibility",
        "website_pages",
        ["website_id", "eligibility_status"],
    )
    op.create_index("ix_website_pages_website_type", "website_pages", ["website_id", "page_type"])
    op.create_index(
        "ix_website_pages_website_robots", "website_pages", ["website_id", "robots_status"]
    )
    op.create_index(
        "ix_website_pages_last_discovery_run_id",
        "website_pages",
        ["last_discovery_run_id"],
    )
    op.create_index(
        "ix_website_pages_latest_analysis_run_id",
        "website_pages",
        ["latest_analysis_run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_website_pages_last_discovery_run_id", table_name="website_pages")
    op.drop_index("ix_website_pages_latest_analysis_run_id", table_name="website_pages")
    op.drop_index("ix_website_pages_website_robots", table_name="website_pages")
    op.drop_index("ix_website_pages_website_type", table_name="website_pages")
    op.drop_index("ix_website_pages_website_eligibility", table_name="website_pages")
    op.drop_table("website_pages")
    op.drop_index("ix_discovery_runs_status", table_name="discovery_runs")
    op.drop_index("ix_discovery_runs_website_created", table_name="discovery_runs")
    op.drop_table("discovery_runs")
