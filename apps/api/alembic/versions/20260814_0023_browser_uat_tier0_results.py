"""Add browser_uat_tier0_page_results and browser_uat_tier0_viewport_results.

M4 of the device/OS/browser QA initiative (docs/DEVICE_OS_BROWSER_QA_PLAN.md):
durable, queryable storage for the M2 Tier 0 desktop lane's real per-page,
per-viewport results, replacing the flat structured_output JSONB placeholder
on browser_uat_tier0_executions with a proper 3-level hierarchy (execution ->
page result -> viewport result), mirroring the depth of the existing
site_diagnostic_executions/findings/occurrences pattern.

Revision ID: 20260814_0023
Revises: 20260814_0022
Create Date: 2026-08-14 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "20260814_0023"
down_revision: str | None = "20260814_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "browser_uat_tier0_page_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("browser_channel", sa.String(length=20), nullable=False),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("browser_version", sa.String(length=50), nullable=True),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("console_error_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("error_message", sa.String(length=2000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["execution_id"], ["browser_uat_tier0_executions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "execution_id",
            "browser_channel",
            "platform",
            "url",
            name="uq_browser_uat_tier0_page_results_identity",
        ),
        sa.CheckConstraint(
            "status IN ('pass', 'fail')",
            name="ck_browser_uat_tier0_page_results_status",
        ),
    )
    op.create_index(
        "ix_browser_uat_tier0_page_results_execution",
        "browser_uat_tier0_page_results",
        ["execution_id"],
    )

    op.create_table(
        "browser_uat_tier0_viewport_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("page_result_id", sa.Uuid(), nullable=False),
        sa.Column("viewport_name", sa.String(length=50), nullable=False),
        sa.Column("viewport_width", sa.Integer(), nullable=False),
        sa.Column("viewport_height", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("horizontal_overflow", sa.Boolean(), nullable=True),
        sa.Column(
            "critical_elements_outside_viewport", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("overlapping_elements", sa.Integer(), server_default="0", nullable=False),
        sa.Column("small_tap_targets", sa.Integer(), server_default="0", nullable=False),
        sa.Column("responsive_navigation", sa.Boolean(), nullable=True),
        sa.Column(
            "viewport_problems",
            sa.JSON().with_variant(JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "tap_target_samples",
            sa.JSON().with_variant(JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["page_result_id"], ["browser_uat_tier0_page_results.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('passed', 'failed')",
            name="ck_browser_uat_tier0_viewport_results_status",
        ),
        sa.CheckConstraint(
            "viewport_width > 0 AND viewport_height > 0",
            name="ck_browser_uat_tier0_viewport_results_dimensions",
        ),
    )
    op.create_index(
        "ix_browser_uat_tier0_viewport_results_page_result",
        "browser_uat_tier0_viewport_results",
        ["page_result_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_browser_uat_tier0_viewport_results_page_result",
        table_name="browser_uat_tier0_viewport_results",
    )
    op.drop_table("browser_uat_tier0_viewport_results")
    op.drop_index(
        "ix_browser_uat_tier0_page_results_execution", table_name="browser_uat_tier0_page_results"
    )
    op.drop_table("browser_uat_tier0_page_results")
