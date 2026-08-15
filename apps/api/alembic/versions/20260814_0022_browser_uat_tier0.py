"""Add browser_uat_tier0_executions table.

M2 first slice of the device/OS/browser QA initiative
(docs/DEVICE_OS_BROWSER_QA_PLAN.md): on-demand real-browser Tier 0
verification for the Chrome/Edge desktop lane. Deliberately minimal --
grows into the full per-combination schema once M4 is designed.

Revision ID: 20260814_0022
Revises: 20260812_0021
Create Date: 2026-08-14 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "20260814_0022"
down_revision: str | None = "20260812_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "browser_uat_tier0_executions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("website_id", sa.Uuid(), nullable=False),
        sa.Column("analysis_run_id", sa.Uuid(), nullable=False),
        sa.Column("lane", sa.String(length=50), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            sa.String(length=50),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("attempt", sa.Integer(), server_default="1", nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("provider_run_reference", sa.String(length=255), nullable=True),
        sa.Column(
            "structured_output",
            sa.JSON().with_variant(JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["website_id"], ["websites.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["analysis_run_id"], ["analysis_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("execution_id", name="uq_browser_uat_tier0_executions_execution_id"),
        sa.UniqueConstraint(
            "analysis_run_id",
            "lane",
            "idempotency_key",
            name="uq_browser_uat_tier0_executions_run_lane_idempotency",
        ),
        sa.CheckConstraint("attempt >= 1", name="ck_browser_uat_tier0_executions_attempt"),
    )
    op.create_index(
        "ix_browser_uat_tier0_executions_website_created",
        "browser_uat_tier0_executions",
        ["website_id", "created_at"],
    )
    op.create_index(
        "ix_browser_uat_tier0_executions_run_created",
        "browser_uat_tier0_executions",
        ["analysis_run_id", "created_at"],
    )
    op.create_index(
        "ix_browser_uat_tier0_executions_status",
        "browser_uat_tier0_executions",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_browser_uat_tier0_executions_status", table_name="browser_uat_tier0_executions"
    )
    op.drop_index(
        "ix_browser_uat_tier0_executions_run_created", table_name="browser_uat_tier0_executions"
    )
    op.drop_index(
        "ix_browser_uat_tier0_executions_website_created",
        table_name="browser_uat_tier0_executions",
    )
    op.drop_table("browser_uat_tier0_executions")
