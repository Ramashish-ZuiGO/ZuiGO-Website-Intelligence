import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

json_type = JSON().with_variant(JSONB(), "postgresql")

if TYPE_CHECKING:
    from app.models.analysis_run import AnalysisRun
    from app.models.website_page import WebsitePage


class PageAnalysisStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"


class PageAnalysisRun(Base):
    __tablename__ = "page_analysis_runs"
    __table_args__ = (
        UniqueConstraint(
            "website_page_id",
            "analysis_level",
            "page_analysis_execution_id",
            name="uq_page_analysis_runs_page_level_exec",
        ),
        Index("ix_page_analysis_runs_website_page_id", "website_page_id"),
        Index("ix_page_analysis_runs_discovery_run_id", "discovery_run_id"),
        Index("ix_page_analysis_runs_execution_id", "page_analysis_execution_id"),
        Index("ix_page_analysis_runs_status", "status"),
        Index("ix_page_analysis_runs_level_status", "analysis_level", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    website_page_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("website_pages.id", ondelete="CASCADE"), nullable=False
    )
    discovery_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("discovery_runs.id", ondelete="CASCADE")
    )
    page_analysis_execution_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    analysis_level: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), default=PageAnalysisStatus.PENDING.value, nullable=False
    )
    failure_reason_code: Mapped[str | None] = mapped_column(String(100))
    failure_reason_text: Mapped[str | None] = mapped_column(String(500))
    analysis_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    analysis_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_url: Mapped[str | None] = mapped_column(String(2048))
    final_url: Mapped[str | None] = mapped_column(String(2048))
    canonical_url: Mapped[str | None] = mapped_column(String(2048))
    http_status_code: Mapped[int | None] = mapped_column(Integer)
    redirect_chain: Mapped[list[dict[str, Any]]] = mapped_column(
        json_type, default=list, nullable=False
    )
    page_title: Mapped[str | None] = mapped_column(Text)
    meta_description: Mapped[str | None] = mapped_column(Text)
    heading_structure: Mapped[list[dict[str, Any]]] = mapped_column(
        json_type, default=list, nullable=False
    )
    robots_directives: Mapped[dict[str, Any]] = mapped_column(
        json_type, default=dict, nullable=False
    )
    content_type: Mapped[str | None] = mapped_column(String(200))
    language: Mapped[str | None] = mapped_column(String(50))
    structured_data_present: Mapped[bool | None] = mapped_column(Boolean)
    internal_link_count: Mapped[int | None] = mapped_column(Integer)
    external_link_count: Mapped[int | None] = mapped_column(Integer)
    image_count: Mapped[int | None] = mapped_column(Integer)
    images_missing_alt: Mapped[int | None] = mapped_column(Integer)
    form_count: Mapped[int | None] = mapped_column(Integer)
    basic_accessibility_signals: Mapped[dict[str, Any]] = mapped_column(
        json_type, default=dict, nullable=False
    )
    basic_seo_signals: Mapped[dict[str, Any]] = mapped_column(
        json_type, default=dict, nullable=False
    )
    security_observations: Mapped[dict[str, Any]] = mapped_column(
        json_type, default=dict, nullable=False
    )
    evidence: Mapped[dict[str, Any]] = mapped_column(json_type, default=dict, nullable=False)
    elapsed_ms: Mapped[int | None] = mapped_column(Integer)
    deep_analysis_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    website_page: Mapped["WebsitePage"] = relationship(
        back_populates="page_analysis_runs", foreign_keys=[website_page_id]
    )
    deep_analysis_run: Mapped["AnalysisRun | None"] = relationship(
        foreign_keys=[deep_analysis_run_id]
    )
