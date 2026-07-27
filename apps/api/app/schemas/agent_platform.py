import re
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

SEMANTIC_VERSION_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
REGISTRY_ID_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")


class RegistryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ExecutionStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNAVAILABLE = "unavailable"


class Permission(StrEnum):
    DATABASE_READ = "database_read"
    DATABASE_WRITE = "database_write"
    NETWORK = "network"
    BROWSER = "browser"
    FILESYSTEM_READ = "filesystem_read"
    LLM_PROVIDER = "llm_provider"


class IdempotencyRequirement(StrEnum):
    REQUIRED = "required"
    SUPPORTED = "supported"
    NOT_APPLICABLE = "not_applicable"


class MemoryPolicy(StrEnum):
    NONE = "none"
    EXECUTION_SCOPED = "execution_scoped"
    EVIDENCE_REFERENCES_ONLY = "evidence_references_only"


class LLMPolicy(StrEnum):
    PROHIBITED = "prohibited"
    OPTIONAL_APPROVED_PROVIDER = "optional_approved_provider"


class PartialFailureBehavior(StrEnum):
    FAIL_FAST = "fail_fast"
    PRESERVE_PARTIAL = "preserve_partial"
    MARK_UNAVAILABLE = "mark_unavailable"


class SideEffectClassification(StrEnum):
    NONE = "none"
    READ_ONLY = "read_only"
    PERSISTENT_WRITE = "persistent_write"
    EXTERNAL_REQUEST = "external_request"


class SecretHandlingPolicy(StrEnum):
    NONE = "none"
    RUNTIME_ONLY = "runtime_only"
    REDACTED_RUNTIME_ONLY = "redacted_runtime_only"


class AvailabilityState(StrEnum):
    AVAILABLE = "available"
    CONDITIONAL = "conditional"
    UNAVAILABLE = "unavailable"


class WorkflowCondition(StrEnum):
    ALWAYS = "always"
    REPOSITORY_CONFIGURED = "repository_configured"


class RetryPolicy(RegistryModel):
    max_attempts: int = Field(ge=1, le=10)
    backoff_seconds: int = Field(ge=0, le=3600)
    retryable_failures: tuple[str, ...]


class CostTokenBudget(RegistryModel):
    max_tokens: int | None = Field(default=None, ge=0)
    max_cost_usd: float | None = Field(default=None, ge=0)


class AgentDefinition(RegistryModel):
    agent_id: str
    version: str
    name: str
    purpose: str
    supported_goals: tuple[str, ...] = Field(min_length=1)
    input_schema_ref: str
    output_schema_ref: str
    allowed_tool_ids: tuple[str, ...]
    dependency_agent_ids: tuple[str, ...]
    timeout_seconds: int = Field(ge=1, le=86400)
    retry_policy: RetryPolicy
    idempotency_requirement: IdempotencyRequirement
    memory_policy: MemoryPolicy
    llm_policy: LLMPolicy
    permissions: tuple[Permission, ...]
    cost_token_budget: CostTokenBudget | None
    partial_failure_behavior: PartialFailureBehavior
    limitations: str

    @field_validator("agent_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not REGISTRY_ID_PATTERN.fullmatch(value):
            raise ValueError("Agent ID must use lower snake case")
        return value

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        if not SEMANTIC_VERSION_PATTERN.fullmatch(value):
            raise ValueError("Version must use semantic MAJOR.MINOR.PATCH format")
        return value

    @field_validator(
        "name",
        "purpose",
        "input_schema_ref",
        "output_schema_ref",
        "limitations",
    )
    @classmethod
    def validate_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Required text cannot be empty")
        return normalized

    @field_validator("supported_goals")
    @classmethod
    def validate_goals(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(goal.strip() for goal in value)
        if any(not goal for goal in normalized):
            raise ValueError("Supported goals cannot be empty")
        if len(normalized) != len(set(normalized)):
            raise ValueError("Supported goals must be unique")
        return normalized


class ToolDefinition(RegistryModel):
    tool_id: str
    version: str
    input_schema_ref: str
    output_schema_ref: str
    permissions: tuple[Permission, ...]
    timeout_seconds: int = Field(ge=1, le=86400)
    retry_policy: RetryPolicy
    side_effect_classification: SideEffectClassification
    idempotency_behavior: IdempotencyRequirement
    evidence_produced: tuple[str, ...] = Field(min_length=1)
    secret_handling_policy: SecretHandlingPolicy
    availability_state: AvailabilityState
    limitations: str

    @field_validator("tool_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not REGISTRY_ID_PATTERN.fullmatch(value):
            raise ValueError("Tool ID must use lower snake case")
        return value

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        if not SEMANTIC_VERSION_PATTERN.fullmatch(value):
            raise ValueError("Version must use semantic MAJOR.MINOR.PATCH format")
        return value

    @field_validator("input_schema_ref", "output_schema_ref", "limitations")
    @classmethod
    def validate_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Required text cannot be empty")
        return normalized


class WorkflowNodeDefinition(RegistryModel):
    agent_id: str
    depends_on: tuple[str, ...] = ()
    optional_dependencies: tuple[str, ...] = ()
    condition: WorkflowCondition = WorkflowCondition.ALWAYS


class WorkflowDefinition(RegistryModel):
    workflow_id: str
    version: str
    name: str
    purpose: str
    orchestrator_id: str
    orchestrator_version: str
    deterministic: bool
    nodes: tuple[WorkflowNodeDefinition, ...] = Field(min_length=1)
    entry_agent_ids: tuple[str, ...] = Field(min_length=1)
    terminal_agent_ids: tuple[str, ...] = Field(min_length=1)
    deterministic_order: tuple[str, ...] = Field(min_length=1)
    limitations: str

    @field_validator("workflow_id", "orchestrator_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not REGISTRY_ID_PATTERN.fullmatch(value):
            raise ValueError("Registry IDs must use lower snake case")
        return value

    @field_validator("version", "orchestrator_version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        if not SEMANTIC_VERSION_PATTERN.fullmatch(value):
            raise ValueError("Version must use semantic MAJOR.MINOR.PATCH format")
        return value

    @field_validator("name", "purpose", "limitations")
    @classmethod
    def validate_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Required text cannot be empty")
        return normalized


class WebsiteAnalysisInput(BaseModel):
    project_id: UUID
    analysis_run_id: UUID | None = None
    website_id: UUID


class RepositoryAnalysisInput(BaseModel):
    project_id: UUID
    repository_connection_id: UUID
    evidence_references: list[str] = Field(default_factory=list)


class EvidenceValidationInput(BaseModel):
    execution_id: UUID
    evidence_references: list[str]


class RemediationInput(BaseModel):
    execution_id: UUID
    validated_evidence_references: list[str]
    repository_artifact_references: list[str] = Field(default_factory=list)


class ReportInput(BaseModel):
    execution_id: UUID
    evidence_references: list[str]
    remediation_references: list[str]


class URLNormalizationInput(BaseModel):
    raw_url: str
    approved_origin: str


class PageToolInput(BaseModel):
    execution_id: UUID
    page_url: str
    evidence_reference: str | None = None


class EvidenceRetrievalInput(BaseModel):
    execution_id: UUID
    evidence_references: list[str]


class ApprovedLLMInput(BaseModel):
    execution_id: UUID
    grounded_evidence_references: list[str]
    structured_prompt: dict[str, Any]


class StructuredEvidenceOutput(BaseModel):
    status: ExecutionStatus
    evidence_references: list[str]
    structured_result: dict[str, Any] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)


class NormalizedURLOutput(BaseModel):
    status: ExecutionStatus
    normalized_url: str | None
    rejection_reason: str | None = None


class RemediationOutput(StructuredEvidenceOutput):
    remediation_references: list[str] = Field(default_factory=list)


class ReportOutput(StructuredEvidenceOutput):
    report_reference: str | None = None


class ApprovedLLMOutput(BaseModel):
    status: ExecutionStatus
    provider: str | None
    model_version: str | None
    structured_result: dict[str, Any] = Field(default_factory=dict)
