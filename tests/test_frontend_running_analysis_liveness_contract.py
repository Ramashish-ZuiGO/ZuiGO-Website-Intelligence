"""Running Analysis liveness/stall-recovery frontend contract.

Source-level contract tests for the generic Running Analysis experience:
backend truth (`stale`, `last_progress_update`, live counters) drives the UI,
progress interpolation stays truthful, and internal engines are never promoted
to branded browsers.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "apps" / "web" / "src"

TIMELINE = ROOT / "components/reports/AnalysisProgressTimeline.tsx"
PANEL = ROOT / "components/reports/ReportDeliveryPanel.tsx"


def _timeline() -> str:
    return TIMELINE.read_text(encoding="utf-8")


def _panel() -> str:
    return PANEL.read_text(encoding="utf-8")


def test_stalled_state_is_backend_authoritative() -> None:
    timeline = _timeline()
    # Backend `stale` drives the stalled experience; the frontend never invents
    # its own stall timeout and never infers stall from a static percentage.
    assert "progress.stale" in timeline
    assert "Analysis appears stalled" in timeline
    assert "No analysis activity has been recorded recently" in timeline
    assert "business_error_message" in timeline
    # No frontend-invented staleness threshold constant.
    assert "STALE_AFTER" not in timeline
    assert "staleThreshold" not in timeline


def test_live_activity_uses_backend_heartbeat_not_polling() -> None:
    timeline = _timeline()
    assert "last_progress_update" in timeline
    assert "Last activity" in timeline
    # API reachability is not activity: the age derives from the backend
    # timestamp, not from successful fetches.
    assert "Date.parse(progress.last_progress_update)" in timeline


def test_interpolation_never_exceeds_backend_target() -> None:
    timeline = _timeline()
    assert "Math.min(backendTarget" in timeline
    assert "Math.min(interpolatedProgress, backendTarget)" in timeline
    # Reduced motion jumps straight to the authoritative value.
    assert "prefers-reduced-motion" in timeline


def test_live_counters_use_canonical_backend_values() -> None:
    timeline = _timeline()
    assert "tested_pages" in timeline
    assert "eligible_pages" in timeline
    assert "successfully_analysed_pages" in timeline
    # Unavailable engines are excluded from the aggregate denominator.
    assert 'availability_status !== "unavailable"' in timeline


def test_run_state_mapping_covers_required_states() -> None:
    timeline = _timeline()
    for state in ('"running"', '"waiting"', '"recovering"', '"stalled"', '"failed"', '"completed"'):
        assert state in timeline
    # Stale is checked before terminal status because a stale run is
    # reconciled to failed while remaining resumable.
    assert timeline.index("if (progress.stale)") < timeline.index('status === "completed"')


def test_activity_shimmer_only_renders_while_running() -> None:
    timeline = _timeline()
    assert 'runState === "running" && (' in timeline
    # Shimmer respects reduced motion.
    assert "motion-safe:animate-" in timeline


def test_agents_and_engines_are_secondary_technical_disclosure() -> None:
    timeline = _timeline()
    assert "Technical execution details" in timeline
    assert "<details" in timeline
    assert "Eight-Agent Execution Pipeline" in timeline
    # Exactly the 8 canonical agents remain represented.
    for agent in (
        "discovery_agent",
        "performance_agent",
        "accessibility_agent",
        "site_diagnostics_agent",
        "repository_intelligence_agent",
        "evidence_validation_agent",
        "remediation_agent",
        "report_agent",
    ):
        assert agent in timeline


def test_internal_engines_never_promoted_to_branded_browsers() -> None:
    timeline = _timeline()
    assert "not branded browser" in timeline
    assert "Chromium is not Chrome or Edge, and WebKit is not Safari" in timeline
    # Engine labels stay engine-branded; no branded-browser labels in the
    # running experience. Labels live in the shared lib/browser-engines.ts
    # (FE-6 dedup) rather than a local copy in this file.
    engine_labels = (ROOT / "lib/browser-engines.ts").read_text(encoding="utf-8")
    assert '"Chromium Engine"' in engine_labels
    assert "Google Chrome" not in timeline
    assert "Apple Safari" not in timeline
    assert "Microsoft Edge" not in timeline
    assert "Google Chrome" not in engine_labels
    assert "Apple Safari" not in engine_labels
    assert "Microsoft Edge" not in engine_labels


def test_recovery_actions_preserve_work_and_prevent_double_submit() -> None:
    timeline = _timeline()
    panel = _panel()
    assert "resume_available" in timeline
    assert "retry_available" in timeline
    assert "pages already analysed are preserved" in timeline
    assert "Resuming…" in timeline
    # Double-submission guard on workflow actions.
    assert "if (!resolvedExecutionId || acting) return;" in panel
    assert "Completed analysis work is preserved." in panel


def test_polling_stops_at_final_success_and_slows_when_terminal() -> None:
    panel = _panel()
    assert "latest.progress_percentage === 100" in panel
    assert "terminalButRecoverable" in panel
    assert "pollEpoch" in panel


def test_status_announcements_are_meaningful_not_per_percent() -> None:
    timeline = _timeline()
    # A single scoped live region announces state-level changes; the wrapper is
    # not aria-live so interpolated percentages never flood screen readers.
    assert '<p className="sr-only" role="status" aria-live="polite">' in timeline
    assert '<div className="flex flex-col gap-6" aria-live="polite">' not in timeline
    assert 'role="progressbar"' in timeline


def test_elapsed_time_is_paired_with_last_activity() -> None:
    timeline = _timeline()
    assert "formatDuration(progress.elapsed_seconds)" in timeline
    elapsed_index = timeline.index(">Elapsed<")
    activity_index = timeline.index(">Last activity<")
    assert abs(activity_index - elapsed_index) < 600
