"""threshold_profiles

Revision ID: 20260725_0012
Revises: 20260723_0011
Create Date: 2026-07-25 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260725_0012"
down_revision: str | None = "20260723_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("analysis_runs", sa.Column("profile_id", sa.String(length=100), nullable=True))
    op.add_column(
        "analysis_runs", sa.Column("profile_version", sa.String(length=50), nullable=True)
    )
    op.add_column(
        "websites",
        sa.Column(
            "profile_id", sa.String(length=100), server_default="global_general", nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_column("websites", "profile_id")
    op.drop_column("analysis_runs", "profile_version")
    op.drop_column("analysis_runs", "profile_id")
