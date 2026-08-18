"""Add report_feedback.

M12 (docs/REPORT_QUALITY_INITIATIVE.md): report-level feedback collection.
Simplest, highest-value feedback surface (was this report accurate/useful)
rather than per-finding, which would need UI wiring across every report
component for comparatively little extra signal at v1. Multiple
submissions per report are allowed -- no per-user identity exists yet
under the single shared-admin auth model (M1) -- so each row is an
independent, immutable submission.

Revision ID: 20260818_0024
Revises: 20260814_0023
Create Date: 2026-08-18 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260818_0024"
down_revision: str | None = "20260814_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "report_feedback",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("report_execution_id", sa.Uuid(), nullable=False),
        sa.Column("rating", sa.String(length=20), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["report_execution_id"], ["report_executions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "rating IN ('helpful', 'not_helpful')",
            name="ck_report_feedback_rating",
        ),
        sa.CheckConstraint(
            "length(comment) <= 4000",
            name="ck_report_feedback_comment_length",
        ),
    )
    op.create_index(
        "ix_report_feedback_execution",
        "report_feedback",
        ["report_execution_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_report_feedback_execution", table_name="report_feedback")
    op.drop_table("report_feedback")
