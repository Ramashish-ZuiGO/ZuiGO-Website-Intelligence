"""Add actionable remediation engine: action generations, groups, items, status history.

Revision ID: 20260723_0010
Revises: 20260723_0009
"""
# ruff: noqa: E501

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260723_0010"
down_revision: str | Sequence[str] | None = "20260723_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "action_generation_executions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("website_id", sa.Uuid(), nullable=False),
        sa.Column("discovery_run_id", sa.Uuid()),
        sa.Column("page_analysis_execution_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status", sa.String(length=30), nullable=False, server_default=sa.text("'pending'")
        ),
        sa.Column(
            "total_findings_processed", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "total_actions_generated", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "unsupported_finding_count", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "insufficient_evidence_count", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "duplicate_within_execution_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "historical_equivalent_count", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("error_message", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["website_id"], ["websites.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["discovery_run_id"], ["discovery_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_action_gen_exec_website_id", "action_generation_executions", ["website_id"])
    op.create_index(
        "ix_action_gen_exec_page_analysis_exec_id",
        "action_generation_executions",
        ["page_analysis_execution_id"],
    )
    op.create_index("ix_action_gen_exec_status", "action_generation_executions", ["status"])
    op.create_index(
        "ix_action_gen_exec_created",
        "action_generation_executions",
        ["website_id", "created_at"],
    )

    op.create_table(
        "action_groups",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("generation_execution_id", sa.Uuid(), nullable=False),
        sa.Column("website_id", sa.Uuid(), nullable=False),
        sa.Column("grouping_key", sa.String(length=200), nullable=False),
        sa.Column("issue_title", sa.String(length=300), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("severity", sa.String(length=30), nullable=False),
        sa.Column("priority_score", sa.Integer(), nullable=False),
        sa.Column("priority_formula_version", sa.String(length=50), nullable=False),
        sa.Column("confidence", sa.String(length=30), nullable=False),
        sa.Column("estimated_effort", sa.String(length=30), nullable=False),
        sa.Column("business_impact", sa.Text(), nullable=False),
        sa.Column("responsible_area", sa.String(length=100), nullable=False),
        sa.Column("responsible_role", sa.String(length=100), nullable=False),
        sa.Column("action_location", sa.String(length=300), nullable=False),
        sa.Column("why_this_matters", sa.Text(), nullable=False),
        sa.Column("exact_correction", sa.Text(), nullable=False),
        sa.Column("implementation_steps", sa.Text(), nullable=False),
        sa.Column("verification_steps", sa.Text(), nullable=False),
        sa.Column("expected_result", sa.Text(), nullable=False),
        sa.Column("limitations", sa.Text(), nullable=False),
        sa.Column(
            "evidence_summary",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("source_audit", sa.String(length=100), nullable=False),
        sa.Column(
            "priority_components",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("affected_page_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.String(length=30), nullable=False, server_default=sa.text("'open'")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["generation_execution_id"],
            ["action_generation_executions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["website_id"], ["websites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "generation_execution_id", "grouping_key", name="uq_action_groups_execution_key"
        ),
    )
    op.create_index(
        "ix_action_groups_generation_exec_id", "action_groups", ["generation_execution_id"]
    )
    op.create_index("ix_action_groups_website_id", "action_groups", ["website_id"])
    op.create_index("ix_action_groups_status", "action_groups", ["status"])
    op.create_index("ix_action_groups_severity", "action_groups", ["severity"])
    op.create_index("ix_action_groups_category", "action_groups", ["category"])
    op.create_index("ix_action_groups_responsible_area", "action_groups", ["responsible_area"])

    op.create_table(
        "action_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("generation_execution_id", sa.Uuid(), nullable=False),
        sa.Column("action_group_id", sa.Uuid()),
        sa.Column("website_id", sa.Uuid(), nullable=False),
        sa.Column("page_analysis_run_id", sa.Uuid()),
        sa.Column("website_page_id", sa.Uuid(), nullable=False),
        sa.Column("source_finding_identity", sa.String(length=200), nullable=False),
        sa.Column("source_page_analysis_run_id", sa.Uuid()),
        sa.Column("requested_url", sa.String(length=2048)),
        sa.Column("final_url", sa.String(length=2048)),
        sa.Column("page_title", sa.Text()),
        sa.Column("issue_title", sa.String(length=300), nullable=False),
        sa.Column("issue_category", sa.String(length=100), nullable=False),
        sa.Column("severity", sa.String(length=30), nullable=False),
        sa.Column("priority_score", sa.Integer(), nullable=False),
        sa.Column("priority_formula_version", sa.String(length=50), nullable=False),
        sa.Column(
            "priority_components",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("confidence", sa.String(length=30), nullable=False),
        sa.Column(
            "confidence_percent", sa.Integer(), nullable=False, server_default=sa.text("100")
        ),
        sa.Column("estimated_effort", sa.String(length=30), nullable=False),
        sa.Column("business_impact", sa.Text(), nullable=False),
        sa.Column("responsible_area", sa.String(length=100), nullable=False),
        sa.Column("responsible_role", sa.String(length=100), nullable=False),
        sa.Column("action_location", sa.String(length=300), nullable=False),
        sa.Column("why_this_matters", sa.Text(), nullable=False),
        sa.Column("exact_correction", sa.Text(), nullable=False),
        sa.Column("implementation_steps", sa.Text(), nullable=False),
        sa.Column("verification_steps", sa.Text(), nullable=False),
        sa.Column("expected_result", sa.Text(), nullable=False),
        sa.Column("limitations", sa.Text(), nullable=False),
        sa.Column(
            "evidence_summary",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("source_audit", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default=sa.text("'open'")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["generation_execution_id"],
            ["action_generation_executions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["action_group_id"], ["action_groups.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["website_id"], ["websites.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["page_analysis_run_id"], ["page_analysis_runs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["website_page_id"], ["website_pages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_page_analysis_run_id"], ["page_analysis_runs.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "generation_execution_id",
            "source_finding_identity",
            "website_page_id",
            name="uq_action_items_execution_finding_page",
        ),
        sa.CheckConstraint(
            "confidence_percent >= 0 AND confidence_percent <= 100",
            name="ck_action_items_confidence_percent_range",
        ),
        sa.CheckConstraint(
            "priority_score >= 0 AND priority_score <= 100",
            name="ck_action_items_priority_score_range",
        ),
    )
    op.create_index(
        "ix_action_items_generation_exec_id", "action_items", ["generation_execution_id"]
    )
    op.create_index("ix_action_items_website_id", "action_items", ["website_id"])
    op.create_index("ix_action_items_website_page_id", "action_items", ["website_page_id"])
    op.create_index("ix_action_items_status", "action_items", ["status"])
    op.create_index("ix_action_items_severity", "action_items", ["severity"])
    op.create_index("ix_action_items_priority", "action_items", ["priority_score"])
    op.create_index("ix_action_items_group_id", "action_items", ["action_group_id"])
    op.create_index("ix_action_items_category", "action_items", ["issue_category"])
    op.create_index("ix_action_items_responsible_area", "action_items", ["responsible_area"])

    op.create_table(
        "action_status_history",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("action_item_id", sa.Uuid(), nullable=False),
        sa.Column("previous_status", sa.String(length=30), nullable=False),
        sa.Column("new_status", sa.String(length=30), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("actor", sa.String(length=200)),
        sa.Column(
            "source", sa.String(length=30), nullable=False, server_default=sa.text("'manual'")
        ),
        sa.Column(
            "changed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["action_item_id"], ["action_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_action_status_history_action_id", "action_status_history", ["action_item_id"]
    )
    op.create_index("ix_action_status_history_changed_at", "action_status_history", ["changed_at"])
    op.create_index("ix_action_status_history_new_status", "action_status_history", ["new_status"])


def downgrade() -> None:
    for idx in (
        "ix_action_status_history_new_status",
        "ix_action_status_history_changed_at",
        "ix_action_status_history_action_id",
    ):
        op.execute(f'DROP INDEX IF EXISTS "{idx}" CASCADE')
    op.drop_table("action_status_history")

    for idx in (
        "ix_action_items_responsible_area",
        "ix_action_items_category",
        "ix_action_items_priority",
        "ix_action_items_severity",
        "ix_action_items_status",
        "ix_action_items_website_page_id",
        "ix_action_items_website_id",
        "ix_action_items_generation_exec_id",
    ):
        op.execute(f'DROP INDEX IF EXISTS "{idx}" CASCADE')
    op.drop_table("action_items")

    for idx in (
        "ix_action_groups_responsible_area",
        "ix_action_groups_category",
        "ix_action_groups_severity",
        "ix_action_groups_status",
        "ix_action_groups_website_id",
        "ix_action_groups_generation_exec_id",
    ):
        op.execute(f'DROP INDEX IF EXISTS "{idx}" CASCADE')
    op.drop_table("action_groups")

    for idx in (
        "ix_action_gen_exec_created",
        "ix_action_gen_exec_status",
        "ix_action_gen_exec_page_analysis_exec_id",
        "ix_action_gen_exec_website_id",
    ):
        op.execute(f'DROP INDEX IF EXISTS "{idx}" CASCADE')
    op.drop_table("action_generation_executions")
