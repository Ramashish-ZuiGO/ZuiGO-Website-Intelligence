import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
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
    Column("url", String(2048), nullable=False),
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

engine = create_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def parse_analysis_run_id(value: str) -> uuid.UUID:
    return uuid.UUID(value)


def utc_now() -> datetime:
    from datetime import UTC

    return datetime.now(UTC)
