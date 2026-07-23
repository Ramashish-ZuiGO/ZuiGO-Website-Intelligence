import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
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
    from app.models.website import Website
    from app.models.website_page import WebsitePage


class ActionStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    IGNORED = "ignored"
    REOPENED = "reopened"


class ActionResponsibleArea(StrEnum):
    FRONTEND = "frontend"
    BACKEND = "backend"
    CMS_CONTENT = "CMS/content"
    DESIGN = "design"
    ACCESSIBILITY = "accessibility"
    SEO = "SEO"
    ANALYTICS = "analytics"
    CDN_SERVER = "CDN/server"
    SECURITY = "security"
    LEGAL_COMPLIANCE = "legal/compliance"
    DEVOPS_INFRASTRUCTURE = "DevOps/infrastructure"


ACTION_STATUS_TRANSITIONS: dict[str, set[str]] = {
    ActionStatus.OPEN: {ActionStatus.ACKNOWLEDGED, ActionStatus.IN_PROGRESS, ActionStatus.IGNORED},
    ActionStatus.ACKNOWLEDGED: {ActionStatus.IN_PROGRESS, ActionStatus.IGNORED},
    ActionStatus.IN_PROGRESS: {ActionStatus.RESOLVED, ActionStatus.IGNORED},
    ActionStatus.RESOLVED: {ActionStatus.REOPENED},
    ActionStatus.IGNORED: {ActionStatus.REOPENED},
    ActionStatus.REOPENED: {
        ActionStatus.IN_PROGRESS,
        ActionStatus.ACKNOWLEDGED,
        ActionStatus.IGNORED,
    },
}


def validate_action_transition(current: str, next_status: str) -> None:
    allowed = ACTION_STATUS_TRANSITIONS.get(current, set())
    if next_status not in allowed:
        raise ValueError(
            f"Invalid status transition: {current} -> {next_status}. "
            f"Allowed transitions from '{current}': {', '.join(sorted(allowed)) or 'none'}"
        )


class ActionGenerationExecution(Base):
    __tablename__ = "action_generation_executions"
    __table_args__ = (
        Index("ix_action_gen_exec_website_id", "website_id"),
        Index("ix_action_gen_exec_page_analysis_exec_id", "page_analysis_execution_id"),
        Index("ix_action_gen_exec_status", "status"),
        Index("ix_action_gen_exec_created", "website_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    website_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("websites.id", ondelete="CASCADE"), nullable=False
    )
    discovery_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("discovery_runs.id", ondelete="SET NULL")
    )
    page_analysis_execution_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)
    total_findings_processed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_actions_generated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unsupported_finding_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    insufficient_evidence_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duplicate_within_execution_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    historical_equivalent_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    website: Mapped["Website"] = relationship()
    action_groups: Mapped[list["ActionGroup"]] = relationship(
        back_populates="generation_execution",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    actions: Mapped[list["ActionItem"]] = relationship(
        back_populates="generation_execution",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ActionGroup(Base):
    __tablename__ = "action_groups"
    __table_args__ = (
        UniqueConstraint(
            "generation_execution_id",
            "grouping_key",
            name="uq_action_groups_execution_key",
        ),
        Index("ix_action_groups_generation_exec_id", "generation_execution_id"),
        Index("ix_action_groups_website_id", "website_id"),
        Index("ix_action_groups_status", "status"),
        Index("ix_action_groups_severity", "severity"),
        Index("ix_action_groups_category", "category"),
        Index("ix_action_groups_responsible_area", "responsible_area"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    generation_execution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("action_generation_executions.id", ondelete="CASCADE"), nullable=False
    )
    website_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("websites.id", ondelete="CASCADE"), nullable=False
    )
    grouping_key: Mapped[str] = mapped_column(String(200), nullable=False)
    issue_title: Mapped[str] = mapped_column(String(300), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[str] = mapped_column(String(30), nullable=False)
    priority_score: Mapped[int] = mapped_column(Integer, nullable=False)
    priority_formula_version: Mapped[str] = mapped_column(String(50), nullable=False)
    confidence: Mapped[str] = mapped_column(String(30), nullable=False)
    estimated_effort: Mapped[str] = mapped_column(String(30), nullable=False)
    business_impact: Mapped[str] = mapped_column(Text, nullable=False)
    responsible_area: Mapped[str] = mapped_column(String(100), nullable=False)
    responsible_role: Mapped[str] = mapped_column(String(100), nullable=False)
    action_location: Mapped[str] = mapped_column(String(300), nullable=False)
    why_this_matters: Mapped[str] = mapped_column(Text, nullable=False)
    exact_correction: Mapped[str] = mapped_column(Text, nullable=False)
    implementation_steps: Mapped[str] = mapped_column(Text, nullable=False)
    verification_steps: Mapped[str] = mapped_column(Text, nullable=False)
    expected_result: Mapped[str] = mapped_column(Text, nullable=False)
    limitations: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_summary: Mapped[dict[str, Any]] = mapped_column(
        json_type, default=dict, nullable=False
    )
    source_audit: Mapped[str] = mapped_column(String(100), nullable=False)
    priority_components: Mapped[dict[str, Any]] = mapped_column(
        json_type, default=dict, nullable=False
    )
    affected_page_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="open", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    generation_execution: Mapped["ActionGenerationExecution"] = relationship(
        back_populates="action_groups"
    )
    actions: Mapped[list["ActionItem"]] = relationship(
        back_populates="action_group",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ActionItem(Base):
    __tablename__ = "action_items"
    __table_args__ = (
        CheckConstraint(
            "confidence_percent >= 0 AND confidence_percent <= 100",
            name="ck_action_items_confidence_percent_range",
        ),
        CheckConstraint(
            "priority_score >= 0 AND priority_score <= 100",
            name="ck_action_items_priority_score_range",
        ),
        UniqueConstraint(
            "generation_execution_id",
            "source_finding_identity",
            "website_page_id",
            name="uq_action_items_execution_finding_page",
        ),
        Index("ix_action_items_generation_exec_id", "generation_execution_id"),
        Index("ix_action_items_website_id", "website_id"),
        Index("ix_action_items_website_page_id", "website_page_id"),
        Index("ix_action_items_status", "status"),
        Index("ix_action_items_severity", "severity"),
        Index("ix_action_items_priority", "priority_score"),
        Index("ix_action_items_group_id", "action_group_id"),
        Index("ix_action_items_category", "issue_category"),
        Index("ix_action_items_responsible_area", "responsible_area"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    generation_execution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("action_generation_executions.id", ondelete="CASCADE"), nullable=False
    )
    action_group_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("action_groups.id", ondelete="SET NULL")
    )
    website_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("websites.id", ondelete="CASCADE"), nullable=False
    )
    page_analysis_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("page_analysis_runs.id", ondelete="SET NULL")
    )
    website_page_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("website_pages.id", ondelete="CASCADE"), nullable=False
    )
    source_finding_identity: Mapped[str] = mapped_column(String(200), nullable=False)
    source_page_analysis_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("page_analysis_runs.id", ondelete="SET NULL")
    )
    requested_url: Mapped[str | None] = mapped_column(String(2048))
    final_url: Mapped[str | None] = mapped_column(String(2048))
    page_title: Mapped[str | None] = mapped_column(Text)
    issue_title: Mapped[str] = mapped_column(String(300), nullable=False)
    issue_category: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[str] = mapped_column(String(30), nullable=False)
    priority_score: Mapped[int] = mapped_column(Integer, nullable=False)
    priority_formula_version: Mapped[str] = mapped_column(String(50), nullable=False)
    priority_components: Mapped[dict[str, Any]] = mapped_column(
        json_type, default=dict, nullable=False
    )
    confidence: Mapped[str] = mapped_column(String(30), nullable=False)
    confidence_percent: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    estimated_effort: Mapped[str] = mapped_column(String(30), nullable=False)
    business_impact: Mapped[str] = mapped_column(Text, nullable=False)
    responsible_area: Mapped[str] = mapped_column(String(100), nullable=False)
    responsible_role: Mapped[str] = mapped_column(String(100), nullable=False)
    action_location: Mapped[str] = mapped_column(String(300), nullable=False)
    why_this_matters: Mapped[str] = mapped_column(Text, nullable=False)
    exact_correction: Mapped[str] = mapped_column(Text, nullable=False)
    implementation_steps: Mapped[str] = mapped_column(Text, nullable=False)
    verification_steps: Mapped[str] = mapped_column(Text, nullable=False)
    expected_result: Mapped[str] = mapped_column(Text, nullable=False)
    limitations: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_summary: Mapped[dict[str, Any]] = mapped_column(
        json_type, default=dict, nullable=False
    )
    source_audit: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="open", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    generation_execution: Mapped["ActionGenerationExecution"] = relationship(
        back_populates="actions"
    )
    action_group: Mapped["ActionGroup | None"] = relationship(back_populates="actions")
    website_page: Mapped["WebsitePage"] = relationship()
    status_history: Mapped[list["ActionStatusHistory"]] = relationship(
        back_populates="action_item",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ActionStatusHistory.changed_at.asc()",
    )


class ActionStatusHistory(Base):
    __tablename__ = "action_status_history"
    __table_args__ = (
        Index("ix_action_status_history_action_id", "action_item_id"),
        Index("ix_action_status_history_changed_at", "changed_at"),
        Index("ix_action_status_history_new_status", "new_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    action_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("action_items.id", ondelete="CASCADE"), nullable=False
    )
    previous_status: Mapped[str] = mapped_column(String(30), nullable=False)
    new_status: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    actor: Mapped[str | None] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(30), default="manual", nullable=False)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    action_item: Mapped["ActionItem"] = relationship(back_populates="status_history")
