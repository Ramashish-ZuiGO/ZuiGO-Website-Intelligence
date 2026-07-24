import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RepositoryProvider(StrEnum):
    LOCAL = "local"
    GITHUB = "github"
    GITLAB = "gitlab"
    BITBUCKET = "bitbucket"
    AZURE_DEVOPS = "azure_devops"


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


class RepositoryConnectionCreate(BaseModel):
    project_id: uuid.UUID
    provider: str
    display_name: str
    local_root: str
    remote_url: str | None = None


class RepositoryConnectionUpdate(BaseModel):
    display_name: str | None = None
    local_root: str | None = None
    status: str | None = None
    remote_url: str | None = None


class RepositoryConnectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    provider: str
    display_name: str
    local_root: str
    remote_url: str | None
    default_branch: str | None
    current_branch: str | None
    current_commit_sha: str | None
    framework_summary: dict[str, Any] | None
    status: str
    last_scan_execution_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class RepositoryConnectionValidate(BaseModel):
    local_root: str
    is_git: bool
    error_message: str | None = None


class RepositoryScanStartRequest(BaseModel):
    connection_id: uuid.UUID
    commit_sha: str | None = None
    branch: str | None = None


class RepositoryScanExecutionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    connection_id: uuid.UUID
    requested_commit_sha: str | None
    resolved_commit_sha: str | None
    branch: str | None
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    total_files_discovered: int
    eligible_files: int
    scanned_files: int
    skipped_files: int
    failed_files: int
    ignored_directories: list[str] | None
    detected_frameworks: dict[str, Any] | None
    limitations: list[str] | None
    failure_reason_code: str | None
    failure_explanation: str | None
    created_at: datetime
    updated_at: datetime


class RepositoryScanSummaryRead(BaseModel):
    total_files_discovered: int
    eligible_files: int
    scanned_files: int
    skipped_files: int
    failed_files: int
    total_technologies: int
    total_actions_matched: int
    located_actions: int
    unlocated_actions: int


class RepositoryFileIndexRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    scan_execution_id: uuid.UUID
    relative_path: str
    normalized_path: str
    extension: str | None
    detected_language: str | None
    file_size: int
    line_count: int
    content_hash: str | None
    git_status: str | None
    framework_role: str | None
    module_hints: dict[str, Any] | None
    exported_symbols: list[str] | None
    redacted: bool
    redaction_metadata: dict[str, Any] | None
    first_lines: str | None = Field(default=None, exclude=True)
    scan_status: str
    skip_reason: str | None
    created_at: datetime


class RepositoryFileDetailRead(RepositoryFileIndexRead):
    first_lines: str | None = None


class DetectedTechnologyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    scan_execution_id: uuid.UUID
    technology: str
    confidence: str
    supporting_files: list[str] | None
    evidence: dict[str, Any] | None
    limitations: str | None
    created_at: datetime


class ActionMatchingStartRequest(BaseModel):
    connection_id: uuid.UUID
    scan_execution_id: uuid.UUID
    generation_execution_id: uuid.UUID | None = None


class ActionMatchingExecutionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    connection_id: uuid.UUID
    scan_execution_id: uuid.UUID
    generation_execution_id: uuid.UUID | None
    status: str
    total_actions: int
    located_actions: int
    unlocated_actions: int
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ActionRepositoryMatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    matching_execution_id: uuid.UUID
    action_item_id: uuid.UUID
    repository_file_id: uuid.UUID | None
    relative_path: str | None
    start_line: int | None
    end_line: int | None
    symbol_name: str | None
    match_reason: str | None
    evidence_snippet: str | None
    match_confidence: str
    mapping_strategy: str | None
    is_primary: bool
    created_at: datetime


class PaginatedResponse(BaseModel):
    items: list[Any]
    page: int
    page_size: int
    total: int
    total_pages: int
