import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    Uuid,
    create_engine,
)
from sqlalchemy.orm import sessionmaker

from worker_app.config import get_settings

metadata = MetaData()
analysis_runs = Table(
    "analysis_runs",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("website_id", Uuid, nullable=False),
    Column("status", String(20), nullable=False),
    Column("progress_percent", Integer, nullable=False),
    Column("current_step", String(200)),
    Column("celery_task_id", String(255)),
    Column("started_at", DateTime(timezone=True)),
    Column("completed_at", DateTime(timezone=True)),
    Column("error_code", String(100)),
    Column("error_message", String(500)),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
websites = Table(
    "websites",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("project_id", Uuid),
    Column("url", String(2048), nullable=False),
    Column("name", String(200)),
)
discovery_runs = Table(
    "discovery_runs",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("website_id", Uuid, nullable=False),
    Column("status", String(20), nullable=False),
    Column("current_stage", String(100)),
    Column("progress_percent", Integer, nullable=False),
    Column("celery_task_id", String(255)),
    Column("configuration", JSON, nullable=False),
    Column("robots_details", JSON, nullable=False),
    Column("sitemap_details", JSON, nullable=False),
    Column("urls_discovered", Integer, nullable=False),
    Column("urls_unique", Integer, nullable=False),
    Column("urls_eligible", Integer, nullable=False),
    Column("urls_excluded", Integer, nullable=False),
    Column("urls_skipped", Integer, nullable=False),
    Column("sitemap_count", Integer, nullable=False),
    Column("crawl_limit_reached", Boolean, nullable=False),
    Column("maximum_depth_reached", Integer, nullable=False),
    Column("started_at", DateTime(timezone=True)),
    Column("completed_at", DateTime(timezone=True)),
    Column("failure_code", String(100)),
    Column("failure_message", String(500)),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
website_pages = Table(
    "website_pages",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("website_id", Uuid, nullable=False),
    Column("normalized_url", String(2048), nullable=False),
    Column("original_url", String(2048), nullable=False),
    Column("final_url", String(2048)),
    Column("canonical_url", String(2048)),
    Column("page_title", Text),
    Column("page_type", String(50), nullable=False),
    Column("page_type_confidence", Integer, nullable=False),
    Column("page_type_indicators", JSON, nullable=False),
    Column("classification_version", String(50), nullable=False),
    Column("discovery_source", String(50), nullable=False),
    Column("discovery_evidence", JSON, nullable=False),
    Column("source_page_url", String(2048)),
    Column("crawl_depth", Integer, nullable=False),
    Column("origin_relation", String(30), nullable=False),
    Column("robots_status", String(30), nullable=False),
    Column("eligibility_status", String(30), nullable=False),
    Column("exclusion_reason", String(200)),
    Column("skip_reason", String(200)),
    Column("last_discovery_run_id", Uuid),
    Column("latest_analysis_run_id", Uuid),
    Column("latest_analysis_status", String(30), nullable=False),
    Column("first_discovered_at", DateTime(timezone=True), nullable=False),
    Column("last_discovered_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
analysis_results = Table(
    "analysis_results",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("analysis_run_id", Uuid, nullable=False, unique=True),
    Column("requested_url", String(2048), nullable=False),
    Column("final_url", String(2048), nullable=False),
    Column("http_status_code", Integer),
    Column("page_title", Text),
    Column("meta_description", Text),
    Column("lighthouse_version", String(50)),
    Column("user_agent", Text),
    Column("analysis_started_at", DateTime(timezone=True), nullable=False),
    Column("analysis_completed_at", DateTime(timezone=True), nullable=False),
    Column("raw_lighthouse_data", JSON, nullable=False),
    Column("raw_playwright_data", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
analysis_diagnostics = Table(
    "analysis_diagnostics",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("analysis_run_id", Uuid, nullable=False),
    Column("group_name", String(100), nullable=False),
    Column("payload", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
analysis_findings = Table(
    "analysis_findings",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("analysis_run_id", Uuid, nullable=False),
    Column("finding_code", String(100), nullable=False),
    Column("category", String(100), nullable=False),
    Column("title", String(200), nullable=False),
    Column("description", Text, nullable=False),
    Column("severity", String(20), nullable=False),
    Column("affected_url", String(2048), nullable=False),
    Column("evidence", JSON, nullable=False),
    Column("source", String(20), nullable=False),
    Column("confidence_percent", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
analysis_scores = Table(
    "analysis_scores",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("analysis_run_id", Uuid, nullable=False, unique=True),
    Column("formula_version", String(50), nullable=False),
    Column("overall_score", Integer),
    Column("performance_score", Integer),
    Column("accessibility_score", Integer),
    Column("best_practices_score", Integer),
    Column("seo_score", Integer),
    Column("technical_quality_score", Integer),
    Column("confidence_percent", Integer, nullable=False),
    Column("available_categories", JSON, nullable=False),
    Column("unavailable_categories", JSON, nullable=False),
    Column("weights", JSON, nullable=False),
    Column("deductions", JSON, nullable=False),
    Column("calculation_details", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
analysis_interpretations = Table(
    "analysis_interpretations",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("analysis_run_id", Uuid, nullable=False, unique=True),
    Column("generation_mode", String(30), nullable=False),
    Column("provider", String(50), nullable=False),
    Column("model", String(200), nullable=False),
    Column("prompt_version", String(50), nullable=False),
    Column("executive_summary", Text, nullable=False),
    Column("overall_assessment", Text, nullable=False),
    Column("strengths", JSON, nullable=False),
    Column("weaknesses", JSON, nullable=False),
    Column("priority_recommendations", JSON, nullable=False),
    Column("action_plan", JSON, nullable=False),
    Column("limitations", JSON, nullable=False),
    Column("fallback_reason", String(100)),
    Column("generated_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

engine = create_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def parse_analysis_run_id(value: str) -> uuid.UUID:
    return uuid.UUID(value)


def utc_now() -> datetime:
    from datetime import UTC

    return datetime.now(UTC)
