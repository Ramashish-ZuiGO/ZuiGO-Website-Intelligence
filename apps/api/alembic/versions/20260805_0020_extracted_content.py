"""Add extracted_content column to analysis_results.

Revision ID: 20260805_0020
Revises: 20260730_0019
Create Date: 2026-08-05 20:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260805_0020"
down_revision: str | None = "20260730_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.add_column(
        "analysis_results",
        sa.Column("extracted_content", json_type, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("analysis_results", "extracted_content")
