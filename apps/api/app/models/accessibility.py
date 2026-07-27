import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base


class AccessibilityAudit(Base):
    __tablename__ = "accessibility_audits"

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
    page_id = Column(
        UUID(as_uuid=True),
        ForeignKey("website_pages.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    normalized_url = Column(String(2048), nullable=False, index=True)
    provider = Column(String(100), nullable=False)
    provider_version = Column(String(50), nullable=True)
    ruleset_version = Column(String(50), nullable=True)
    profile_id = Column(String(100), nullable=True)
    profile_version = Column(String(50), nullable=True)
    requested_wcag_level = Column(String(50), nullable=True)

    status = Column(String(50), nullable=False)
    failure_reason = Column(Text, nullable=True)

    violation_count = Column(Integer, nullable=True, default=0)
    incomplete_count = Column(Integer, nullable=True, default=0)
    pass_count = Column(Integer, nullable=True, default=0)
    inapplicable_count = Column(Integer, nullable=True, default=0)

    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))

    __table_args__ = (
        UniqueConstraint(
            "execution_id",
            "website_id",
            "normalized_url",
            "provider",
            name="uq_accessibility_audits_execution_provider",
        ),
    )


class AccessibilityFinding(Base):
    __tablename__ = "accessibility_findings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    audit_id = Column(
        UUID(as_uuid=True),
        ForeignKey("accessibility_audits.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    provider_rule_id = Column(String(255), nullable=False, index=True)
    act_rule_id = Column(String(255), nullable=True)
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    help_text = Column(Text, nullable=True)
    help_url = Column(String(2048), nullable=True)

    impact = Column(String(50), nullable=False)
    result_type = Column(String(50), nullable=False)

    wcag_version = Column(String(50), nullable=True)
    wcag_criteria = Column(JSON, nullable=True)
    conformance_level = Column(String(50), nullable=True)

    affected_element_count = Column(Integer, nullable=False, default=0)
    remediation_summary = Column(Text, nullable=True)
    manual_verification_required = Column(Boolean, nullable=False, default=False)

    source_metadata = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))


class AccessibilityNode(Base):
    __tablename__ = "accessibility_nodes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    finding_id = Column(
        UUID(as_uuid=True),
        ForeignKey("accessibility_findings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    normalized_selector = Column(Text, nullable=False)
    html_excerpt = Column(Text, nullable=True)
    failure_summary = Column(Text, nullable=True)

    related_nodes = Column(JSON, nullable=True)
    frame_context = Column(Text, nullable=True)
    shadow_dom_context = Column(Text, nullable=True)

    occurrence_fingerprint = Column(String(255), nullable=False, index=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))


class ManualReviewChecklist(Base):
    __tablename__ = "manual_review_checklists"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    audit_id = Column(
        UUID(as_uuid=True),
        ForeignKey("accessibility_audits.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    checklist_id = Column(String(255), nullable=False)
    title = Column(String(500), nullable=False)
    reason = Column(Text, nullable=True)
    applicable_wcag_criterion = Column(String(255), nullable=True)

    required_evidence = Column(Text, nullable=True)
    suggested_test_procedure = Column(Text, nullable=True)
    status = Column(String(50), nullable=False, default="not_reviewed")

    automated_evidence_references = Column(JSON, nullable=True)
    limitation_statement = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
