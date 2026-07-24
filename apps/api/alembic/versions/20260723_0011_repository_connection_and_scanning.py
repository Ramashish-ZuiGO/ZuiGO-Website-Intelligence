"""Add repository connection and scanning models.

Revision ID: 20260723_0011
Revises: 20260723_0010
"""
# ruff: noqa: E501

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260723_0011"
down_revision: str | Sequence[str] | None = "20260723_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "repository_connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column(
            "provider", sa.String(length=50), nullable=False, server_default=sa.text("'local'")
        ),
        sa.Column("display_name", sa.String(length=300), nullable=False),
        sa.Column("local_root", sa.Text(), nullable=False),
        sa.Column("remote_url", sa.Text()),
        sa.Column("default_branch", sa.String(length=200)),
        sa.Column("current_branch", sa.String(length=200)),
        sa.Column("current_commit_sha", sa.String(length=200)),
        sa.Column("framework_summary", postgresql.JSONB()),
        sa.Column(
            "status", sa.String(length=30), nullable=False, server_default=sa.text("'active'")
        ),
        sa.Column("last_scan_execution_id", sa.Uuid()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", name="uq_repository_connections_project"),
    )
    op.create_index("ix_repository_connections_status", "repository_connections", ["status"])
    op.create_index(
        "ix_repository_connections_project_id", "repository_connections", ["project_id"]
    )

    op.create_table(
        "repository_scan_executions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("requested_commit_sha", sa.String(length=200)),
        sa.Column("resolved_commit_sha", sa.String(length=200)),
        sa.Column("branch", sa.String(length=200)),
        sa.Column(
            "status", sa.String(length=30), nullable=False, server_default=sa.text("'queued'")
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "total_files_discovered", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("eligible_files", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("scanned_files", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("skipped_files", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("failed_files", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("ignored_directories", postgresql.JSONB()),
        sa.Column("detected_frameworks", postgresql.JSONB()),
        sa.Column("limitations", postgresql.JSONB()),
        sa.Column("failure_reason_code", sa.String(length=100)),
        sa.Column("failure_explanation", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["repository_connections.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_repo_scan_connection_id", "repository_scan_executions", ["connection_id"])
    op.create_index("ix_repo_scan_status", "repository_scan_executions", ["status"])
    op.create_index(
        "ix_repo_scan_commit_sha", "repository_scan_executions", ["requested_commit_sha"]
    )

    op.create_table(
        "repository_file_index",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scan_execution_id", sa.Uuid(), nullable=False),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("normalized_path", sa.Text(), nullable=False),
        sa.Column("extension", sa.String(length=50)),
        sa.Column("detected_language", sa.String(length=100)),
        sa.Column("file_size", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("line_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("content_hash", sa.String(length=64)),
        sa.Column("git_status", sa.String(length=30)),
        sa.Column("framework_role", sa.String(length=100)),
        sa.Column("module_hints", postgresql.JSONB()),
        sa.Column("exported_symbols", postgresql.JSONB()),
        sa.Column("redacted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("redaction_metadata", postgresql.JSONB()),
        sa.Column("first_lines", sa.Text()),
        sa.Column(
            "scan_status", sa.String(length=30), nullable=False, server_default=sa.text("'scanned'")
        ),
        sa.Column("skip_reason", sa.String(length=200)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["scan_execution_id"], ["repository_scan_executions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scan_execution_id", "relative_path", name="uq_repo_file_index_scan_path"
        ),
    )
    op.create_index("ix_repo_file_scan_id", "repository_file_index", ["scan_execution_id"])
    op.create_index("ix_repo_file_extension", "repository_file_index", ["extension"])
    op.create_index("ix_repo_file_language", "repository_file_index", ["detected_language"])
    op.create_index("ix_repo_file_status", "repository_file_index", ["scan_status"])
    op.create_index("ix_repo_file_framework_role", "repository_file_index", ["framework_role"])
    op.create_index("ix_repo_file_hash", "repository_file_index", ["content_hash"])
    op.create_index("ix_repo_file_path", "repository_file_index", ["normalized_path"])

    op.create_table(
        "detected_technologies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scan_execution_id", sa.Uuid(), nullable=False),
        sa.Column("technology", sa.String(length=200), nullable=False),
        sa.Column("confidence", sa.String(length=30), nullable=False),
        sa.Column("supporting_files", postgresql.JSONB()),
        sa.Column("evidence", postgresql.JSONB()),
        sa.Column("limitations", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["scan_execution_id"], ["repository_scan_executions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scan_execution_id", "technology", name="uq_detected_tech_scan_tech"),
    )
    op.create_index("ix_detected_tech_scan_id", "detected_technologies", ["scan_execution_id"])
    op.create_index("ix_detected_tech_confidence", "detected_technologies", ["confidence"])

    op.create_table(
        "action_matching_executions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("scan_execution_id", sa.Uuid(), nullable=False),
        sa.Column("generation_execution_id", sa.Uuid()),
        sa.Column(
            "status", sa.String(length=30), nullable=False, server_default=sa.text("'queued'")
        ),
        sa.Column("total_actions", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("located_actions", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("unlocated_actions", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["repository_connections.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["scan_execution_id"], ["repository_scan_executions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["generation_execution_id"], ["action_generation_executions.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_action_match_exec_scan", "action_matching_executions", ["scan_execution_id"]
    )
    op.create_index(
        "ix_action_match_exec_gen", "action_matching_executions", ["generation_execution_id"]
    )
    op.create_index("ix_action_match_exec_status", "action_matching_executions", ["status"])

    op.create_table(
        "action_repository_matches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("matching_execution_id", sa.Uuid(), nullable=False),
        sa.Column("action_item_id", sa.Uuid(), nullable=False),
        sa.Column("repository_file_id", sa.Uuid()),
        sa.Column("relative_path", sa.Text()),
        sa.Column("start_line", sa.Integer()),
        sa.Column("end_line", sa.Integer()),
        sa.Column("symbol_name", sa.String(length=300)),
        sa.Column("match_reason", sa.Text()),
        sa.Column("evidence_snippet", sa.Text()),
        sa.Column(
            "match_confidence",
            sa.String(length=30),
            nullable=False,
            server_default=sa.text("'unlocated'"),
        ),
        sa.Column("mapping_strategy", sa.String(length=100)),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["matching_execution_id"], ["action_matching_executions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["action_item_id"], ["action_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["repository_file_id"], ["repository_file_index.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "match_confidence IN ('high', 'medium', 'low', 'unlocated')",
            name="ck_action_repo_match_confidence",
        ),
        sa.UniqueConstraint(
            "matching_execution_id",
            "action_item_id",
            "repository_file_id",
            name="uq_action_repo_match_exec_action_file",
        ),
    )
    op.create_index(
        "ix_action_repo_match_exec", "action_repository_matches", ["matching_execution_id"]
    )
    op.create_index("ix_action_repo_match_action", "action_repository_matches", ["action_item_id"])
    op.create_index(
        "ix_action_repo_match_file", "action_repository_matches", ["repository_file_id"]
    )
    op.create_index(
        "ix_action_repo_match_confidence", "action_repository_matches", ["match_confidence"]
    )
    op.create_index("ix_action_repo_match_path", "action_repository_matches", ["relative_path"])

    # Add circular FK referencing repository_scan_executions
    op.create_foreign_key(
        "fk_repository_connections_last_scan_execution_id",
        "repository_connections",
        "repository_scan_executions",
        ["last_scan_execution_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_repository_connections_last_scan_execution_id",
        "repository_connections",
        type_="foreignkey",
    )

    for idx in (
        "ix_action_repo_match_path",
        "ix_action_repo_match_confidence",
        "ix_action_repo_match_file",
        "ix_action_repo_match_action",
        "ix_action_repo_match_exec",
    ):
        op.execute(f'DROP INDEX IF EXISTS "{idx}" CASCADE')
    op.drop_table("action_repository_matches")

    for idx in (
        "ix_action_match_exec_status",
        "ix_action_match_exec_gen",
        "ix_action_match_exec_scan",
    ):
        op.execute(f'DROP INDEX IF EXISTS "{idx}" CASCADE')
    op.drop_table("action_matching_executions")

    for idx in (
        "ix_detected_tech_confidence",
        "ix_detected_tech_scan_id",
    ):
        op.execute(f'DROP INDEX IF EXISTS "{idx}" CASCADE')
    op.drop_table("detected_technologies")

    for idx in (
        "ix_repo_file_path",
        "ix_repo_file_hash",
        "ix_repo_file_framework_role",
        "ix_repo_file_status",
        "ix_repo_file_language",
        "ix_repo_file_extension",
        "ix_repo_file_scan_id",
    ):
        op.execute(f'DROP INDEX IF EXISTS "{idx}" CASCADE')
    op.drop_table("repository_file_index")

    for idx in (
        "ix_repo_scan_commit_sha",
        "ix_repo_scan_status",
        "ix_repo_scan_connection_id",
    ):
        op.execute(f'DROP INDEX IF EXISTS "{idx}" CASCADE')
    op.drop_table("repository_scan_executions")

    for idx in (
        "ix_repository_connections_project_id",
        "ix_repository_connections_status",
    ):
        op.execute(f'DROP INDEX IF EXISTS "{idx}" CASCADE')
    op.drop_table("repository_connections")
