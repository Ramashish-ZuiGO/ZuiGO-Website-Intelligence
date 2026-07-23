import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.analysis_run import AnalysisRun
    from app.models.discovery_run import DiscoveryRun
    from app.models.project import Project
    from app.models.website_page import WebsitePage


class Website(Base):
    __tablename__ = "websites"
    __table_args__ = (UniqueConstraint("project_id", "url", name="uq_websites_project_id_url"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    name: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    project: Mapped["Project"] = relationship(back_populates="websites")
    analysis_runs: Mapped[list["AnalysisRun"]] = relationship(
        back_populates="website",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AnalysisRun.created_at.desc()",
    )
    discovery_runs: Mapped[list["DiscoveryRun"]] = relationship(
        back_populates="website", cascade="all, delete-orphan", passive_deletes=True
    )
    pages: Mapped[list["WebsitePage"]] = relationship(
        back_populates="website", cascade="all, delete-orphan", passive_deletes=True
    )
