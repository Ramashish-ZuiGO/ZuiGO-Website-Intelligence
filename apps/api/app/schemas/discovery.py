import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.discovery_run import DiscoveryStatus


class DiscoveryRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    website_id: uuid.UUID
    status: DiscoveryStatus
    current_stage: str | None
    progress_percent: int
    configuration: dict[str, Any]
    robots_details: dict[str, Any]
    sitemap_details: list[dict[str, Any]]
    urls_discovered: int
    urls_unique: int
    urls_eligible: int
    urls_excluded: int
    urls_skipped: int
    sitemap_count: int
    crawl_limit_reached: bool
    maximum_depth_reached: int
    started_at: datetime | None
    completed_at: datetime | None
    failure_code: str | None
    failure_message: str | None
    created_at: datetime
    updated_at: datetime


class WebsitePageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    website_id: uuid.UUID
    normalized_url: str
    original_url: str
    final_url: str | None
    canonical_url: str | None
    page_title: str | None
    page_type: str
    page_type_confidence: int
    page_type_indicators: list[dict[str, Any]]
    classification_version: str
    discovery_source: str
    discovery_evidence: list[dict[str, Any]]
    source_page_url: str | None
    crawl_depth: int
    origin_relation: str
    robots_status: str
    eligibility_status: str
    exclusion_reason: str | None
    skip_reason: str | None
    latest_analysis_run_id: uuid.UUID | None
    latest_analysis_status: str
    first_discovered_at: datetime
    last_discovered_at: datetime


class WebsitePageList(BaseModel):
    items: list[WebsitePageRead]
    page: int
    page_size: int
    total: int
    total_pages: int


class CoverageSummary(BaseModel):
    website_id: uuid.UUID
    discovery_run_id: uuid.UUID | None
    discovered_urls: int
    unique_pages: int
    eligible_pages: int
    excluded_pages: int
    skipped_pages: int
    robots_disallowed_pages: int
    analyzed_pages: int
    completed_analyses: int
    partial_analyses: int
    failed_analyses: int
    pending_analyses: int
    pages_requiring_action: int
    pages_without_findings: int
    analyzed_coverage_numerator: int
    analyzed_coverage_denominator: int
    analyzed_coverage_percent: float | None
    crawl_limit_reached: bool
    maximum_depth_reached: int
    calculated_at: datetime
