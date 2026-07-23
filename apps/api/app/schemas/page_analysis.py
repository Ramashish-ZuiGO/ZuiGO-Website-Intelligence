import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class PageAnalysisRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    website_page_id: uuid.UUID
    discovery_run_id: uuid.UUID | None
    page_analysis_execution_id: uuid.UUID
    analysis_level: int
    status: str
    failure_reason_code: str | None
    failure_reason_text: str | None
    analysis_started_at: datetime | None
    analysis_completed_at: datetime | None
    requested_url: str | None
    final_url: str | None
    canonical_url: str | None
    http_status_code: int | None
    redirect_chain: list[dict[str, Any]]
    page_title: str | None
    meta_description: str | None
    heading_structure: list[dict[str, Any]]
    robots_directives: dict[str, Any]
    content_type: str | None
    language: str | None
    structured_data_present: bool | None
    internal_link_count: int | None
    external_link_count: int | None
    image_count: int | None
    images_missing_alt: int | None
    form_count: int | None
    basic_accessibility_signals: dict[str, Any]
    basic_seo_signals: dict[str, Any]
    security_observations: dict[str, Any]
    evidence: dict[str, Any]
    elapsed_ms: int | None
    deep_analysis_run_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class PageAnalysisRunList(BaseModel):
    items: list[PageAnalysisRunRead]
    page: int
    page_size: int
    total: int
    total_pages: int


class PageAnalysisActionRecommendation(BaseModel):
    page_id: uuid.UUID
    page_url: str
    page_title: str | None
    issue_title: str
    issue_category: str
    severity: str
    evidence: dict[str, Any]
    responsible_area: str
    responsible_role: str
    action_location: str
    remediation: str
    verification_method: str
    source: str
    confidence: str
    analysis_level: int


class PageLevelScore(BaseModel):
    page_id: uuid.UUID
    page_url: str
    page_title: str | None
    analysis_level: int
    analysis_status: str
    score: int | None
    confidence: str
    score_available: bool


class SiteCoverageDetail(BaseModel):
    website_id: uuid.UUID
    discovery_run_id: uuid.UUID | None
    discovered_page_count: int
    eligible_page_count: int
    selected_page_count: int
    level_1_attempted: int
    level_1_successful: int
    level_1_failed: int
    level_1_partial: int
    level_2_attempted: int
    level_2_successful: int
    level_2_failed: int
    level_2_partial: int
    skipped_page_count: int
    unanalyzed_eligible_count: int
    coverage_percent: float | None
    clean_pass_percent: float | None
    partial_result_status: bool
    coverage_limitations: list[str]
    calculated_at: datetime


class PageAnalysisSummary(BaseModel):
    website_id: uuid.UUID
    total_pages: int
    eligible_pages: int
    level_1_completed: int
    level_1_partial: int
    level_1_failed: int
    level_1_skipped: int
    level_1_pending: int
    level_2_completed: int
    level_2_partial: int
    level_2_failed: int
    level_2_skipped: int
    level_2_pending: int
    pages_with_findings: int
    pages_without_findings: int
    coverage_percent: float | None
