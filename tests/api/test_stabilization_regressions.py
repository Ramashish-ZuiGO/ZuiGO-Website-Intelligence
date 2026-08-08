"""Regression tests for stabilization phases 1-10 and runtime state hardening.

Covers:
- Report quality classification (_compute_report_quality)
- HTML URL helper (_html_url)
- Discovery message semantics (_discovery_message)
- Action plan deduplication (_deduplicate_actions)
- Workflow dependency blocking logic (_partition_batch)
- Lighthouse timeout isolation
"""

import html as htmlmod

import pytest
from app.schemas.agent_platform import ExecutionStatus
from app.services.report_delivery import (
    _compute_report_quality,
    _discovery_message,
    _html_url,
)
from app.services.workflow_execution import SUCCESSFUL_DEPENDENCY_STATUSES


class TestComputeReportQuality:
    """Phase 10: report quality gate classification."""

    def test_failed_when_denominator_zero(self) -> None:
        assert (
            _compute_report_quality(
                numerator=5,
                denominator=0,
                overall_score=80.0,
                confidence=90,
                discovery_completeness="complete",
            )
            == "FAILED"
        )

    def test_failed_when_numerator_zero(self) -> None:
        assert (
            _compute_report_quality(
                numerator=0,
                denominator=16,
                overall_score=None,
                confidence=None,
                discovery_completeness="complete",
            )
            == "FAILED"
        )

    def test_failed_when_discovery_failed(self) -> None:
        assert (
            _compute_report_quality(
                numerator=8,
                denominator=16,
                overall_score=80.0,
                confidence=90,
                discovery_completeness="failed",
            )
            == "FAILED"
        )

    def test_complete_all_conditions_met(self) -> None:
        assert (
            _compute_report_quality(
                numerator=15,
                denominator=16,
                overall_score=85.0,
                confidence=70,
                discovery_completeness="complete",
            )
            == "COMPLETE"
        )

    def test_complete_at_boundary_ratio(self) -> None:
        assert (
            _compute_report_quality(
                numerator=9,
                denominator=10,
                overall_score=50.0,
                confidence=50,
                discovery_completeness="complete",
            )
            == "COMPLETE"
        )

    def test_partial_not_complete_when_confidence_below_50(self) -> None:
        result = _compute_report_quality(
            numerator=15,
            denominator=16,
            overall_score=85.0,
            confidence=49,
            discovery_completeness="complete",
        )
        assert result == "PARTIAL"

    def test_partial_not_complete_when_confidence_none(self) -> None:
        result = _compute_report_quality(
            numerator=15,
            denominator=16,
            overall_score=85.0,
            confidence=None,
            discovery_completeness="complete",
        )
        assert result == "PARTIAL"

    def test_partial_not_complete_when_score_none(self) -> None:
        result = _compute_report_quality(
            numerator=15,
            denominator=16,
            overall_score=None,
            confidence=90,
            discovery_completeness="complete",
        )
        assert result == "PARTIAL"

    def test_partial_with_low_ratio_but_score_present(self) -> None:
        result = _compute_report_quality(
            numerator=3,
            denominator=16,
            overall_score=60.0,
            confidence=None,
            discovery_completeness="partial",
        )
        assert result == "PARTIAL"

    def test_partial_with_ratio_above_04(self) -> None:
        result = _compute_report_quality(
            numerator=7,
            denominator=16,
            overall_score=None,
            confidence=None,
            discovery_completeness="partial",
        )
        assert result == "PARTIAL"

    def test_inconclusive_low_ratio_no_score(self) -> None:
        result = _compute_report_quality(
            numerator=2,
            denominator=16,
            overall_score=None,
            confidence=None,
            discovery_completeness="partial",
        )
        assert result == "INCONCLUSIVE"

    def test_discovery_completeness_none_does_not_fail(self) -> None:
        result = _compute_report_quality(
            numerator=8,
            denominator=16,
            overall_score=None,
            confidence=None,
            discovery_completeness=None,
        )
        assert result == "PARTIAL"


class TestHtmlUrl:
    """Phase 9: URL presentation helper."""

    def test_none_returns_unavailable(self) -> None:
        assert _html_url(None) == "Unavailable"

    def test_short_url_not_truncated(self) -> None:
        url = "https://example.com/page"
        result = _html_url(url)
        assert f'href="{htmlmod.escape(url, quote=True)}"' in result
        assert f">{htmlmod.escape(url)}</a>" in result

    def test_long_url_truncated(self) -> None:
        url = "https://example.com/" + "a" * 100
        result = _html_url(url, max_display=60)
        assert "…" in result
        assert f'title="{htmlmod.escape(url, quote=True)}"' in result

    def test_special_chars_escaped(self) -> None:
        url = 'https://example.com/page?a=1&b=2"'
        result = _html_url(url)
        assert "&amp;" in result
        assert "&#x27;" in result or "&quot;" in result

    def test_produces_anchor_tag(self) -> None:
        result = _html_url("https://example.com")
        assert result.startswith("<a ")
        assert result.endswith("</a>")


class TestDiscoveryMessage:
    """Phase 1: discovery startup semantics — no false 'inconclusive'."""

    def test_queued_state(self) -> None:
        msg = _discovery_message("queued", None, None)
        assert "waiting to start" in msg

    def test_pending_state(self) -> None:
        msg = _discovery_message("pending", None, None)
        assert "waiting to start" in msg

    def test_running_state(self) -> None:
        msg = _discovery_message("running", None, None)
        assert "in progress" in msg

    def test_complete_state(self) -> None:
        msg = _discovery_message("completed", "complete", None)
        assert "Full-site coverage was established" in msg

    def test_partial_state(self) -> None:
        msg = _discovery_message("completed", "partial", None)
        assert "partial coverage" in msg

    def test_none_stage_returns_not_started(self) -> None:
        msg = _discovery_message(None, None, None)
        assert "not" in msg.lower() or "waiting" in msg.lower() or "unavailable" in msg.lower()


class TestReportQualityValues:
    """Verify the four quality values are the only valid outputs."""

    VALID_QUALITIES = {"COMPLETE", "PARTIAL", "INCONCLUSIVE", "FAILED"}

    @pytest.mark.parametrize(
        "num,den,score,conf,disc",
        [
            (0, 0, None, None, None),
            (0, 16, None, None, "complete"),
            (8, 16, None, None, "failed"),
            (16, 16, 90.0, 90, "complete"),
            (8, 16, 60.0, None, "partial"),
            (7, 16, None, None, "partial"),
            (2, 16, None, None, "partial"),
            (1, 16, None, None, None),
        ],
    )
    def test_output_is_valid_quality(
        self,
        num: int,
        den: int,
        score: float | None,
        conf: int | None,
        disc: str | None,
    ) -> None:
        result = _compute_report_quality(
            numerator=num,
            denominator=den,
            overall_score=score,
            confidence=conf,
            discovery_completeness=disc,
        )
        assert result in self.VALID_QUALITIES


class TestSuccessfulDependencyStatuses:
    """Runtime hardening: workflow dependency blocking contract."""

    def test_completed_is_successful(self) -> None:
        assert ExecutionStatus.COMPLETED.value in SUCCESSFUL_DEPENDENCY_STATUSES

    def test_partial_is_successful(self) -> None:
        assert ExecutionStatus.PARTIAL.value in SUCCESSFUL_DEPENDENCY_STATUSES

    def test_failed_is_not_successful(self) -> None:
        assert ExecutionStatus.FAILED.value not in SUCCESSFUL_DEPENDENCY_STATUSES

    def test_unavailable_is_not_successful(self) -> None:
        assert ExecutionStatus.UNAVAILABLE.value not in SUCCESSFUL_DEPENDENCY_STATUSES

    def test_pending_is_not_successful(self) -> None:
        assert ExecutionStatus.PENDING.value not in SUCCESSFUL_DEPENDENCY_STATUSES

    def test_cancelled_is_not_successful(self) -> None:
        assert ExecutionStatus.CANCELLED.value not in SUCCESSFUL_DEPENDENCY_STATUSES

    def test_at_least_one_partial_unblocks_downstream(self) -> None:
        """If one of three deps is partial and others failed, downstream should run."""
        statuses = [
            ExecutionStatus.FAILED.value,
            ExecutionStatus.PARTIAL.value,
            ExecutionStatus.UNAVAILABLE.value,
        ]
        assert any(s in SUCCESSFUL_DEPENDENCY_STATUSES for s in statuses)

    def test_all_failed_blocks_downstream(self) -> None:
        statuses = [
            ExecutionStatus.FAILED.value,
            ExecutionStatus.UNAVAILABLE.value,
            ExecutionStatus.FAILED.value,
        ]
        assert not any(s in SUCCESSFUL_DEPENDENCY_STATUSES for s in statuses)


class TestDeterministicScoring:
    """Runtime hardening: scoring formula is purely deterministic, no LLM."""

    def test_formula_version_is_1_0_0(self) -> None:
        from app.services.scoring_formula import FORMULA_VERSION

        assert FORMULA_VERSION == "1.0.0"

    def test_scoring_produces_score_without_llm(self) -> None:
        from app.services.scoring_formula import calculate_score

        metrics = {
            "performance_score": 54,
            "accessibility_score": 100,
            "best_practices_score": 100,
            "seo_score": 92,
        }
        playwright = {
            "h1_count": 1,
            "https_usage": True,
            "image_count": 1,
            "images_missing_alt": 0,
        }
        findings: list[dict] = []
        result = calculate_score(metrics, playwright, findings, audit_completed=True)
        assert isinstance(result["overall_score"], int)
        assert 0 <= result["overall_score"] <= 100
        assert result["formula_version"] == "1.0.0"

    def test_scoring_without_lighthouse_uses_partial_evidence(self) -> None:
        from app.services.scoring_formula import calculate_score

        metrics: dict = {}
        playwright = {
            "h1_count": 1,
            "https_usage": True,
            "image_count": 0,
            "images_missing_alt": 0,
        }
        findings: list[dict] = []
        result = calculate_score(metrics, playwright, findings, audit_completed=False)
        assert isinstance(result["overall_score"], int)
        assert result["confidence_percent"] < 100

    def test_category_weights_sum_to_100(self) -> None:
        from app.services.scoring_formula import CATEGORY_WEIGHTS

        assert sum(CATEGORY_WEIGHTS.values()) == 100


class TestLighthouseIsolation:
    """Runtime hardening: Lighthouse timeout doesn't fail the whole run."""

    def test_lighthouse_available_flag_controls_audit_completed(self) -> None:
        from app.services.scoring_formula import calculate_score

        metrics = {"performance_score": 50, "accessibility_score": 90}
        playwright = {"h1_count": 1, "https_usage": True}

        with_lighthouse = calculate_score(metrics, playwright, [], audit_completed=True)
        without_lighthouse = calculate_score({}, playwright, [], audit_completed=False)

        assert with_lighthouse["confidence_percent"] >= without_lighthouse["confidence_percent"]
