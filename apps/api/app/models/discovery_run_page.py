import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DiscoveryRunPage(Base):
    """Run-scoped membership between a discovery run and the pages it found.

    The ``website_pages`` row is a shared per-(website, url) catalog entry whose
    ``last_discovery_run_id`` is a last-writer-wins pointer. When two analyses of
    the same website run concurrently they overwrite that pointer, so a run must
    not use it to identify *its own* pages. This table records each run's
    discovered page set and the eligibility that run computed, independently of
    any other concurrent run.
    """

    __tablename__ = "discovery_run_pages"
    __table_args__ = (
        UniqueConstraint(
            "discovery_run_id", "website_page_id", name="uq_discovery_run_pages_run_page"
        ),
        Index("ix_discovery_run_pages_run_eligibility", "discovery_run_id", "eligibility_status"),
        Index("ix_discovery_run_pages_page", "website_page_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    discovery_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("discovery_runs.id", ondelete="CASCADE"), nullable=False
    )
    website_page_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("website_pages.id", ondelete="CASCADE"), nullable=False
    )
    eligibility_status: Mapped[str] = mapped_column(String(30), nullable=False)
    crawl_depth: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
