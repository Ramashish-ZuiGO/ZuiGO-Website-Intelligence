"""Add page-level analysis runs and extend pages for site-wide analysis.

Revision ID: 20260723_0009
Revises: 20260723_0008
"""

# ruff: noqa: E501

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260723_0009"
down_revision: str | Sequence[str] | None = "20260723_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "page_analysis_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("website_page_id", sa.Uuid(), nullable=False),
        sa.Column("discovery_run_id", sa.Uuid()),
        sa.Column("page_analysis_execution_id", sa.Uuid(), nullable=False),
        sa.Column("analysis_level", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("failure_reason_code", sa.String(length=100)),
        sa.Column("failure_reason_text", sa.String(length=500)),
        sa.Column("analysis_started_at", sa.DateTime(timezone=True)),
        sa.Column("analysis_completed_at", sa.DateTime(timezone=True)),
        sa.Column("requested_url", sa.String(length=2048)),
        sa.Column("final_url", sa.String(length=2048)),
        sa.Column("canonical_url", sa.String(length=2048)),
        sa.Column("http_status_code", sa.Integer()),
        sa.Column(
            "redirect_chain",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("page_title", sa.Text()),
        sa.Column("meta_description", sa.Text()),
        sa.Column(
            "heading_structure",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "robots_directives",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("content_type", sa.String(length=200)),
        sa.Column("language", sa.String(length=50)),
        sa.Column("structured_data_present", sa.Boolean()),
        sa.Column("internal_link_count", sa.Integer()),
        sa.Column("external_link_count", sa.Integer()),
        sa.Column("image_count", sa.Integer()),
        sa.Column("images_missing_alt", sa.Integer()),
        sa.Column("form_count", sa.Integer()),
        sa.Column(
            "basic_accessibility_signals",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "basic_seo_signals",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "security_observations",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "evidence", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("elapsed_ms", sa.Integer()),
        sa.Column("deep_analysis_run_id", sa.Uuid()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["website_page_id"], ["website_pages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["discovery_run_id"], ["discovery_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["deep_analysis_run_id"], ["analysis_runs.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_page_analysis_runs_website_page_id",
        "page_analysis_runs",
        ["website_page_id"],
    )
    op.create_index(
        "ix_page_analysis_runs_discovery_run_id",
        "page_analysis_runs",
        ["discovery_run_id"],
    )
    op.create_index(
        "ix_page_analysis_runs_status",
        "page_analysis_runs",
        ["status"],
    )
    op.create_index(
        "ix_page_analysis_runs_level_status",
        "page_analysis_runs",
        ["analysis_level", "status"],
    )
    op.create_index(
        "ix_page_analysis_runs_execution_id",
        "page_analysis_runs",
        ["page_analysis_execution_id"],
    )
    op.create_index(
        "uq_page_analysis_runs_page_level_exec",
        "page_analysis_runs",
        ["website_page_id", "analysis_level", "page_analysis_execution_id"],
        unique=True,
    )

    op.add_column(
        "website_pages",
        sa.Column(
            "page_analysis_level_1_status",
            sa.String(length=30),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
    )
    op.add_column(
        "website_pages",
        sa.Column(
            "page_analysis_level_2_status",
            sa.String(length=30),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
    )
    op.add_column(
        "website_pages",
        sa.Column("page_analysis_level_1_run_id", sa.Uuid()),
    )
    op.add_column(
        "website_pages",
        sa.Column("page_analysis_level_2_run_id", sa.Uuid()),
    )
    op.add_column(
        "website_pages",
        sa.Column("page_analysis_level_1_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "website_pages",
        sa.Column("page_analysis_level_2_at", sa.DateTime(timezone=True)),
    )
    op.create_foreign_key(
        "fk_website_pages_l1_run",
        "website_pages",
        "page_analysis_runs",
        ["page_analysis_level_1_run_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )
    op.create_foreign_key(
        "fk_website_pages_l2_run",
        "website_pages",
        "page_analysis_runs",
        ["page_analysis_level_2_run_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )
    op.create_index(
        "ix_website_pages_l1_status",
        "website_pages",
        ["website_id", "page_analysis_level_1_status"],
    )
    op.create_index(
        "ix_website_pages_l2_status",
        "website_pages",
        ["website_id", "page_analysis_level_2_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_website_pages_l2_status", table_name="website_pages")
    op.drop_index("ix_website_pages_l1_status", table_name="website_pages")
    op.drop_constraint("fk_website_pages_l2_run", "website_pages", type_="foreignkey")
    op.drop_constraint("fk_website_pages_l1_run", "website_pages", type_="foreignkey")
    op.drop_column("website_pages", "page_analysis_level_2_at")
    op.drop_column("website_pages", "page_analysis_level_1_at")
    op.drop_column("website_pages", "page_analysis_level_2_run_id")
    op.drop_column("website_pages", "page_analysis_level_1_run_id")
    op.drop_column("website_pages", "page_analysis_level_2_status")
    op.drop_column("website_pages", "page_analysis_level_1_status")
    for idx in (
        "uq_page_analysis_runs_page_level_exec",
        "ix_page_analysis_runs_execution_id",
        "ix_page_analysis_runs_page_level_run",
        "ix_page_analysis_runs_level_status",
        "ix_page_analysis_runs_status",
        "ix_page_analysis_runs_discovery_run_id",
        "ix_page_analysis_runs_website_page_id",
    ):
        op.execute(f'DROP INDEX IF EXISTS "{idx}" CASCADE')
    op.drop_table("page_analysis_runs")
