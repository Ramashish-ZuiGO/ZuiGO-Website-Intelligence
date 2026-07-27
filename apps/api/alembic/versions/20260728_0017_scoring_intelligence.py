"""Add explainable scoring intelligence persistence.

Revision ID: 20260728_0017
Revises: 20260727_0016
Create Date: 2026-07-28 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260728_0017"
down_revision: str | None = "20260727_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "score_executions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("execution_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("website_id", sa.UUID(), nullable=False),
        sa.Column("analysis_run_id", sa.UUID(), nullable=False),
        sa.Column("formula_id", sa.String(100), nullable=False),
        sa.Column("formula_version", sa.String(50), nullable=False),
        sa.Column("scoring_profile_id", sa.String(100), nullable=False),
        sa.Column("scoring_profile_version", sa.String(50), nullable=False),
        sa.Column("metric_registry_version", sa.String(50), nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("status", sa.String(50), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("overall_score", sa.Integer(), nullable=True),
        sa.Column("confidence_percent", sa.Integer(), nullable=True),
        sa.Column("confidence_classification", sa.String(50), nullable=False),
        sa.Column("evidence_coverage_numerator", sa.Integer(), nullable=False),
        sa.Column("evidence_coverage_denominator", sa.Integer(), nullable=False),
        sa.Column("evidence_coverage_percentage", sa.Float(), nullable=True),
        sa.Column("unavailable_metrics", json_type, nullable=False),
        sa.Column("excluded_metrics", json_type, nullable=False),
        sa.Column("failure_details", json_type, nullable=False),
        sa.Column("partial_completion_details", json_type, nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "confidence_percent IS NULL OR confidence_percent BETWEEN 0 AND 100",
            name="ck_score_executions_confidence",
        ),
        sa.CheckConstraint(
            "evidence_coverage_percentage IS NULL OR "
            "evidence_coverage_percentage BETWEEN 0 AND 100",
            name="ck_score_executions_coverage",
        ),
        sa.CheckConstraint(
            "evidence_coverage_numerator >= 0 AND evidence_coverage_denominator >= 0 "
            "AND evidence_coverage_numerator <= evidence_coverage_denominator",
            name="ck_score_executions_coverage_counts",
        ),
        sa.CheckConstraint(
            "overall_score IS NULL OR overall_score BETWEEN 0 AND 100",
            name="ck_score_executions_overall",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'partial', 'failed', 'unavailable')",
            name="ck_score_executions_status",
        ),
        sa.ForeignKeyConstraint(["analysis_run_id"], ["analysis_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["website_id"], ["websites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("execution_id", name="uq_score_executions_execution_id"),
        sa.UniqueConstraint(
            "analysis_run_id",
            "formula_id",
            "formula_version",
            "idempotency_key",
            name="uq_score_executions_run_formula_idempotency",
        ),
    )
    op.create_index(
        "ix_score_executions_project_status",
        "score_executions",
        ["project_id", "status"],
    )
    op.create_index(
        "ix_score_executions_run_created",
        "score_executions",
        ["analysis_run_id", "created_at"],
    )
    op.create_index(
        "ix_score_executions_website_created",
        "score_executions",
        ["website_id", "created_at"],
    )

    op.create_table(
        "score_snapshots",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("snapshot_id", sa.UUID(), nullable=False),
        sa.Column("score_execution_id", sa.UUID(), nullable=False),
        sa.Column("overall_score", sa.Integer(), nullable=True),
        sa.Column("category_scores", json_type, nullable=False),
        sa.Column("confidence_percent", sa.Integer(), nullable=True),
        sa.Column("evidence_coverage_percentage", sa.Float(), nullable=True),
        sa.Column("unavailable_metrics", json_type, nullable=False),
        sa.Column("excluded_metrics", json_type, nullable=False),
        sa.Column("evidence_references", json_type, nullable=False),
        sa.Column("calculation_details", json_type, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "overall_score IS NULL OR overall_score BETWEEN 0 AND 100",
            name="ck_score_snapshots_overall",
        ),
        sa.ForeignKeyConstraint(
            ["score_execution_id"], ["score_executions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("score_execution_id", name="uq_score_snapshots_execution"),
        sa.UniqueConstraint("snapshot_id", name="uq_score_snapshots_snapshot_id"),
    )
    op.create_index("ix_score_snapshots_created", "score_snapshots", ["created_at"])

    op.create_table(
        "category_scores",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("score_execution_id", sa.UUID(), nullable=False),
        sa.Column("category_id", sa.String(100), nullable=False),
        sa.Column("raw_score", sa.Integer(), nullable=True),
        sa.Column("final_score", sa.Integer(), nullable=True),
        sa.Column("configured_weight", sa.Float(), nullable=False),
        sa.Column("normalized_weight", sa.Float(), nullable=True),
        sa.Column("contribution", sa.Float(), nullable=True),
        sa.Column("band", sa.String(50), nullable=False),
        sa.Column("included", sa.Boolean(), nullable=False),
        sa.Column("exclusion_reason", sa.String(255), nullable=True),
        sa.Column("thresholds", json_type, nullable=False),
        sa.Column("deductions", json_type, nullable=False),
        sa.Column("adjustments", json_type, nullable=False),
        sa.Column("evidence_references", json_type, nullable=False),
        sa.CheckConstraint(
            "final_score IS NULL OR final_score BETWEEN 0 AND 100",
            name="ck_category_scores_final",
        ),
        sa.CheckConstraint(
            "raw_score IS NULL OR raw_score BETWEEN 0 AND 100",
            name="ck_category_scores_raw",
        ),
        sa.ForeignKeyConstraint(
            ["score_execution_id"], ["score_executions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "score_execution_id",
            "category_id",
            name="uq_category_scores_execution_category",
        ),
    )
    op.create_index("ix_category_scores_execution", "category_scores", ["score_execution_id"])

    op.create_table(
        "metric_contributions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("score_execution_id", sa.UUID(), nullable=False),
        sa.Column("category_score_id", sa.UUID(), nullable=True),
        sa.Column("metric_id", sa.String(100), nullable=False),
        sa.Column("raw_value", json_type, nullable=False),
        sa.Column("normalized_value", sa.Float(), nullable=True),
        sa.Column("configured_weight", sa.Float(), nullable=False),
        sa.Column("normalized_weight", sa.Float(), nullable=True),
        sa.Column("contribution", sa.Float(), nullable=True),
        sa.Column("inclusion_status", sa.String(50), nullable=False),
        sa.Column("exclusion_reason", sa.String(255), nullable=True),
        sa.Column("threshold_decision", json_type, nullable=False),
        sa.Column("deduction_or_adjustment", json_type, nullable=False),
        sa.Column("evidence_references", json_type, nullable=False),
        sa.ForeignKeyConstraint(["category_score_id"], ["category_scores.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["score_execution_id"], ["score_executions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "score_execution_id",
            "metric_id",
            name="uq_metric_contributions_execution_metric",
        ),
    )
    op.create_index(
        "ix_metric_contributions_execution",
        "metric_contributions",
        ["score_execution_id"],
    )
    op.create_index("ix_metric_contributions_metric", "metric_contributions", ["metric_id"])

    op.create_table(
        "score_explanations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("score_execution_id", sa.UUID(), nullable=False),
        sa.Column("formula_summary", sa.Text(), nullable=False),
        sa.Column("profile_summary", sa.Text(), nullable=False),
        sa.Column("normalization_decisions", json_type, nullable=False),
        sa.Column("caps_floors_deductions", json_type, nullable=False),
        sa.Column("limitations", json_type, nullable=False),
        sa.Column("reproducibility_payload", json_type, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["score_execution_id"], ["score_executions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("score_execution_id", name="uq_score_explanations_execution"),
    )
    op.create_index("ix_score_explanations_created", "score_explanations", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_score_explanations_created", table_name="score_explanations")
    op.drop_table("score_explanations")
    op.drop_index("ix_metric_contributions_metric", table_name="metric_contributions")
    op.drop_index("ix_metric_contributions_execution", table_name="metric_contributions")
    op.drop_table("metric_contributions")
    op.drop_index("ix_category_scores_execution", table_name="category_scores")
    op.drop_table("category_scores")
    op.drop_index("ix_score_snapshots_created", table_name="score_snapshots")
    op.drop_table("score_snapshots")
    op.drop_index("ix_score_executions_website_created", table_name="score_executions")
    op.drop_index("ix_score_executions_run_created", table_name="score_executions")
    op.drop_index("ix_score_executions_project_status", table_name="score_executions")
    op.drop_table("score_executions")
