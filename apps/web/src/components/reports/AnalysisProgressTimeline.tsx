"use client";

import React, { useMemo } from "react";
import type { WorkflowProgress } from "@/components/reports/types";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { ConceptInfoButton } from "@/components/metrics/ConceptInfoButton";
import { MetricStat } from "@/components/ui/MetricStat";
import { AlertCircle, RotateCcw, XCircle, LayoutDashboard, Search, Eye, Activity, ShieldCheck, CheckSquare, Zap, FileText } from "lucide-react";

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

const AGENT_LABELS: Record<string, string> = {
  discovery_agent: "Discovery Agent",
  performance_agent: "Performance Agent",
  accessibility_agent: "Accessibility Agent",
  site_diagnostics_agent: "Site Diagnostics Agent",
  repository_intelligence_agent: "Repository Intelligence Agent",
  evidence_validation_agent: "Evidence Validation Agent",
  remediation_agent: "Remediation Agent",
  report_agent: "Report Agent",
};

const ENGINE_LABELS: Record<string, string> = {
  chromium: "Chromium Engine",
  firefox: "Firefox Engine",
  webkit: "WebKit Engine",
};

const TERMINAL_STATUSES = ["completed", "partial", "failed", "cancelled", "unavailable"];

function statusLabel(status: string | null | undefined): string {
  if (!status) return "Unknown";
  return status.replaceAll("_", " ").replace(/\b\w/g, (character) => character.toUpperCase());
}

interface AnalysisProgressTimelineProps {
  progress: WorkflowProgress;

  acting: boolean;
  onPerformAction: (action: "cancel" | "resume") => void;
}

export function AnalysisProgressTimeline({
  progress,
  acting,
  onPerformAction,
}: AnalysisProgressTimelineProps) {
  const isTerminal = TERMINAL_STATUSES.includes(progress.status);

  // Truthful interpolation: animates only to the known backend value, no fake infinite progression.
  const [interpolatedProgress, setInterpolatedProgress] = React.useState(progress.progress_percentage);

  React.useEffect(() => {
    if (interpolatedProgress === progress.progress_percentage) return;

    const startTime = performance.now();
    const startValue = interpolatedProgress;
    const targetValue = progress.progress_percentage;
    const duration = 500; // Match the CSS transition duration

    let frameId: number;
    const tick = (currentTime: number) => {
      const elapsed = currentTime - startTime;
      if (elapsed >= duration) {
        setInterpolatedProgress(targetValue);
      } else {
        const t = elapsed / duration;
        const easeOut = 1 - Math.pow(1 - t, 3);
        setInterpolatedProgress(startValue + (targetValue - startValue) * easeOut);
        frameId = requestAnimationFrame(tick);
      }
    };

    frameId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frameId);
  }, [progress.progress_percentage, interpolatedProgress]);

  const progressDescription = useMemo(() => {
    if (progress.progress_percentage === 100 && progress.report_generation_available) {
      return progress.status === "partial"
        ? "Analysis completed with limitations. The final report is available."
        : "Analysis completed. The final report is available.";
    }
    const stage = progress.stages.find((item) => item.stage_id === progress.current_stage);
    return `${progress.progress_percentage.toFixed(0)}% complete. Current stage: ${stage?.label ?? statusLabel(progress.current_stage)}`;
  }, [progress]);

  const discoveryPending = progress.page_coverage.discovery_completeness == null;
  const discoveryRunning = progress.page_coverage.discovery_stage_status === "running";

  const discoveryStatusText = discoveryPending
    ? isTerminal
      ? "Not Recorded"
      : discoveryRunning
        ? "In Progress"
        : "Pending"
    : statusLabel(progress.page_coverage.discovery_completeness);

  const browserAttemptDenominator = progress.browser_engine_progress.engines.reduce(
    (total, engine) => total + (engine.eligible_pages || 0),
    0,
  );
  const browserTestedNumerator = progress.browser_engine_progress.engines.reduce(
    (total, engine) => total + (engine.tested_pages || 0),
    0,
  );

  return (
    <div className="flex flex-col gap-6" aria-live="polite">
      {/* 1. Analysis Identity & Progress Header */}
      <div className="rounded-xl border border-z-border bg-z-surface p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-widest text-z-muted">
              Active Analysis Run
            </p>
            <h3 className="mt-1 text-xl font-bold text-z-text">
              {progress.submitted_website ?? "Website Analysis"}
            </h3>
            <p className="mt-1 text-sm text-z-text-subtle">
              Started {new Date(progress.started_at).toLocaleString()} · Elapsed {progress.elapsed_seconds.toFixed(1)}s
            </p>
          </div>
          <div className="flex flex-col items-end gap-2">
            <StatusBadge
              status={progress.status === "partial" && progress.report_generation_available ? "partial" : progress.status}
              label={progress.status === "partial" && progress.report_generation_available ? "Completed with limitations" : undefined}
            />
          </div>
        </div>

        <div className="mt-6">
          <div className="flex justify-between text-sm font-semibold text-z-text mb-2">
            <span>{progressDescription}</span>
            <span>{interpolatedProgress.toFixed(0)}%</span>
          </div>
          <div
            className="h-3 w-full overflow-hidden rounded-full bg-z-neutral-subtle border border-z-border shadow-inner"
            role="progressbar"
            aria-label={progressDescription}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={interpolatedProgress}
          >
            <div
              className={`h-full transition-all duration-500 ease-out ${
                isTerminal
                  ? progress.status === 'failed' || progress.status === 'cancelled' ? 'bg-z-danger' : 'bg-z-success'
                  : 'bg-z-info relative overflow-hidden'
              }`}
              style={{ width: `${progress.progress_percentage}%` }}
            >
              {!isTerminal && (
                <div className="absolute inset-0 bg-white/20 animate-[pulse_2s_ease-in-out_infinite]" style={{
                  backgroundImage: 'linear-gradient(90deg, transparent, rgba(255,255,255,0.3), transparent)',
                  transform: 'skewX(-20deg)'
                }} />
              )}
            </div>
          </div>
        </div>
      </div>

      {/* 2. Limitations & Errors */}
      {progress.business_error_message && (
        <div className="rounded-xl border border-z-danger/30 bg-z-danger-subtle p-5">
          <div className="flex items-start gap-3">
            <AlertCircle className="h-5 w-5 text-z-danger shrink-0 mt-0.5" />
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
            <AlertCircle className="h-5 w-5 text-z-warning shrink-0 mt-0.5" />
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

      {/* 3. Stage Timeline (Agents) */}
      <div className="rounded-xl border border-z-border bg-z-surface p-5">
        <h4 className="text-lg font-bold text-z-text flex items-center gap-2 mb-4">
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
                      : "border-z-border/50 bg-z-background/50 opacity-70"
                }`}
              >
                <div className="flex items-start justify-between mb-2">
                  <div className={`p-1.5 rounded-md ${isRunning ? 'bg-z-info text-white' : isActive ? 'bg-z-neutral-subtle text-z-text' : 'bg-z-neutral-subtle/50 text-z-muted'}`}>
                    <Icon className="h-4 w-4" />
                  </div>
                  <StatusBadge status={agent.status} size="xs" />
                </div>
                <p className={`text-sm font-semibold mt-2 ${isActive ? 'text-z-text' : 'text-z-text-subtle'}`}>
                  {label}
                </p>
              </div>
            );
          })}
        </div>
      </div>

      {/* 4. Live Evidence / Website Coverage */}
      <div className="grid gap-6 sm:grid-cols-2">
        <div className="rounded-xl border border-z-border bg-z-surface p-5">
          <h4 className="text-base font-bold text-z-text flex items-center justify-between mb-4">
            Site Coverage
            <ConceptInfoButton conceptId="discovery_completeness" title="Discovery completeness" />
          </h4>
          <div className="grid grid-cols-2 gap-4">
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

        <div className="rounded-xl border border-z-border bg-z-surface p-5">
          <h4 className="text-base font-bold text-z-text flex items-center justify-between mb-4">
            Browser Engines
            <ConceptInfoButton conceptId="browser_coverage" title="Browser coverage" />
          </h4>
          <div className="space-y-4">
            <div className="flex justify-between items-end pb-3 border-b border-z-border">
              <div>
                <p className="text-xs font-semibold text-z-muted uppercase tracking-wider">Overall Status</p>
                <p className="mt-1 font-bold text-z-text capitalize">{statusLabel(progress.browser_engine_progress.status)}</p>
              </div>
              <div className="text-right">
                <p className="text-xs font-semibold text-z-muted uppercase tracking-wider">Engine Coverage</p>
                <p className="mt-1 font-bold text-z-text">{browserTestedNumerator} / {browserAttemptDenominator} tests</p>
              </div>
            </div>
            <div className="grid grid-cols-3 gap-2">
              {progress.browser_engine_progress.engines.map((engine) => (
                <div key={engine.engine} className="text-center">
                  <p className="text-xs font-medium text-z-text-subtle truncate" title={ENGINE_LABELS[engine.engine] ?? statusLabel(engine.engine)}>
                    {ENGINE_LABELS[engine.engine] ?? statusLabel(engine.engine)}
                  </p>
                  {engine.availability_status === "unavailable" ? (
                    <span className="mt-1 inline-block text-[10px] bg-z-neutral-subtle text-z-muted px-1.5 py-0.5 rounded">N/A</span>
                  ) : (
                    <p className="mt-1 text-sm font-bold text-z-text">{engine.tested_pages}/{engine.eligible_pages}</p>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* 5. Limitations & Recovery Actions */}
      <div className="flex flex-wrap gap-3 items-center pt-2">
        {!isTerminal && (
          <button
            className="inline-flex items-center gap-2 rounded-lg border border-z-danger text-z-danger px-4 py-2 text-sm font-semibold hover:bg-z-danger-subtle focus:ring-2 focus:ring-z-danger/50 focus:outline-none disabled:opacity-50 transition-colors"
            disabled={acting}
            onClick={() => onPerformAction("cancel")}
            type="button"
          >
            <XCircle className="h-4 w-4" />
            Cancel analysis
          </button>
        )}
        {progress.retry_available && (
          <button
            className="inline-flex items-center gap-2 rounded-lg bg-z-surface border border-z-border text-z-text px-4 py-2 text-sm font-semibold hover:bg-z-neutral-subtle shadow-sm focus:ring-2 focus:ring-z-text/50 focus:outline-none disabled:opacity-50 transition-colors"
            disabled={acting || !progress.resume_available}
            onClick={() => onPerformAction("resume")}
            type="button"
          >
            <RotateCcw className="h-4 w-4" />
            {progress.page_coverage.discovery_retry_available
              ? "Retry incomplete discovery"
              : "Retry or resume analysis"}
          </button>
        )}
      </div>

    </div>
  );
}
