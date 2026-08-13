"""Add run-scoped discovery_run_pages membership table.

Isolates concurrent same-website analyses: each discovery run records the pages
it found (and their eligibility) independently of the shared, last-writer-wins
``website_pages.last_discovery_run_id`` pointer.

Revision ID: 20260812_0021
Revises: 20260805_0020
Create Date: 2026-08-12 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0021"
down_revision: str | None = "20260805_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "discovery_run_pages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("discovery_run_id", sa.Uuid(), nullable=False),
        sa.Column("website_page_id", sa.Uuid(), nullable=False),
        sa.Column("eligibility_status", sa.String(length=30), nullable=False),
        sa.Column("crawl_depth", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["discovery_run_id"], ["discovery_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["website_page_id"], ["website_pages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "discovery_run_id", "website_page_id", name="uq_discovery_run_pages_run_page"
        ),
    )
    op.create_index(
        "ix_discovery_run_pages_run_eligibility",
        "discovery_run_pages",
        ["discovery_run_id", "eligibility_status"],
    )
    op.create_index(
        "ix_discovery_run_pages_page",
        "discovery_run_pages",
        ["website_page_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_discovery_run_pages_page", table_name="discovery_run_pages")
    op.drop_index("ix_discovery_run_pages_run_eligibility", table_name="discovery_run_pages")
    op.drop_table("discovery_run_pages")
