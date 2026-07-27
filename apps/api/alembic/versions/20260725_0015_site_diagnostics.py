"""Add persistent site-wide diagnostic executions, findings, and occurrences.

Revision ID: 20260725_0015
Revises: 20260725_0014
Create Date: 2026-07-27 12:50:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260725_0015"
down_revision: str | None = "20260725_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "site_diagnostic_executions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("execution_id", sa.UUID(), nullable=False),
        sa.Column("website_id", sa.UUID(), nullable=False),
        sa.Column("analysis_run_id", sa.UUID(), nullable=False),
        sa.Column("workflow_id", sa.String(length=100), nullable=False),
        sa.Column("workflow_version", sa.String(length=50), nullable=False),
        sa.Column("selected_profile_id", sa.String(length=100), nullable=False),
        sa.Column("selected_profile_version", sa.String(length=50), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("evidence_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("diagnostic_engine_version", sa.String(length=50), nullable=False),
        sa.Column("rule_registry_version", sa.String(length=50), nullable=False),
        sa.Column(
            "status",
            sa.String(length=50),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column(
            "total_page_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "processed_page_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "failed_page_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "evidence_coverage_numerator",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "evidence_coverage_denominator",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "evidence_coverage_ratio",
            sa.Float(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("error_metadata", json_type, nullable=False),
        sa.Column("partial_completion_metadata", json_type, nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "evidence_coverage_denominator >= 0",
            name="ck_site_diagnostic_executions_coverage_denominator",
        ),
        sa.CheckConstraint(
            "evidence_coverage_numerator >= 0 "
            "AND evidence_coverage_numerator <= evidence_coverage_denominator",
            name="ck_site_diagnostic_executions_coverage_counts",
        ),
        sa.CheckConstraint(
            "evidence_coverage_ratio >= 0 AND evidence_coverage_ratio <= 1",
            name="ck_site_diagnostic_executions_coverage_ratio",
        ),
        sa.CheckConstraint(
            "failed_page_count >= 0 AND failed_page_count <= processed_page_count",
            name="ck_site_diagnostic_executions_failed_page_count",
        ),
        sa.CheckConstraint(
            "processed_page_count >= 0 AND processed_page_count <= total_page_count",
            name="ck_site_diagnostic_executions_processed_page_count",
        ),
        sa.CheckConstraint(
            "total_page_count >= 0",
            name="ck_site_diagnostic_executions_total_page_count",
        ),
        sa.ForeignKeyConstraint(
            ["analysis_run_id"],
            ["analysis_runs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["website_id"],
            ["websites.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "execution_id",
            name="uq_site_diagnostic_executions_execution_id",
        ),
        sa.UniqueConstraint(
            "analysis_run_id",
            "idempotency_key",
            name="uq_site_diagnostic_executions_run_idempotency",
        ),
    )
    op.create_index(
        "ix_site_diagnostic_executions_run_created",
        "site_diagnostic_executions",
        ["analysis_run_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_site_diagnostic_executions_status",
        "site_diagnostic_executions",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_site_diagnostic_executions_website_created",
        "site_diagnostic_executions",
        ["website_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "site_diagnostic_findings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("execution_id", sa.UUID(), nullable=False),
        sa.Column("rule_id", sa.String(length=255), nullable=False),
        sa.Column("rule_version", sa.String(length=50), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("severity", sa.String(length=50), nullable=False),
        sa.Column("confidence", sa.String(length=50), nullable=False),
        sa.Column("scope", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("why_it_matters", sa.Text(), nullable=False),
        sa.Column("affected_page_count", sa.Integer(), nullable=False),
        sa.Column("total_eligible_page_count", sa.Integer(), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("affected_ratio", sa.Float(), nullable=False),
        sa.Column("evidence_summary", sa.Text(), nullable=False),
        sa.Column("evidence_references", json_type, nullable=False),
        sa.Column("remediation_guidance", sa.Text(), nullable=False),
        sa.Column("responsible_role", sa.String(length=255), nullable=False),
        sa.Column("verification_guidance", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "affected_page_count >= 0 AND affected_page_count <= total_eligible_page_count",
            name="ck_site_diagnostic_findings_affected_page_count",
        ),
        sa.CheckConstraint(
            "affected_ratio >= 0 AND affected_ratio <= 1",
            name="ck_site_diagnostic_findings_affected_ratio",
        ),
        sa.CheckConstraint(
            "confidence IN ('high', 'medium', 'low', 'unavailable')",
            name="ck_site_diagnostic_findings_confidence",
        ),
        sa.CheckConstraint(
            "total_eligible_page_count >= 0",
            name="ck_site_diagnostic_findings_eligible_page_count",
        ),
        sa.CheckConstraint(
            "occurrence_count >= affected_page_count",
            name="ck_site_diagnostic_findings_occurrence_count",
        ),
        sa.CheckConstraint(
            "scope IN ('page', 'section', 'template', 'site')",
            name="ck_site_diagnostic_findings_scope",
        ),
        sa.CheckConstraint(
            "severity IN ('critical', 'high', 'medium', 'low', 'info')",
            name="ck_site_diagnostic_findings_severity",
        ),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["site_diagnostic_executions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_site_diagnostic_findings_execution_category",
        "site_diagnostic_findings",
        ["execution_id", "category"],
        unique=False,
    )
    op.create_index(
        "ix_site_diagnostic_findings_execution_rule",
        "site_diagnostic_findings",
        ["execution_id", "rule_id"],
        unique=False,
    )
    op.create_index(
        "ix_site_diagnostic_findings_execution_scope",
        "site_diagnostic_findings",
        ["execution_id", "scope"],
        unique=False,
    )
    op.create_index(
        "ix_site_diagnostic_findings_execution_severity",
        "site_diagnostic_findings",
        ["execution_id", "severity"],
        unique=False,
    )

    op.create_table(
        "site_diagnostic_occurrences",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("finding_id", sa.UUID(), nullable=False),
        sa.Column("website_page_id", sa.UUID(), nullable=True),
        sa.Column("normalized_url", sa.String(length=2048), nullable=True),
        sa.Column("evidence_reference", sa.String(length=255), nullable=False),
        sa.Column("occurrence_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("element_selector", sa.Text(), nullable=True),
        sa.Column("resource_url", sa.String(length=2048), nullable=True),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("context", json_type, nullable=False),
        sa.Column("observed_value", sa.Text(), nullable=True),
        sa.Column("expected_value", sa.Text(), nullable=True),
        sa.Column("supporting_evidence", json_type, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "website_page_id IS NOT NULL OR normalized_url IS NOT NULL",
            name="ck_site_diagnostic_occurrences_page_reference",
        ),
        sa.ForeignKeyConstraint(
            ["finding_id"],
            ["site_diagnostic_findings.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["website_page_id"],
            ["website_pages.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "finding_id",
            "occurrence_fingerprint",
            name="uq_site_diagnostic_occurrences_fingerprint",
        ),
    )
    op.create_index(
        "ix_site_diagnostic_occurrences_evidence_reference",
        "site_diagnostic_occurrences",
        ["evidence_reference"],
        unique=False,
    )
    op.create_index(
        "ix_site_diagnostic_occurrences_finding_id",
        "site_diagnostic_occurrences",
        ["finding_id"],
        unique=False,
    )
    op.create_index(
        "ix_site_diagnostic_occurrences_website_page_id",
        "site_diagnostic_occurrences",
        ["website_page_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_site_diagnostic_occurrences_website_page_id",
        table_name="site_diagnostic_occurrences",
    )
    op.drop_index(
        "ix_site_diagnostic_occurrences_finding_id",
        table_name="site_diagnostic_occurrences",
    )
    op.drop_index(
        "ix_site_diagnostic_occurrences_evidence_reference",
        table_name="site_diagnostic_occurrences",
    )
    op.drop_table("site_diagnostic_occurrences")

    op.drop_index(
        "ix_site_diagnostic_findings_execution_severity",
        table_name="site_diagnostic_findings",
    )
    op.drop_index(
        "ix_site_diagnostic_findings_execution_scope",
        table_name="site_diagnostic_findings",
    )
    op.drop_index(
        "ix_site_diagnostic_findings_execution_rule",
        table_name="site_diagnostic_findings",
    )
    op.drop_index(
        "ix_site_diagnostic_findings_execution_category",
        table_name="site_diagnostic_findings",
    )
    op.drop_table("site_diagnostic_findings")

    op.drop_index(
        "ix_site_diagnostic_executions_website_created",
        table_name="site_diagnostic_executions",
    )
    op.drop_index(
        "ix_site_diagnostic_executions_status",
        table_name="site_diagnostic_executions",
    )
    op.drop_index(
        "ix_site_diagnostic_executions_run_created",
        table_name="site_diagnostic_executions",
    )
    op.drop_table("site_diagnostic_executions")
