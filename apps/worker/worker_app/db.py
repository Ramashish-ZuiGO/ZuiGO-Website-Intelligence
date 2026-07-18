import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, Uuid, create_engine
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

engine = create_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def parse_analysis_run_id(value: str) -> uuid.UUID:
    return uuid.UUID(value)


def utc_now() -> datetime:
    from datetime import UTC

    return datetime.now(UTC)
