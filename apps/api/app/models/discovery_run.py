import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

json_type = JSON().with_variant(JSONB(), "postgresql")

if TYPE_CHECKING:
    from app.models.website import Website


class DiscoveryStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PARTIAL = "partial"
    COMPLETED = "completed"
    FAILED = "failed"


class DiscoveryRun(Base):
    __tablename__ = "discovery_runs"
    __table_args__ = (
        CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100",
            name="ck_discovery_runs_progress_percent_range",
        ),
        Index("ix_discovery_runs_website_created", "website_id", "created_at"),
        Index("ix_discovery_runs_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    website_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("websites.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[DiscoveryStatus] = mapped_column(
        Enum(
            DiscoveryStatus,
            name="discovery_run_status",
            native_enum=False,
            create_constraint=True,
            values_callable=lambda enum_type: [item.value for item in enum_type],
        ),
        default=DiscoveryStatus.QUEUED,
        nullable=False,
    )
    current_stage: Mapped[str | None] = mapped_column(String(100))
    progress_percent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    celery_task_id: Mapped[str | None] = mapped_column(String(255))
    configuration: Mapped[dict[str, Any]] = mapped_column(json_type, default=dict, nullable=False)
    robots_details: Mapped[dict[str, Any]] = mapped_column(json_type, default=dict, nullable=False)
    sitemap_details: Mapped[list[dict[str, Any]]] = mapped_column(
        json_type, default=list, nullable=False
    )
    urls_discovered: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    urls_unique: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    urls_eligible: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    urls_excluded: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    urls_skipped: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sitemap_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    crawl_limit_reached: Mapped[bool] = mapped_column(default=False, nullable=False)
    maximum_depth_reached: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(100))
    failure_message: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    website: Mapped["Website"] = relationship(back_populates="discovery_runs")
