import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
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
    from app.models.website import Website
    from app.models.website_page import WebsitePage


class SiteDiagnosticExecutionStatusEnum(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNAVAILABLE = "unavailable"


class DiagnosticScopeEnum(StrEnum):
    PAGE = "page"
    SECTION = "section"
    TEMPLATE = "template"
    SITE = "site"


class SiteDiagnosticExecution(Base):
    __tablename__ = "site_diagnostic_executions"
    __table_args__ = (
        UniqueConstraint("execution_id", name="uq_site_diagnostic_executions_execution_id"),
        UniqueConstraint(
            "analysis_run_id",
            "idempotency_key",
            name="uq_site_diagnostic_executions_run_idempotency",
        ),
        CheckConstraint(
            "total_page_count >= 0",
            name="ck_site_diagnostic_executions_total_page_count",
        ),
        CheckConstraint(
            "processed_page_count >= 0 AND processed_page_count <= total_page_count",
            name="ck_site_diagnostic_executions_processed_page_count",
        ),
        CheckConstraint(
            "failed_page_count >= 0 AND failed_page_count <= processed_page_count",
            name="ck_site_diagnostic_executions_failed_page_count",
        ),
        CheckConstraint(
            "evidence_coverage_numerator >= 0 "
            "AND evidence_coverage_numerator <= evidence_coverage_denominator",
            name="ck_site_diagnostic_executions_coverage_counts",
        ),
        CheckConstraint(
            "evidence_coverage_denominator >= 0",
            name="ck_site_diagnostic_executions_coverage_denominator",
        ),
        CheckConstraint(
            "evidence_coverage_ratio >= 0 AND evidence_coverage_ratio <= 1",
            name="ck_site_diagnostic_executions_coverage_ratio",
        ),
        Index(
            "ix_site_diagnostic_executions_website_created",
            "website_id",
            "created_at",
        ),
        Index(
            "ix_site_diagnostic_executions_run_created",
            "analysis_run_id",
            "created_at",
        ),
        Index("ix_site_diagnostic_executions_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    execution_id: Mapped[uuid.UUID] = mapped_column(default=uuid.uuid4, nullable=False)
    website_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("websites.id", ondelete="CASCADE"), nullable=False
    )
    analysis_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    workflow_id: Mapped[str] = mapped_column(String(100), nullable=False)
    workflow_version: Mapped[str] = mapped_column(String(50), nullable=False)
    selected_profile_id: Mapped[str] = mapped_column(String(100), nullable=False)
    selected_profile_version: Mapped[str] = mapped_column(String(50), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    diagnostic_engine_version: Mapped[str] = mapped_column(String(50), nullable=False)
    rule_registry_version: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50),
        default=SiteDiagnosticExecutionStatusEnum.PENDING.value,
        server_default=SiteDiagnosticExecutionStatusEnum.PENDING.value,
        nullable=False,
    )
    total_page_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    processed_page_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    failed_page_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    evidence_coverage_numerator: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    evidence_coverage_denominator: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    evidence_coverage_ratio: Mapped[float] = mapped_column(
        Float, default=0.0, server_default="0", nullable=False
    )
    error_metadata: Mapped[dict[str, Any]] = mapped_column(json_type, default=dict, nullable=False)
    partial_completion_metadata: Mapped[dict[str, Any]] = mapped_column(
        json_type, default=dict, nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    website: Mapped["Website"] = relationship()
    analysis_run: Mapped["AnalysisRun"] = relationship()
    findings: Mapped[list["SiteDiagnosticFinding"]] = relationship(
        back_populates="execution",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="SiteDiagnosticFinding.created_at",
    )


class SiteDiagnosticFinding(Base):
    __tablename__ = "site_diagnostic_findings"
    __table_args__ = (
        CheckConstraint(
            "affected_page_count >= 0 AND affected_page_count <= total_eligible_page_count",
            name="ck_site_diagnostic_findings_affected_page_count",
        ),
        CheckConstraint(
            "total_eligible_page_count >= 0",
            name="ck_site_diagnostic_findings_eligible_page_count",
        ),
        CheckConstraint(
            "occurrence_count >= affected_page_count",
            name="ck_site_diagnostic_findings_occurrence_count",
        ),
        CheckConstraint(
            "affected_ratio >= 0 AND affected_ratio <= 1",
            name="ck_site_diagnostic_findings_affected_ratio",
        ),
        CheckConstraint(
            "severity IN ('critical', 'high', 'medium', 'low', 'info')",
            name="ck_site_diagnostic_findings_severity",
        ),
        CheckConstraint(
            "confidence IN ('high', 'medium', 'low', 'unavailable')",
            name="ck_site_diagnostic_findings_confidence",
        ),
        CheckConstraint(
            "scope IN ('page', 'section', 'template', 'site')",
            name="ck_site_diagnostic_findings_scope",
        ),
        Index(
            "ix_site_diagnostic_findings_execution_rule",
            "execution_id",
            "rule_id",
        ),
        Index(
            "ix_site_diagnostic_findings_execution_category",
            "execution_id",
            "category",
        ),
        Index(
            "ix_site_diagnostic_findings_execution_severity",
            "execution_id",
            "severity",
        ),
        Index(
            "ix_site_diagnostic_findings_execution_scope",
            "execution_id",
            "scope",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    execution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("site_diagnostic_executions.id", ondelete="CASCADE"),
        nullable=False,
    )
    rule_id: Mapped[str] = mapped_column(String(255), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(50), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[str] = mapped_column(String(50), nullable=False)
    confidence: Mapped[str] = mapped_column(String(50), nullable=False)
    scope: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    why_it_matters: Mapped[str] = mapped_column(Text, nullable=False)
    affected_page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_eligible_page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    affected_ratio: Mapped[float] = mapped_column(Float, nullable=False)
    evidence_summary: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_references: Mapped[list[dict[str, Any]]] = mapped_column(
        json_type, default=list, nullable=False
    )
    remediation_guidance: Mapped[str] = mapped_column(Text, nullable=False)
    responsible_role: Mapped[str] = mapped_column(String(255), nullable=False)
    verification_guidance: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    execution: Mapped["SiteDiagnosticExecution"] = relationship(back_populates="findings")
    occurrences: Mapped[list["SiteDiagnosticOccurrence"]] = relationship(
        back_populates="finding",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="SiteDiagnosticOccurrence.created_at",
    )


class SiteDiagnosticOccurrence(Base):
    __tablename__ = "site_diagnostic_occurrences"
    __table_args__ = (
        UniqueConstraint(
            "finding_id",
            "occurrence_fingerprint",
            name="uq_site_diagnostic_occurrences_fingerprint",
        ),
        CheckConstraint(
            "website_page_id IS NOT NULL OR normalized_url IS NOT NULL",
            name="ck_site_diagnostic_occurrences_page_reference",
        ),
        Index("ix_site_diagnostic_occurrences_finding_id", "finding_id"),
        Index("ix_site_diagnostic_occurrences_website_page_id", "website_page_id"),
        Index("ix_site_diagnostic_occurrences_evidence_reference", "evidence_reference"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    finding_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("site_diagnostic_findings.id", ondelete="CASCADE"),
        nullable=False,
    )
    website_page_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("website_pages.id", ondelete="SET NULL")
    )
    normalized_url: Mapped[str | None] = mapped_column(String(2048))
    evidence_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    occurrence_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    element_selector: Mapped[str | None] = mapped_column(Text)
    resource_url: Mapped[str | None] = mapped_column(String(2048))
    location: Mapped[str | None] = mapped_column(Text)
    context: Mapped[dict[str, Any]] = mapped_column(json_type, default=dict, nullable=False)
    observed_value: Mapped[str | None] = mapped_column(Text)
    expected_value: Mapped[str | None] = mapped_column(Text)
    supporting_evidence: Mapped[dict[str, Any]] = mapped_column(
        json_type, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    finding: Mapped["SiteDiagnosticFinding"] = relationship(back_populates="occurrences")
    website_page: Mapped["WebsitePage | None"] = relationship()
