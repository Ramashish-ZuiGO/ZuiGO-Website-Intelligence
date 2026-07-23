import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
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
    from app.models.page_analysis_run import PageAnalysisRun
    from app.models.website import Website


class WebsitePage(Base):
    __tablename__ = "website_pages"
    __table_args__ = (
        UniqueConstraint("website_id", "normalized_url", name="uq_website_pages_normalized_url"),
        Index("ix_website_pages_website_eligibility", "website_id", "eligibility_status"),
        Index("ix_website_pages_website_type", "website_id", "page_type"),
        Index("ix_website_pages_website_robots", "website_id", "robots_status"),
        Index("ix_website_pages_latest_analysis_run_id", "latest_analysis_run_id"),
        Index("ix_website_pages_last_discovery_run_id", "last_discovery_run_id"),
        Index("ix_website_pages_l1_status", "website_id", "page_analysis_level_1_status"),
        Index("ix_website_pages_l2_status", "website_id", "page_analysis_level_2_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    website_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("websites.id", ondelete="CASCADE"), nullable=False
    )
    normalized_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    original_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    final_url: Mapped[str | None] = mapped_column(String(2048))
    canonical_url: Mapped[str | None] = mapped_column(String(2048))
    page_title: Mapped[str | None] = mapped_column(Text)
    page_type: Mapped[str] = mapped_column(String(50), default="unknown", nullable=False)
    page_type_confidence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    page_type_indicators: Mapped[list[dict[str, Any]]] = mapped_column(
        json_type, default=list, nullable=False
    )
    classification_version: Mapped[str] = mapped_column(String(50), default="1.0.0", nullable=False)
    discovery_source: Mapped[str] = mapped_column(String(50), nullable=False)
    discovery_evidence: Mapped[list[dict[str, Any]]] = mapped_column(
        json_type, default=list, nullable=False
    )
    source_page_url: Mapped[str | None] = mapped_column(String(2048))
    crawl_depth: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    origin_relation: Mapped[str] = mapped_column(String(30), nullable=False)
    robots_status: Mapped[str] = mapped_column(String(30), default="unknown", nullable=False)
    eligibility_status: Mapped[str] = mapped_column(String(30), nullable=False)
    exclusion_reason: Mapped[str | None] = mapped_column(String(200))
    skip_reason: Mapped[str | None] = mapped_column(String(200))
    last_discovery_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("discovery_runs.id", ondelete="SET NULL")
    )
    latest_analysis_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="SET NULL")
    )
    latest_analysis_status: Mapped[str] = mapped_column(
        String(30), default="pending", nullable=False
    )
    page_analysis_level_1_status: Mapped[str] = mapped_column(
        String(30), default="pending", nullable=False
    )
    page_analysis_level_2_status: Mapped[str] = mapped_column(
        String(30), default="pending", nullable=False
    )
    page_analysis_level_1_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("page_analysis_runs.id", ondelete="SET NULL", use_alter=True)
    )
    page_analysis_level_2_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("page_analysis_runs.id", ondelete="SET NULL", use_alter=True)
    )
    page_analysis_level_1_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    page_analysis_level_2_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    website: Mapped["Website"] = relationship(back_populates="pages")
    page_analysis_runs: Mapped[list["PageAnalysisRun"]] = relationship(
        back_populates="website_page",
        cascade="all, delete-orphan",
        passive_deletes=True,
        foreign_keys="PageAnalysisRun.website_page_id",
    )
