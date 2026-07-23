import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class ActionGenerationExecutionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    website_id: uuid.UUID
    discovery_run_id: uuid.UUID | None
    page_analysis_execution_id: uuid.UUID
    status: str
    total_findings_processed: int
    total_actions_generated: int
    unsupported_finding_count: int
    insufficient_evidence_count: int
    duplicate_within_execution_count: int
    historical_equivalent_count: int
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ActionGroupRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    generation_execution_id: uuid.UUID
    website_id: uuid.UUID
    grouping_key: str
    issue_title: str
    category: str
    severity: str
    priority_score: int
    priority_formula_version: str
    confidence: str
    estimated_effort: str
    business_impact: str
    responsible_area: str
    responsible_role: str
    action_location: str
    why_this_matters: str
    exact_correction: str
    implementation_steps: str
    verification_steps: str
    expected_result: str
    limitations: str
    evidence_summary: dict[str, Any]
    source_audit: str
    priority_components: dict[str, Any]
    affected_page_count: int
    status: str
    created_at: datetime
    updated_at: datetime


class ActionItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    generation_execution_id: uuid.UUID
    action_group_id: uuid.UUID | None
    website_id: uuid.UUID
    page_analysis_run_id: uuid.UUID | None
    website_page_id: uuid.UUID
    source_finding_identity: str
    source_page_analysis_run_id: uuid.UUID | None
    requested_url: str | None
    final_url: str | None
    page_title: str | None
    issue_title: str
    issue_category: str
    severity: str
    priority_score: int
    priority_formula_version: str
    priority_components: dict[str, Any]
    confidence: str
    confidence_percent: int
    estimated_effort: str
    business_impact: str
    responsible_area: str
    responsible_role: str
    action_location: str
    why_this_matters: str
    exact_correction: str
    implementation_steps: str
    verification_steps: str
    expected_result: str
    limitations: str
    evidence_summary: dict[str, Any]
    source_audit: str
    status: str
    created_at: datetime
    updated_at: datetime


class ActionStatusHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    action_item_id: uuid.UUID
    previous_status: str
    new_status: str
    reason: str | None
    actor: str | None
    source: str
    changed_at: datetime
    created_at: datetime


class ActionGroupDetailRead(ActionGroupRead):
    actions: list[ActionItemRead] = []


class ActionItemDetailRead(ActionItemRead):
    status_history: list[ActionStatusHistoryRead] = []


class ActionPlanSummary(BaseModel):
    website_id: uuid.UUID
    generation_execution_id: uuid.UUID | None
    total_actions: int
    total_open: int
    total_acknowledged: int
    total_in_progress: int
    total_resolved: int
    total_ignored: int
    total_reopened: int
    critical_actions: int
    high_priority_actions: int
    pages_requiring_correction: int
    grouped_issues: int
    average_priority: float | None
    generation_status: str | None
    generation_coverage: int | None


class PaginatedResponse(BaseModel):
    items: list[Any]
    page: int
    page_size: int
    total: int
    total_pages: int


class StatusUpdateRequest(BaseModel):
    status: str
    reason: str | None = None
    actor: str | None = None
    source: str = "manual"


class BulkStatusUpdateRequest(BaseModel):
    action_ids: list[uuid.UUID]
    status: str
    reason: str | None = None
    actor: str | None = None
    source: str = "manual"


class BulkStatusUpdateResult(BaseModel):
    total: int
    succeeded: int
    failed: int
    failures: list[dict[str, Any]] = []


class ActionGenerationStartResponse(BaseModel):
    status: str
    generation_execution_id: uuid.UUID
    page_analysis_execution_id: uuid.UUID
