from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SiteDiagnosticExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    execution_id: UUID
    website_id: UUID
    analysis_run_id: UUID
    workflow_id: str
    workflow_version: str
    selected_profile_id: str
    selected_profile_version: str
    input_fingerprint: str
    evidence_fingerprint: str
    idempotency_key: str
    diagnostic_engine_version: str
    rule_registry_version: str
    status: str
    total_page_count: int
    processed_page_count: int
    failed_page_count: int
    evidence_coverage_numerator: int
    evidence_coverage_denominator: int
    evidence_coverage_ratio: float
    error_metadata: dict[str, Any]
    partial_completion_metadata: dict[str, Any]
    started_at: datetime
    completed_at: datetime | None
    created_at: datetime


class SiteDiagnosticOccurrenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    finding_id: UUID
    website_page_id: UUID | None
    normalized_url: str | None
    evidence_reference: str
    occurrence_fingerprint: str
    element_selector: str | None
    resource_url: str | None
    location: str | None
    context: dict[str, Any]
    observed_value: str | None
    expected_value: str | None
    supporting_evidence: dict[str, Any]
    created_at: datetime


class SiteDiagnosticFindingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    execution_id: UUID
    rule_id: str
    rule_version: str
    category: str
    severity: str
    confidence: str
    scope: str
    title: str
    description: str
    why_it_matters: str
    affected_page_count: int
    total_eligible_page_count: int
    occurrence_count: int
    affected_ratio: float
    evidence_summary: str
    evidence_references: list[dict[str, Any]]
    remediation_guidance: str
    responsible_role: str
    verification_guidance: str
    created_at: datetime


class SiteDiagnosticFindingDetailResponse(SiteDiagnosticFindingResponse):
    occurrences: list[SiteDiagnosticOccurrenceResponse]


class SiteDiagnosticLinkGraphNode(BaseModel):
    page_id: UUID
    normalized_url: str
    eligibility_status: str
    crawl_depth: int
    inbound_link_count: int
    outbound_link_count: int
    outbound_evidence_available: bool
    http_status_code: int | None
    canonical_values: list[str]


class SiteDiagnosticLinkGraphEdge(BaseModel):
    source_page_id: UUID
    source_url: str
    raw_target: str
    target_url: str
    target_page_id: UUID | None
    target_http_status: int | None
    redirect_chain: list[dict[str, Any]]
    target_eligibility_status: str | None
    target_robots_status: str | None
    target_robots_directives: dict[str, Any]
    target_canonical_values: list[str]
    evidence_reference: str


class SiteDiagnosticMalformedEdge(BaseModel):
    source_page_id: UUID
    source_url: str
    raw_target: str
    evidence_reference: str


class SiteDiagnosticLinkGraphResponse(BaseModel):
    execution_id: UUID
    website_id: UUID
    evidence_complete: bool
    discovery_run_id: UUID | None
    total_nodes: int
    total_edges: int
    total_malformed_edges: int
    node_offset: int
    node_limit: int
    edge_offset: int
    edge_limit: int
    nodes: list[SiteDiagnosticLinkGraphNode]
    edges: list[SiteDiagnosticLinkGraphEdge]
    malformed_edges: list[SiteDiagnosticMalformedEdge]


class SiteDiagnosticGenerateRequest(BaseModel):
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=255)
