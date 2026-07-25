import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base


class PerformanceSnapshot(Base):
    __tablename__ = "performance_snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    execution_id = Column(UUID(as_uuid=True), nullable=False)
    website_id = Column(
        UUID(as_uuid=True),
        ForeignKey("websites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    analysis_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("analysis_runs.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    url_or_origin = Column(String(2048), nullable=False, index=True)
    evidence_source = Column(String(50), nullable=False)  # crux, lighthouse, playwright
    evidence_type = Column(String(50), nullable=False)  # field, lab, browser_timing
    scope = Column(String(50), nullable=False)  # url, origin
    form_factor = Column(String(50), nullable=False)  # phone, desktop, tablet, all
    metric_id = Column(String(100), nullable=False, index=True)

    raw_value = Column(Float, nullable=True)
    display_value = Column(String(100), nullable=True)
    numeric_unit = Column(String(50), nullable=True)
    percentile = Column(Float, nullable=True)
    histogram_bins = Column(JSON, nullable=True)

    rating = Column(String(50), nullable=True)
    profile_id = Column(String(100), nullable=True)
    profile_version = Column(String(50), nullable=True)

    collection_period_start = Column(DateTime(timezone=True), nullable=True)
    collection_period_end = Column(DateTime(timezone=True), nullable=True)
    observation_timestamp = Column(DateTime(timezone=True), nullable=True)

    provider = Column(String(100), nullable=True)
    provider_metadata = Column(JSON, nullable=True)

    availability_status = Column(String(50), nullable=False)  # available, unavailable, partial
    unavailable_reason = Column(String(500), nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "execution_id",
            "website_id",
            "url_or_origin",
            "evidence_type",
            "metric_id",
            "form_factor",
            name="uq_performance_snapshots_execution_metric",
        ),
    )
