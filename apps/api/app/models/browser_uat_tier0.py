"""M2 execution tracking + M4 per-combination results for the desktop Tier 0
real-browser lane (Chrome/Edge via GitHub Actions, not an emulated engine).

BrowserUatTier0Execution tracks one dispatch (one workflow_dispatch call).
BrowserUatTier0PageResult/BrowserUatTier0ViewportResult (M4) hold the durable,
queryable per-page and per-viewport results -- one execution legitimately
produces multiple page results, since the workflow runs 3 separate browser/
platform jobs. See docs/DEVICE_OS_BROWSER_QA_PLAN.md M2/M4.
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

json_type = JSON().with_variant(JSONB(), "postgresql")


class BrowserUatTier0Status(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNAVAILABLE = "unavailable"


TERMINAL_BROWSER_UAT_TIER0_STATUSES = frozenset(
    {
        BrowserUatTier0Status.COMPLETED.value,
        BrowserUatTier0Status.PARTIAL.value,
        BrowserUatTier0Status.FAILED.value,
        BrowserUatTier0Status.CANCELLED.value,
        BrowserUatTier0Status.UNAVAILABLE.value,
    }
)


class BrowserUatTier0Lane(StrEnum):
    """Which execution mechanism produced the evidence.

    Only one lane is implemented so far. Adding a lane here is additive and
    does not change BRANDED_BROWSER_SCOPE's row count -- lanes are evidence
    SOURCES, not new browsers.
    """

    GITHUB_ACTIONS_CHROME_EDGE = "github_actions_chrome_edge"


class BrowserUatTier0Execution(Base):
    """One on-demand Tier 0 real-browser verification run for one analysis."""

    __tablename__ = "browser_uat_tier0_executions"
    __table_args__ = (
        UniqueConstraint("execution_id", name="uq_browser_uat_tier0_executions_execution_id"),
        UniqueConstraint(
            "analysis_run_id",
            "lane",
            "idempotency_key",
            name="uq_browser_uat_tier0_executions_run_lane_idempotency",
        ),
        CheckConstraint("attempt >= 1", name="ck_browser_uat_tier0_executions_attempt"),
        Index("ix_browser_uat_tier0_executions_website_created", "website_id", "created_at"),
        Index("ix_browser_uat_tier0_executions_run_created", "analysis_run_id", "created_at"),
        Index("ix_browser_uat_tier0_executions_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    execution_id: Mapped[uuid.UUID] = mapped_column(default=uuid.uuid4, nullable=False)
    website_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("websites.id", ondelete="CASCADE"), nullable=False
    )
    analysis_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    lane: Mapped[str] = mapped_column(String(50), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50),
        default=BrowserUatTier0Status.PENDING.value,
        server_default=BrowserUatTier0Status.PENDING.value,
        nullable=False,
    )
    attempt: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    # Correlation id embedded in the GitHub Actions run-name so a dispatched
    # workflow_dispatch call (which returns no run id) can be matched back to
    # this execution when polling.
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # The GitHub Actions run id, populated once polling finds the matching run.
    provider_run_reference: Mapped[str | None] = mapped_column(String(255))
    # Lightweight execution-level summary/error context only (e.g. why a
    # dispatch went unavailable). The durable, queryable per-page/per-viewport
    # results live in BrowserUatTier0PageResult/BrowserUatTier0ViewportResult
    # (M4) below, not here.
    structured_output: Mapped[dict[str, Any]] = mapped_column(
        json_type, default=dict, nullable=False
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class BrowserUatTier0PageResult(Base):
    """One (execution, browser, platform, page) real-browser check result.

    The GitHub Actions workflow behind the github_actions_chrome_edge lane
    runs 3 separate jobs (chrome/windows, msedge/windows, chrome/macos), each
    uploading its own artifact -- so one execution legitimately produces
    multiple rows here, distinguished by browser_channel + platform.
    """

    __tablename__ = "browser_uat_tier0_page_results"
    __table_args__ = (
        UniqueConstraint(
            "execution_id",
            "browser_channel",
            "platform",
            "url",
            name="uq_browser_uat_tier0_page_results_identity",
        ),
        CheckConstraint(
            "status IN ('pass', 'fail')",
            name="ck_browser_uat_tier0_page_results_status",
        ),
        Index("ix_browser_uat_tier0_page_results_execution", "execution_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    execution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("browser_uat_tier0_executions.id", ondelete="CASCADE"), nullable=False
    )
    browser_channel: Mapped[str] = mapped_column(String(20), nullable=False)
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    browser_version: Mapped[str | None] = mapped_column(String(50))
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer)
    console_error_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    error_message: Mapped[str | None] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class BrowserUatTier0ViewportResult(Base):
    """One (page_result, viewport) real-browser structural-assertion result.

    Field names deliberately match the M3 shared assertion contract's output
    exactly (apps/api/app/services/responsive_assertions.js), including its
    "passed"/"failed" status vocabulary -- distinct from the parent page
    result's "pass"/"fail" -- so nothing is silently remapped between what
    the browser actually returned and what gets stored.
    """

    __tablename__ = "browser_uat_tier0_viewport_results"
    __table_args__ = (
        CheckConstraint(
            "status IN ('passed', 'failed')",
            name="ck_browser_uat_tier0_viewport_results_status",
        ),
        CheckConstraint(
            "viewport_width > 0 AND viewport_height > 0",
            name="ck_browser_uat_tier0_viewport_results_dimensions",
        ),
        Index("ix_browser_uat_tier0_viewport_results_page_result", "page_result_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    page_result_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("browser_uat_tier0_page_results.id", ondelete="CASCADE"), nullable=False
    )
    viewport_name: Mapped[str] = mapped_column(String(50), nullable=False)
    viewport_width: Mapped[int] = mapped_column(Integer, nullable=False)
    viewport_height: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    horizontal_overflow: Mapped[bool | None] = mapped_column()
    critical_elements_outside_viewport: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    overlapping_elements: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    small_tap_targets: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    responsive_navigation: Mapped[bool | None] = mapped_column()
    viewport_problems: Mapped[list[str]] = mapped_column(json_type, default=list, nullable=False)
    tap_target_samples: Mapped[list[dict[str, Any]]] = mapped_column(
        json_type, default=list, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
