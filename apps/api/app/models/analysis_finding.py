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
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.analysis_run import AnalysisRun

json_type = JSON().with_variant(JSONB(), "postgresql")


class FindingSeverity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFORMATIONAL = "informational"


class FindingSource(StrEnum):
    LIGHTHOUSE = "lighthouse"
    PLAYWRIGHT = "playwright"
    HTTP = "http"


class AnalysisFinding(Base):
    __tablename__ = "analysis_findings"
    __table_args__ = (
        CheckConstraint(
            "confidence_percent >= 0 AND confidence_percent <= 100",
            name="ck_analysis_findings_confidence_percent_range",
        ),
        UniqueConstraint("analysis_run_id", "finding_code", name="uq_analysis_findings_run_code"),
        Index("ix_analysis_findings_analysis_run_id", "analysis_run_id"),
        Index("ix_analysis_findings_severity", "severity"),
        Index("ix_analysis_findings_finding_code", "finding_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    analysis_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    finding_code: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[FindingSeverity] = mapped_column(
        Enum(
            FindingSeverity,
            name="finding_severity",
            native_enum=False,
            create_constraint=True,
            values_callable=lambda enum_type: [item.value for item in enum_type],
        ),
        nullable=False,
    )
    affected_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(json_type, nullable=False)
    source: Mapped[FindingSource] = mapped_column(
        Enum(
            FindingSource,
            name="finding_source",
            native_enum=False,
            create_constraint=True,
            values_callable=lambda enum_type: [item.value for item in enum_type],
        ),
        nullable=False,
    )
    confidence_percent: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    analysis_run: Mapped["AnalysisRun"] = relationship(back_populates="findings")
