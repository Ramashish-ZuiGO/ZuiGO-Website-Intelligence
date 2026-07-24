import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.project import Project


class RepositoryProvider(StrEnum):
    LOCAL = "local"
    GITHUB = "github"
    GITLAB = "gitlab"
    BITBUCKET = "bitbucket"
    AZURE_DEVOPS = "azure_devops"


class RepositoryConnectionStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"


class ScanStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class FileScanStatus(StrEnum):
    SCANNED = "scanned"
    SKIPPED = "skipped"
    FAILED = "failed"


class MatchConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNLOCATED = "unlocated"


class LocationStatus(StrEnum):
    LOCATED = "located"
    MULTIPLE_CANDIDATES = "multiple_candidates"
    LOW_CONFIDENCE = "low_confidence"
    UNLOCATED = "unlocated"
    REPOSITORY_NOT_CONNECTED = "repository_not_connected"
    REPOSITORY_SCAN_UNAVAILABLE = "repository_scan_unavailable"


class MappingStrategy(StrEnum):
    EXACT_METADATA_ROUTE = "exact_metadata_route"
    PAGE_URL_TO_NEXTJS_ROUTE = "page_url_to_nextjs_route"
    COMPONENT_NAME_MATCH = "component_name_match"
    CONFIGURATION_KEY_MATCH = "configuration_key_match"
    AUDIT_CODE_MAPPING = "audit_code_mapping"
    FRAMEWORK_CONVENTION_MATCH = "framework_convention_match"
    MANIFEST_EVIDENCE = "manifest_evidence"
    CONTENT_SIGNATURE = "content_signature"
    FALLBACK_HEURISTIC = "fallback_heuristic"


class RepositoryConnection(Base):
    __tablename__ = "repository_connections"
    __table_args__ = (
        UniqueConstraint("project_id", name="uq_repository_connections_project"),
        Index("ix_repository_connections_status", "status"),
        Index("ix_repository_connections_project_id", "project_id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(50), default="local", nullable=False)
    display_name: Mapped[str] = mapped_column(String(300), nullable=False)
    local_root: Mapped[str] = mapped_column(Text, nullable=False)
    remote_url: Mapped[str | None] = mapped_column(Text)
    default_branch: Mapped[str | None] = mapped_column(String(200))
    current_branch: Mapped[str | None] = mapped_column(String(200))
    current_commit_sha: Mapped[str | None] = mapped_column(String(200))
    framework_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), default="active", nullable=False)
    last_scan_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("repository_scan_executions.id", ondelete="SET NULL", use_alter=True)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    project: Mapped["Project"] = relationship(back_populates="repository_connection")
    scan_executions: Mapped[list["RepositoryScanExecution"]] = relationship(
        back_populates="connection",
        cascade="all, delete-orphan",
        passive_deletes=True,
        foreign_keys="RepositoryScanExecution.connection_id",
    )


class RepositoryScanExecution(Base):
    __tablename__ = "repository_scan_executions"
    __table_args__ = (
        Index("ix_repo_scan_connection_id", "connection_id"),
        Index("ix_repo_scan_status", "status"),
        Index("ix_repo_scan_commit_sha", "requested_commit_sha"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repository_connections.id", ondelete="CASCADE"), nullable=False
    )
    requested_commit_sha: Mapped[str | None] = mapped_column(String(200))
    resolved_commit_sha: Mapped[str | None] = mapped_column(String(200))
    branch: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30), default="queued", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_files_discovered: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    eligible_files: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    scanned_files: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped_files: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_files: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ignored_directories: Mapped[list[str] | None] = mapped_column(JSON)
    detected_frameworks: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    limitations: Mapped[list[str] | None] = mapped_column(JSON)
    failure_reason_code: Mapped[str | None] = mapped_column(String(100))
    failure_explanation: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    connection: Mapped["RepositoryConnection"] = relationship(
        back_populates="scan_executions",
        foreign_keys=[connection_id],
    )
    files: Mapped[list["RepositoryFileIndex"]] = relationship(
        back_populates="scan_execution",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    technologies: Mapped[list["DetectedTechnology"]] = relationship(
        back_populates="scan_execution",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class RepositoryFileIndex(Base):
    __tablename__ = "repository_file_index"
    __table_args__ = (
        UniqueConstraint("scan_execution_id", "relative_path", name="uq_repo_file_index_scan_path"),
        Index("ix_repo_file_scan_id", "scan_execution_id"),
        Index("ix_repo_file_extension", "extension"),
        Index("ix_repo_file_language", "detected_language"),
        Index("ix_repo_file_status", "scan_status"),
        Index("ix_repo_file_framework_role", "framework_role"),
        Index("ix_repo_file_hash", "content_hash"),
        Index("ix_repo_file_path", "normalized_path"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    scan_execution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repository_scan_executions.id", ondelete="CASCADE"), nullable=False
    )
    relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_path: Mapped[str] = mapped_column(Text, nullable=False)
    extension: Mapped[str | None] = mapped_column(String(50))
    detected_language: Mapped[str | None] = mapped_column(String(100))
    file_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    line_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    git_status: Mapped[str | None] = mapped_column(String(30))
    framework_role: Mapped[str | None] = mapped_column(String(100))
    module_hints: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    exported_symbols: Mapped[list[str] | None] = mapped_column(JSON)
    redacted: Mapped[bool] = mapped_column(default=False, nullable=False)
    redaction_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    first_lines: Mapped[str | None] = mapped_column(Text)
    scan_status: Mapped[str] = mapped_column(String(30), default="scanned", nullable=False)
    skip_reason: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    scan_execution: Mapped["RepositoryScanExecution"] = relationship(back_populates="files")


class DetectedTechnology(Base):
    __tablename__ = "detected_technologies"
    __table_args__ = (
        UniqueConstraint("scan_execution_id", "technology", name="uq_detected_tech_scan_tech"),
        Index("ix_detected_tech_scan_id", "scan_execution_id"),
        Index("ix_detected_tech_confidence", "confidence"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    scan_execution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repository_scan_executions.id", ondelete="CASCADE"), nullable=False
    )
    technology: Mapped[str] = mapped_column(String(200), nullable=False)
    confidence: Mapped[str] = mapped_column(String(30), nullable=False)
    supporting_files: Mapped[list[str] | None] = mapped_column(JSON)
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    limitations: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    scan_execution: Mapped["RepositoryScanExecution"] = relationship(back_populates="technologies")


class ActionMatchingExecution(Base):
    __tablename__ = "action_matching_executions"
    __table_args__ = (
        Index("ix_action_match_exec_scan", "scan_execution_id"),
        Index("ix_action_match_exec_gen", "generation_execution_id"),
        Index("ix_action_match_exec_status", "status"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repository_connections.id", ondelete="CASCADE"), nullable=False
    )
    scan_execution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repository_scan_executions.id", ondelete="CASCADE"), nullable=False
    )
    generation_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("action_generation_executions.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(30), default="queued", nullable=False)
    total_actions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    located_actions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unlocated_actions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ActionRepositoryMatch(Base):
    __tablename__ = "action_repository_matches"
    __table_args__ = (
        CheckConstraint(
            "match_confidence IN ('high', 'medium', 'low', 'unlocated')",
            name="ck_action_repo_match_confidence",
        ),
        UniqueConstraint(
            "matching_execution_id",
            "action_item_id",
            "repository_file_id",
            name="uq_action_repo_match_exec_action_file",
        ),
        Index("ix_action_repo_match_exec", "matching_execution_id"),
        Index("ix_action_repo_match_action", "action_item_id"),
        Index("ix_action_repo_match_file", "repository_file_id"),
        Index("ix_action_repo_match_confidence", "match_confidence"),
        Index("ix_action_repo_match_path", "relative_path"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    matching_execution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("action_matching_executions.id", ondelete="CASCADE"), nullable=False
    )
    action_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("action_items.id", ondelete="CASCADE"), nullable=False
    )
    repository_file_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("repository_file_index.id", ondelete="SET NULL")
    )
    relative_path: Mapped[str | None] = mapped_column(Text)
    start_line: Mapped[int | None] = mapped_column(Integer)
    end_line: Mapped[int | None] = mapped_column(Integer)
    symbol_name: Mapped[str | None] = mapped_column(String(300))
    match_reason: Mapped[str | None] = mapped_column(Text)
    evidence_snippet: Mapped[str | None] = mapped_column(Text)
    match_confidence: Mapped[str] = mapped_column(String(30), default="unlocated", nullable=False)
    mapping_strategy: Mapped[str | None] = mapped_column(String(100))
    is_primary: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
