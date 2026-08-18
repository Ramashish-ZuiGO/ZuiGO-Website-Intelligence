"use client";

import React, { useMemo } from "react";
import type { WorkflowProgress } from "@/components/reports/types";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { ConceptInfoButton } from "@/components/metrics/ConceptInfoButton";
import { MetricStat } from "@/components/ui/MetricStat";
import { ENGINE_LABELS } from "@/lib/browser-engines";
import { AGENT_LABELS } from "@/lib/agent-labels";
import { AlertCircle, AlertTriangle, RotateCcw, XCircle, LayoutDashboard, Search, Eye, Activity, ShieldCheck, CheckSquare, Zap, FileText, PauseCircle, Loader2 } from "lucide-react";

// Agent to icon mapping for ZuiGO styling
const AGENT_ICONS: Record<string, React.ElementType> = {
  discovery_agent: Search,
  performance_agent: Zap,
  accessibility_agent: Eye,
  site_diagnostics_agent: Activity,
  repository_intelligence_agent: LayoutDashboard,
  evidence_validation_agent: ShieldCheck,
  remediation_agent: CheckSquare,
  report_agent: FileText,
};

// Customer-readable names for the primary running view. Falls back to the
// backend stage label for unknown stages.
const CUSTOMER_STAGE_LABELS: Record<string, string> = {
  setup: "Validating website",
  website_discovery: "Discovering website",
  page_analysis: "Preparing pages",
  primary_page_analysis: "Analysing pages",
  browser_compatibility: "Browser analysis",
  browser_engine_analysis: "Browser analysis",
  evidence_validation: "Evaluating findings",
  diagnostics_scoring: "Evaluating findings",
  remediation: "Preparing recommendations",
  report_generation: "Generating report",
  workflow_complete: "Finishing up",
};

const TERMINAL_STATUSES = ["completed", "partial", "failed", "cancelled", "unavailable"];

type RunState = "running" | "waiting" | "recovering" | "stalled" | "failed" | "completed";

const RUN_STATE_TEXT: Record<RunState, string> = {
  running: "Active",
  waiting: "Waiting",
  recovering: "Resuming",
  stalled: "Stalled",
  failed: "Failed",
  completed: "Completed",
};

function statusLabel(status: string | null | undefined): string {
  if (!status) return "Unknown";
  return status.replaceAll("_", " ").replace(/\b\w/g, (character) => character.toUpperCase());
}

function formatDuration(totalSeconds: number): string {
  const seconds = Math.max(0, Math.floor(totalSeconds));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const rest = seconds % 60;
  if (hours > 0) return `${hours}h ${minutes}m`;
  if (minutes > 0) return `${minutes}m ${rest}s`;
  return `${rest}s`;
}

// Canonical run state derived only from backend truth. Backend `stale` is
// authoritative and is checked before terminal status because a stale run is
// reconciled to "failed" by the progress endpoint while remaining resumable.
function deriveRunState(progress: WorkflowProgress, pendingAction: string | null): RunState {
  if (pendingAction === "resume") return "recovering";
  if (progress.stale) return "stalled";
  const status = progress.status;
  if (status === "completed" || status === "partial") return "completed";
  if (status === "failed" || status === "cancelled" || status === "unavailable") return "failed";
  if (status === "pending" || status === "queued") return "waiting";
  return "running";
}

interface AnalysisProgressTimelineProps {
  progress: WorkflowProgress;
  acting: boolean;
  pendingAction?: "cancel" | "resume" | null;
  onPerformAction: (action: "cancel" | "resume") => void;
}

export function AnalysisProgressTimeline({
  progress,
  acting,
  pendingAction = null,
  onPerformAction,
}: AnalysisProgressTimelineProps) {
  const isTerminal = TERMINAL_STATUSES.includes(progress.status) && !progress.stale;
  const runState = deriveRunState(progress, pendingAction);

  // Truthful interpolation: the display may animate one step at a time toward
  // the latest backend-confirmed percentage, then it MUST hold there. It never
  // exceeds the backend target and never invents progress from elapsed time.
  const backendTarget = progress.progress_percentage;
  const [interpolatedProgress, setInterpolatedProgress] = React.useState(backendTarget);

  React.useEffect(() => {
    if (interpolatedProgress === backendTarget) return;
    // Respect prefers-reduced-motion: jump straight to the authoritative value.
    const reduceMotion =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    // A backend value below the display (legitimate retry/reset semantics)
    // snaps immediately rather than animating backwards.
    if (reduceMotion || backendTarget < interpolatedProgress) {
      const snapFrame = requestAnimationFrame(() => setInterpolatedProgress(backendTarget));
      return () => cancelAnimationFrame(snapFrame);
    }
    const startTime = performance.now();
    const startValue = interpolatedProgress;
    const duration = 500;
    let frameId: number;
    const tick = (currentTime: number) => {
      const elapsed = currentTime - startTime;
      if (elapsed >= duration) {
        setInterpolatedProgress(backendTarget);
      } else {
        const t = elapsed / duration;
        const easeOut = 1 - Math.pow(1 - t, 3);
        // Clamp: interpolation can approach but never exceed the backend value.
        setInterpolatedProgress(
          Math.min(backendTarget, startValue + (backendTarget - startValue) * easeOut),
        );
        frameId = requestAnimationFrame(tick);
      }
    };
    frameId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frameId);
  }, [backendTarget, interpolatedProgress]);

  const displayedProgress = Math.min(interpolatedProgress, backendTarget);

  // Last-activity ticker: refreshes the human-readable age of the backend
  // heartbeat. API reachability alone never counts as analysis activity —
  // only the backend `last_progress_update` timestamp does.
  const [nowMs, setNowMs] = React.useState(() => Date.now());
  React.useEffect(() => {
    if (isTerminal) return;
    let timer: number | undefined;
    const tickClock = () => {
      setNowMs(Date.now());
      timer = window.setTimeout(tickClock, 5_000);
    };
    timer = window.setTimeout(tickClock, 5_000);
    return () => {
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [isTerminal]);

  const lastActivityMs = progress.last_progress_update
    ? Date.parse(progress.last_progress_update)
    : Number.NaN;
  const activityAgeSeconds = Number.isFinite(lastActivityMs)
    ? Math.max(0, (nowMs - lastActivityMs) / 1000)
    : null;
  const lastActivityText =
    activityAgeSeconds === null
      ? "Not recorded"
      : activityAgeSeconds < 10
        ? "Moments ago"
        : `${formatDuration(activityAgeSeconds)} ago`;

  const currentStageLabel = useMemo(() => {
    const stage = progress.stages.find((item) => item.stage_id === progress.current_stage);
    return (
      CUSTOMER_STAGE_LABELS[progress.current_stage ?? ""] ??
      stage?.label ??
      statusLabel(progress.current_stage)
    );
  }, [progress.stages, progress.current_stage]);

  const progressDescription = useMemo(() => {
    if (progress.progress_percentage === 100 && progress.report_generation_available) {
      return progress.status === "partial"
        ? "Analysis completed with limitations. The final report is available."
        : "Analysis completed. The final report is available.";
    }
    return `${progress.progress_percentage.toFixed(0)}% complete. Current stage: ${currentStageLabel}`;
  }, [progress, currentStageLabel]);

  const discoveryPending = progress.page_coverage.discovery_completeness == null;
  const discoveryRunning = progress.page_coverage.discovery_stage_status === "running";

  const discoveryStatusText = discoveryPending
    ? isTerminal
      ? "Not Recorded"
      : discoveryRunning
        ? "In Progress"
        : "Pending"
    : statusLabel(progress.page_coverage.discovery_completeness);

  // Neutral aggregated browser counter over AVAILABLE internal engines only —
  // unavailable engines are excluded from the denominator so the total stays
  // truthful. Engine-level detail remains under Technical execution details.
  const availableEngines = progress.browser_engine_progress.engines.filter(
    (engine) => engine.availability_status !== "unavailable",
  );
  const browserChecksTotal = availableEngines.reduce(
    (total, engine) => total + (engine.eligible_pages || 0),
    0,
  );
  const browserChecksDone = availableEngines.reduce(
    (total, engine) => total + (engine.tested_pages || 0),
    0,
  );
  const browserStageActive =
    progress.current_stage === "browser_compatibility" ||
    progress.current_stage === "browser_engine_analysis";

  const pagesEligible = progress.page_coverage.eligible_pages ?? 0;
  const pagesAnalysed = progress.page_coverage.successfully_analysed_pages ?? 0;

  const stateChip = (() => {
    switch (runState) {
      case "running":
        return (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-z-success-subtle text-z-success border border-z-success/30 px-3 py-1 text-xs font-bold">
            <Activity className="h-3.5 w-3.5" aria-hidden="true" /> {RUN_STATE_TEXT.running}
          </span>
        );
      case "waiting":
        return (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-z-neutral-subtle text-z-ink-secondary border border-z-border px-3 py-1 text-xs font-bold">
            <PauseCircle className="h-3.5 w-3.5" aria-hidden="true" /> {RUN_STATE_TEXT.waiting}
          </span>
        );
      case "recovering":
        return (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-z-info-subtle text-z-info border border-z-info/30 px-3 py-1 text-xs font-bold">
            <Loader2 className="h-3.5 w-3.5 motion-safe:animate-spin" aria-hidden="true" /> {RUN_STATE_TEXT.recovering}
          </span>
        );
      case "stalled":
        return (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-z-warning-subtle text-z-warning border border-z-warning/30 px-3 py-1 text-xs font-bold">
            <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" /> {RUN_STATE_TEXT.stalled}
          </span>
        );
      case "failed":
        return (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-z-danger-subtle text-z-danger border border-z-danger/30 px-3 py-1 text-xs font-bold">
            <XCircle className="h-3.5 w-3.5" aria-hidden="true" /> {RUN_STATE_TEXT.failed}
          </span>
        );
      default:
        return (
          <StatusBadge
            status={progress.status === "partial" && progress.report_generation_available ? "partial" : progress.status}
            label={progress.status === "partial" && progress.report_generation_available ? "Completed with limitations" : undefined}
          />
        );
    }
  })();

  return (
    <div className="flex flex-col gap-6">
      {/* Meaningful state changes only — never per-percent announcements. */}
      <p className="sr-only" role="status" aria-live="polite">
        {runState === "stalled"
          ? "Analysis appears stalled. Recovery is available."
          : runState === "failed"
            ? "Analysis failed."
            : runState === "completed"
              ? "Analysis completed."
              : runState === "recovering"
                ? "Resuming analysis."
                : `Analysis ${RUN_STATE_TEXT[runState].toLowerCase()}.`}
      </p>

      {/* 1. Analysis Identity & Progress Header */}
      <div className="rounded-xl border border-z-border bg-z-surface p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-widest text-z-ink-muted">
              Active Analysis Run
            </p>
            <h3 className="mt-1 text-xl font-bold text-z-ink">
              {progress.submitted_website ?? "Website Analysis"}
            </h3>
            <p className="mt-1 text-sm text-z-ink-secondary">
              Started {new Date(progress.started_at).toLocaleString()}
            </p>
          </div>
          <div className="flex flex-col items-end gap-2">{stateChip}</div>
        </div>

        <div className="mt-6">
          <div className="flex flex-wrap justify-between gap-2 text-sm font-semibold text-z-ink mb-2">
            <span>{progressDescription}</span>
            <span>{displayedProgress.toFixed(0)}%</span>
          </div>
          <div
            className="h-3 w-full overflow-hidden rounded-full bg-z-neutral-subtle border border-z-border shadow-inner"
            role="progressbar"
            aria-label={progressDescription}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(displayedProgress)}
          >
            <div
              className={`h-full transition-all duration-500 ease-out ${
                runState === "failed"
                  ? "bg-z-danger"
                  : runState === "stalled"
                    ? "bg-z-warning"
                    : runState === "completed"
                      ? "bg-z-success"
                      : "bg-z-info relative overflow-hidden"
              }`}
              style={{ width: `${displayedProgress}%` }}
            >
              {/* The shimmer is an activity cue: it only renders while the
                  backend heartbeat says work is genuinely active. */}
              {runState === "running" && (
                <div
                  className="absolute inset-0 bg-white/20 motion-safe:animate-[pulse_2s_ease-in-out_infinite]"
                  style={{
                    backgroundImage:
                      "linear-gradient(90deg, transparent, rgba(255,255,255,0.3), transparent)",
                    transform: "skewX(-20deg)",
                  }}
                />
              )}
            </div>
          </div>
        </div>

        {/* Secondary liveness strip: elapsed alone never implies activity —
            it is always paired with the backend last-activity heartbeat. */}
        <dl className="mt-5 grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-3 lg:grid-cols-5">
          <div>
            <dt className="text-xs font-semibold uppercase tracking-wider text-z-ink-muted">Elapsed</dt>
            <dd className="mt-0.5 font-bold text-z-ink">{formatDuration(progress.elapsed_seconds)}</dd>
          </div>
          <div>
            <dt className="text-xs font-semibold uppercase tracking-wider text-z-ink-muted">Last activity</dt>
            <dd className={`mt-0.5 font-bold ${runState === "stalled" ? "text-z-warning" : "text-z-ink"}`}>
              {lastActivityText}
            </dd>
          </div>
          <div>
            <dt className="text-xs font-semibold uppercase tracking-wider text-z-ink-muted">Stage</dt>
            <dd className="mt-0.5 font-bold text-z-ink">{currentStageLabel}</dd>
          </div>
          {pagesEligible > 0 && (
            <div>
              <dt className="text-xs font-semibold uppercase tracking-wider text-z-ink-muted">Pages analysed</dt>
              <dd className="mt-0.5 font-bold text-z-ink">
                {pagesAnalysed} / {pagesEligible}
              </dd>
            </div>
          )}
          {(browserStageActive || browserChecksDone > 0) && browserChecksTotal > 0 && (
            <div>
              <dt className="text-xs font-semibold uppercase tracking-wider text-z-ink-muted">Browser analysis</dt>
              <dd className="mt-0.5 font-bold text-z-ink">
                {browserChecksDone} / {browserChecksTotal} checks
              </dd>
            </div>
          )}
          {progress.attempt > 1 && (
            <div>
              <dt className="text-xs font-semibold uppercase tracking-wider text-z-ink-muted">Attempt</dt>
              <dd className="mt-0.5 font-bold text-z-ink">{progress.attempt}</dd>
            </div>
          )}
        </dl>
      </div>

      {/* 2. Stalled experience — backend `stale` is the only authority. */}
      {runState === "stalled" && (
        <div className="rounded-xl border border-z-warning/40 bg-z-warning-subtle p-5">
          <div className="flex items-start gap-3">
            <AlertTriangle className="h-5 w-5 text-z-warning shrink-0 mt-0.5" aria-hidden="true" />
            <div>
              <h4 className="font-semibold text-z-warning">Analysis appears stalled</h4>
              <p className="mt-1 text-sm text-z-ink">
                No analysis activity has been recorded recently
                {activityAgeSeconds !== null
                  ? ` (last activity ${formatDuration(activityAgeSeconds)} ago)`
                  : ""}
                .
              </p>
              {progress.business_error_message && (
                <p className="mt-1 text-sm text-z-ink-secondary">{progress.business_error_message}</p>
              )}
              {progress.resume_available && (
                <p className="mt-2 text-sm text-z-ink-secondary">
                  Resuming continues from the completed work — pages already analysed are preserved.
                </p>
              )}
            </div>
          </div>
        </div>
      )}

      {/* 3. Terminal failure (non-stalled) */}
      {runState === "failed" && progress.business_error_message && (
        <div className="rounded-xl border border-z-danger/30 bg-z-danger-subtle p-5">
          <div className="flex items-start gap-3">
            <AlertCircle className="h-5 w-5 text-z-danger shrink-0 mt-0.5" aria-hidden="true" />
            <div>
              <h4 className="font-semibold text-z-danger">Analysis Failed</h4>
              <p className="mt-1 text-sm text-z-danger/90">
                {progress.failed_stage_id && (
                  <span className="font-bold mr-1">
                    Stage {progress.stages.find((s) => s.stage_id === progress.failed_stage_id)?.label ?? statusLabel(progress.failed_stage_id)}:
                  </span>
                )}
                {progress.business_error_message}
              </p>
            </div>
          </div>
        </div>
      )}

      {progress.page_coverage.discovery_completeness != null &&
       progress.page_coverage.discovery_completeness !== "complete" && (
        <div className="rounded-xl border border-z-warning/30 bg-z-warning-subtle p-5">
          <div className="flex items-start gap-3">
            <AlertCircle className="h-5 w-5 text-z-warning shrink-0 mt-0.5" aria-hidden="true" />
            <div>
              <h4 className="font-semibold text-z-warning">
                Discovery {progress.page_coverage.discovery_completeness}
              </h4>
              <p className="mt-1 text-sm text-z-warning/90">
                {progress.page_coverage.discovery_failure_message ??
                  "The retained discovered pages remain usable, but they may not represent the full website."}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* 4. Site coverage stays primary — customers care about page progress. */}
      <div className="rounded-xl border border-z-border bg-z-surface p-5">
        <h4 className="text-base font-bold text-z-ink flex items-center justify-between mb-4">
          Site Coverage
          <ConceptInfoButton conceptId="discovery_completeness" title="Discovery completeness" />
        </h4>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <MetricStat
            label="Completeness"
            value={discoveryStatusText}
          />
          <MetricStat
            label="Pages Discovered"
            value={String(progress.page_coverage.discovered_pages)}
          />
          <MetricStat
            label="Successfully Analysed"
            value={String(progress.page_coverage.successfully_analysed_pages)}
          />
          <MetricStat
            label="Assets (Media/Docs)"
            value={String(progress.page_coverage.document_assets + progress.page_coverage.media_static_assets)}
          />
        </div>
      </div>

      {/* 5. Technical execution details — the 8-agent pipeline and internal
          engine diagnostics remain fully available, as a secondary disclosure. */}
      <details className="rounded-xl border border-z-border bg-z-surface">
        <summary className="cursor-pointer select-none p-5 text-base font-bold text-z-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-z-info rounded-xl">
          Technical execution details
        </summary>
        <div className="flex flex-col gap-6 px-5 pb-5">
          <div>
            <h4 className="text-base font-bold text-z-ink flex items-center gap-2 mb-4">
              Eight-Agent Execution Pipeline
            </h4>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {progress.agent_states.map((agent) => {
                const label = AGENT_LABELS[agent.agent_id] ?? statusLabel(agent.agent_id);
                const Icon = AGENT_ICONS[agent.agent_id] ?? Activity;
                const isRunning = agent.status === "running";
                const isActive = isRunning || agent.status === "completed" || agent.status === "partial";

                return (
                  <div
                    key={agent.agent_id}
                    className={`rounded-lg border p-4 transition-colors ${
                      isRunning
                        ? "border-z-info bg-z-info-subtle/30 shadow-sm"
                        : isActive
                          ? "border-z-border bg-z-surface"
                          : "border-z-border/50 bg-z-surface/50 opacity-70"
                    }`}
                  >
                    <div className="flex items-start justify-between mb-2">
                      <div className={`p-1.5 rounded-md ${isRunning ? 'bg-z-info text-white' : isActive ? 'bg-z-neutral-subtle text-z-ink' : 'bg-z-neutral-subtle/50 text-z-ink-muted'}`}>
                        <Icon className="h-4 w-4" aria-hidden="true" />
                      </div>
                      <StatusBadge status={agent.status} size="xs" />
                    </div>
                    <p className={`text-sm font-semibold mt-2 ${isActive ? 'text-z-ink' : 'text-z-ink-secondary'}`}>
                      {label}
                    </p>
                  </div>
                );
              })}
            </div>
          </div>

          <div>
            <h4 className="text-base font-bold text-z-ink flex items-center justify-between mb-4">
              Internal Browser Engines
              <ConceptInfoButton conceptId="browser_coverage" title="Browser coverage" />
            </h4>
            <p className="mb-3 text-xs text-z-ink-secondary">
              Engine-level internal evidence. This is not branded browser
              verification: Chromium is not Chrome or Edge, and WebKit is not Safari.
            </p>
            <div className="space-y-4">
              <div className="flex justify-between items-end pb-3 border-b border-z-border">
                <div>
                  <p className="text-xs font-semibold text-z-ink-muted uppercase tracking-wider">Overall Status</p>
                  <p className="mt-1 font-bold text-z-ink capitalize">{statusLabel(progress.browser_engine_progress.status)}</p>
                </div>
                <div className="text-right">
                  <p className="text-xs font-semibold text-z-ink-muted uppercase tracking-wider">Engine Coverage</p>
                  <p className="mt-1 font-bold text-z-ink">{browserChecksDone} / {browserChecksTotal} tests</p>
                </div>
              </div>
              <div className="grid grid-cols-3 gap-2">
                {progress.browser_engine_progress.engines.map((engine) => (
                  <div key={engine.engine} className="text-center">
                    <p className="text-xs font-medium text-z-ink-secondary truncate" title={ENGINE_LABELS[engine.engine] ?? statusLabel(engine.engine)}>
                      {ENGINE_LABELS[engine.engine] ?? statusLabel(engine.engine)}
                    </p>
                    {engine.availability_status === "unavailable" ? (
                      <span className="mt-1 inline-block text-[10px] bg-z-neutral-subtle text-z-ink-muted px-1.5 py-0.5 rounded">N/A</span>
                    ) : (
                      <p className="mt-1 text-sm font-bold text-z-ink">{engine.tested_pages}/{engine.eligible_pages}</p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </details>

      {/* 6. Recovery actions */}
      <div className="flex flex-wrap gap-3 items-center pt-2">
        {!isTerminal && runState !== "stalled" && (
          <button
            className="inline-flex items-center gap-2 rounded-lg border border-z-danger text-z-danger px-4 py-2 text-sm font-semibold hover:bg-z-danger-subtle focus:ring-2 focus:ring-z-danger/50 focus:outline-none disabled:opacity-50 transition-colors"
            disabled={acting}
            onClick={() => onPerformAction("cancel")}
            type="button"
          >
            <XCircle className="h-4 w-4" aria-hidden="true" />
            Cancel analysis
          </button>
        )}
        {progress.retry_available && (
          <button
            className={`inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold shadow-sm focus:ring-2 focus:outline-none disabled:opacity-50 transition-colors ${
              runState === "stalled"
                ? "bg-z-info text-white hover:bg-z-info/90 focus:ring-z-info/50"
                : "bg-z-surface border border-z-border text-z-ink hover:bg-z-neutral-subtle focus:ring-z-ink/50"
            }`}
            disabled={acting || !progress.resume_available}
            onClick={() => onPerformAction("resume")}
            type="button"
          >
            <RotateCcw className={`h-4 w-4 ${pendingAction === "resume" ? "motion-safe:animate-spin" : ""}`} aria-hidden="true" />
            {pendingAction === "resume"
              ? "Resuming…"
              : progress.page_coverage.discovery_retry_available
                ? "Retry incomplete discovery"
                : "Retry or resume analysis"}
          </button>
        )}
      </div>

    </div>
  );
}
