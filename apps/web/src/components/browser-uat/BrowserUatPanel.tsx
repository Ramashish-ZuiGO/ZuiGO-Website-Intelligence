"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type {
  BrowserUatExecution,
  BrowserUatPageResult,
  BrowserUatTier0Status,
  BrowserUatViewportResult,
} from "@/components/browser-uat/types";
import { browserUatApi, ApiError } from "@/lib/browser-uat-api";
import { StatusBadge } from "@/components/ui/StatusBadge";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const POLL_INTERVAL_MS = 5_000;

const TERMINAL_STATUSES: ReadonlySet<BrowserUatTier0Status> = new Set([
  "completed",
  "partial",
  "failed",
  "cancelled",
  "unavailable",
]);

const PLATFORM_LABELS: Record<string, string> = {
  windows: "Windows",
  macos: "macOS",
  android: "Android",
  ios: "iOS",
  ipados: "iPadOS",
};

const BROWSER_LABELS: Record<string, string> = {
  chrome: "Chrome",
  msedge: "Edge",
  safari: "Safari",
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function platformLabel(platform: string): string {
  return PLATFORM_LABELS[platform] ?? platform;
}

function browserLabel(channel: string): string {
  return BROWSER_LABELS[channel] ?? channel;
}

function groupKey(result: BrowserUatPageResult): string {
  return `${result.browser_channel}:${result.platform}`;
}

function groupLabel(result: BrowserUatPageResult): string {
  return `${browserLabel(result.browser_channel)} · ${platformLabel(result.platform)}`;
}

function isManualLane(result: BrowserUatPageResult): boolean {
  return result.platform === "android";
}

function totalIssues(vr: BrowserUatViewportResult): number {
  return (
    (vr.horizontal_overflow ? 1 : 0) +
    vr.critical_elements_outside_viewport +
    vr.overlapping_elements +
    vr.small_tap_targets
  );
}

function statusForGroup(results: BrowserUatPageResult[]): string {
  if (results.some((r) => r.status === "fail")) return "failed";
  if (results.some((r) => r.status === "error")) return "failed";
  if (results.every((r) => r.status === "pass")) return "passed";
  return "partial";
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function ViewportRow({ vr }: { vr: BrowserUatViewportResult }) {
  const [expanded, setExpanded] = useState(false);
  const issues = totalIssues(vr);

  return (
    <>
      <tr className="border-t border-z-border-subtle">
        <td className="px-3 py-2 text-sm">{vr.viewport_name}</td>
        <td className="px-3 py-2 text-sm text-center">
          {`${vr.viewport_width}×${vr.viewport_height}`}
        </td>
        <td className="px-3 py-2 text-sm text-center">
          {vr.horizontal_overflow ? (
            <span className="text-z-danger font-medium">Yes</span>
          ) : (
            <span className="text-z-success">No</span>
          )}
        </td>
        <td className="px-3 py-2 text-sm text-center">
          {vr.critical_elements_outside_viewport > 0 ? (
            <span className="text-z-danger font-medium">
              {vr.critical_elements_outside_viewport}
            </span>
          ) : (
            "0"
          )}
        </td>
        <td className="px-3 py-2 text-sm text-center">
          {vr.overlapping_elements > 0 ? (
            <span className="text-z-warning font-medium">
              {vr.overlapping_elements}
            </span>
          ) : (
            "0"
          )}
        </td>
        <td className="px-3 py-2 text-sm text-center">
          {vr.small_tap_targets > 0 ? (
            <span className="text-z-warning font-medium">
              {vr.small_tap_targets}
            </span>
          ) : (
            "0"
          )}
          {vr.tap_target_samples.length > 0 && (
            <button
              aria-expanded={expanded}
              aria-label={`${expanded ? "Hide" : "Show"} tap target samples`}
              className="ml-2 text-z-accent underline text-xs"
              onClick={() => setExpanded((v) => !v)}
              type="button"
            >
              {expanded ? "hide" : `${vr.tap_target_samples.length} samples`}
            </button>
          )}
        </td>
        <td className="px-3 py-2 text-sm text-center font-medium">
          {issues === 0 ? (
            <span className="text-z-success">Clean</span>
          ) : (
            <span className="text-z-danger">{issues} issue{issues !== 1 ? "s" : ""}</span>
          )}
        </td>
      </tr>
      {expanded && vr.tap_target_samples.length > 0 && (
        <tr>
          <td className="px-3 py-2 bg-z-surface-muted" colSpan={7}>
            <p className="text-xs font-semibold text-z-ink-secondary mb-1">
              Tap target samples (below 48×48 minimum)
            </p>
            <ul className="grid gap-1 text-xs text-z-ink-secondary">
              {vr.tap_target_samples.map((sample, idx) => (
                <li key={idx}>
                  <code className="font-mono">
                    &lt;{sample.element_type}&gt;
                  </code>{" "}
                  {sample.width.toFixed(1)}×{sample.height.toFixed(1)}px
                  {sample.accessible_label
                    ? ` — "${sample.accessible_label}"`
                    : " — no accessible label"}
                  {sample.spacing_exception && (
                    <span className="ml-1 text-z-info">(spacing exception)</span>
                  )}
                </li>
              ))}
            </ul>
          </td>
        </tr>
      )}
    </>
  );
}

function PageResultCard({ result }: { result: BrowserUatPageResult }) {
  const [open, setOpen] = useState(false);
  const hasViewports = result.viewport_results.length > 0;
  const allClean =
    hasViewports &&
    result.viewport_results.every((vr) => totalIssues(vr) === 0);

  return (
    <div className="rounded-lg border border-z-border bg-z-surface">
      <button
        aria-expanded={open}
        className="w-full flex items-center justify-between gap-3 px-4 py-3 text-left hover:bg-z-surface-muted transition-colors rounded-lg"
        onClick={() => setOpen((v) => !v)}
        type="button"
      >
        <div className="min-w-0">
          <p className="text-sm font-medium text-z-ink truncate">
            {result.url}
          </p>
          <p className="text-xs text-z-ink-muted mt-0.5">
            {browserLabel(result.browser_channel)} {result.browser_version} · {platformLabel(result.platform)}
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <StatusBadge
            status={result.status === "pass" ? "passed" : result.status === "fail" ? "failed" : result.status}
            size="xs"
          />
          <span
            aria-hidden="true"
            className={`text-z-ink-muted text-xs transition-transform ${open ? "rotate-180" : ""}`}
          >
            ▾
          </span>
        </div>
      </button>

      {open && (
        <div className="border-t border-z-border-subtle px-4 py-3">
          {result.error_message && (
            <p className="text-sm text-z-danger mb-3">{result.error_message}</p>
          )}
          {!hasViewports ? (
            <p className="text-sm text-z-ink-muted">
              No viewport data available for this page.
            </p>
          ) : allClean ? (
            <p className="text-sm text-z-success font-medium">
              All viewports passed without structural issues.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[48rem] text-left border-collapse">
                <thead>
                  <tr className="bg-z-surface-muted">
                    {[
                      "Viewport",
                      "Size",
                      "Overflow",
                      "Outside viewport",
                      "Overlapping",
                      "Small tap targets",
                      "Result",
                    ].map((col) => (
                      <th
                        className="px-3 py-2 text-xs font-semibold text-z-ink-secondary"
                        key={col}
                        scope="col"
                      >
                        {col}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {result.viewport_results.map((vr, idx) => (
                    <ViewportRow key={idx} vr={vr} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ResultsGroup({
  label,
  results,
  manual,
}: {
  label: string;
  results: BrowserUatPageResult[];
  manual: boolean;
}) {
  const status = statusForGroup(results);

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 flex-wrap">
        <h4 className="text-sm font-bold text-z-ink">{label}</h4>
        <StatusBadge status={status} size="xs" />
        {manual && (
          <span className="inline-flex items-center gap-1 rounded-full bg-z-info-subtle text-z-info border border-z-info/20 px-2 py-0.5 text-[10px] font-medium">
            Verified by our team on a real device
          </span>
        )}
      </div>
      <div className="grid gap-2">
        {results.map((result) => (
          <PageResultCard key={result.page_result_id} result={result} />
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

interface BrowserUatPanelProps {
  analysisRunId: string;
}

export function BrowserUatPanel({ analysisRunId }: BrowserUatPanelProps) {
  const [execution, setExecution] = useState<BrowserUatExecution | null>(null);
  const [results, setResults] = useState<BrowserUatPageResult[]>([]);
  const [neverStarted, setNeverStarted] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // -----------------------------------------------------------------------
  // Fetch status
  // -----------------------------------------------------------------------

  const fetchStatus = useCallback(async () => {
    try {
      const value = await browserUatApi.status(analysisRunId);
      setExecution(value);
      setNeverStarted(false);
      setError(null);
      return value;
    } catch (reason) {
      if (
        reason instanceof ApiError &&
        reason.status === 404 &&
        reason.code === "BROWSER_UAT_TIER0_NOT_FOUND"
      ) {
        setNeverStarted(true);
        setExecution(null);
        return null;
      }
      if (reason instanceof ApiError && reason.status === 404) {
        // Analysis run not found — genuine error
        setError("This analysis run was not found.");
        return null;
      }
      throw reason;
    }
  }, [analysisRunId]);

  // -----------------------------------------------------------------------
  // Fetch results (once terminal)
  // -----------------------------------------------------------------------

  const fetchResults = useCallback(async () => {
    try {
      const data = await browserUatApi.results(analysisRunId);
      setResults(data.page_results);
    } catch {
      // Results not available yet — not an error state
      setResults([]);
    }
  }, [analysisRunId]);

  // -----------------------------------------------------------------------
  // Polling
  // -----------------------------------------------------------------------

  const stopPolling = useCallback(() => {
    if (pollRef.current !== null) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const startPolling = useCallback(() => {
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const value = await fetchStatus();
        if (
          value &&
          TERMINAL_STATUSES.has(value.status)
        ) {
          stopPolling();
          void fetchResults();
        }
      } catch {
        // Transient failure — keep polling
      }
    }, POLL_INTERVAL_MS);
  }, [fetchStatus, fetchResults, stopPolling]);

  // -----------------------------------------------------------------------
  // Initial load
  // -----------------------------------------------------------------------

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const value = await fetchStatus();
        if (cancelled) return;
        if (value && TERMINAL_STATUSES.has(value.status)) {
          void fetchResults();
        } else if (value) {
          startPolling();
        }
      } catch {
        if (!cancelled) setError("Could not check browser UAT status.");
      }
    }
    void load();
    return () => {
      cancelled = true;
      stopPolling();
    };
  }, [fetchStatus, fetchResults, startPolling, stopPolling]);

  // -----------------------------------------------------------------------
  // Trigger a check
  // -----------------------------------------------------------------------

  async function handleStart() {
    setStarting(true);
    setError(null);
    try {
      const idempotencyKey = crypto.randomUUID();
      const value = await browserUatApi.start(analysisRunId, idempotencyKey);
      setExecution(value);
      setNeverStarted(false);
      startPolling();
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 409) {
        setError("A real browser check is already running for this website.");
        // Refresh status to show the in-flight execution
        void fetchStatus();
      } else {
        setError(
          reason instanceof Error
            ? reason.message
            : "Could not start browser check.",
        );
      }
    } finally {
      setStarting(false);
    }
  }

  // -----------------------------------------------------------------------
  // Derived state
  // -----------------------------------------------------------------------

  const isInFlight =
    execution !== null &&
    (execution.status === "pending" || execution.status === "running");

  const isTerminal =
    execution !== null && TERMINAL_STATUSES.has(execution.status);

  const canRetrigger =
    !isInFlight &&
    (neverStarted ||
      (isTerminal &&
        (execution.status === "failed" ||
          execution.status === "cancelled" ||
          execution.status === "unavailable")));

  const showResults =
    isTerminal &&
    (execution.status === "completed" || execution.status === "partial");

  // Group results by browser+platform
  const grouped = results.reduce<Record<string, BrowserUatPageResult[]>>(
    (acc, result) => {
      const key = groupKey(result);
      if (!acc[key]) acc[key] = [];
      acc[key].push(result);
      return acc;
    },
    {},
  );

  // Sort groups: automated first, manual last
  const sortedGroups = Object.entries(grouped).sort(([, a], [, b]) => {
    const aManual = a.some(isManualLane);
    const bManual = b.some(isManualLane);
    if (aManual && !bManual) return 1;
    if (!aManual && bManual) return -1;
    return 0;
  });

  // -----------------------------------------------------------------------
  // Render
  // -----------------------------------------------------------------------

  return (
    <section className="rounded-xl border border-z-border bg-z-surface p-6">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h2 className="text-lg font-bold text-z-ink">
            Real browser verification
          </h2>
          <p className="text-sm text-z-ink-secondary mt-1">
            Tests your site on real Chrome, Edge, and Safari across Windows,
            macOS, iOS, and Android devices.
          </p>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          {execution && (
            <StatusBadge status={execution.status} />
          )}
          {(canRetrigger || neverStarted) && (
            <button
              aria-label="Run real browser check"
              className="rounded-lg bg-z-accent px-4 py-2 text-sm font-semibold text-white hover:bg-z-accent-hover disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              disabled={starting || isInFlight}
              onClick={() => void handleStart()}
              type="button"
            >
              {starting
                ? "Starting…"
                : neverStarted
                  ? "Run real browser check"
                  : "Rerun browser check"}
            </button>
          )}
        </div>
      </div>

      {error && (
        <p className="mt-3 text-sm text-z-danger" role="alert">
          {error}
        </p>
      )}

      {isInFlight && (
        <div className="mt-4 flex items-center gap-3 rounded-lg bg-z-info-subtle border border-z-info/20 px-4 py-3">
          <div className="h-4 w-4 rounded-full border-2 border-z-info border-t-transparent animate-spin" />
          <div>
            <p className="text-sm font-medium text-z-info">
              Real browser check in progress
            </p>
            <p className="text-xs text-z-ink-muted mt-0.5">
              Running on real browsers via GitHub Actions — this typically takes
              2–5 minutes. Polling every {POLL_INTERVAL_MS / 1000} seconds.
            </p>
          </div>
        </div>
      )}

      {neverStarted && !error && (
        <div className="mt-4 rounded-lg border border-dashed border-z-border bg-z-surface-muted px-6 py-8 text-center">
          <p className="text-sm text-z-ink-secondary">
            No real browser check has been run for this analysis yet.
          </p>
          <p className="text-xs text-z-ink-muted mt-1">
            Click the button above to test your site on real Chrome, Edge, and
            Safari browsers.
          </p>
        </div>
      )}

      {showResults && results.length === 0 && (
        <p className="mt-4 text-sm text-z-ink-muted">
          The check completed but no page-level results are available.
        </p>
      )}

      {showResults && sortedGroups.length > 0 && (
        <div className="mt-5 space-y-5">
          {execution.status === "partial" && (
            <div className="rounded-lg bg-z-warning-subtle border border-z-warning/20 px-4 py-3">
              <p className="text-sm font-medium text-z-warning">
                Some structural issues were detected on real devices
              </p>
              <p className="text-xs text-z-ink-muted mt-0.5">
                These findings come from real browsers, not emulated engines.
                Review the per-viewport details below.
              </p>
            </div>
          )}
          {sortedGroups.map(([key, groupResults]) => (
            <ResultsGroup
              key={key}
              label={groupLabel(groupResults[0])}
              manual={groupResults.some(isManualLane)}
              results={groupResults}
            />
          ))}
        </div>
      )}

      {isTerminal &&
        execution.status !== "completed" &&
        execution.status !== "partial" && (
          <div className="mt-4 rounded-lg bg-z-danger-subtle border border-z-danger/20 px-4 py-3">
            <p className="text-sm font-medium text-z-danger">
              {execution.status === "failed"
                ? "The browser check failed"
                : execution.status === "cancelled"
                  ? "The browser check was cancelled"
                  : "Real browser verification is unavailable"}
            </p>
            <p className="text-xs text-z-ink-muted mt-0.5">
              {execution.status === "failed"
                ? "The underlying CI job did not complete. You can try again."
                : execution.status === "cancelled"
                  ? "This check was cancelled before it finished."
                  : "Real browser checks are not available for this analysis run."}
            </p>
          </div>
        )}

      {execution && (
        <dl className="mt-4 flex flex-wrap gap-x-6 gap-y-1 text-xs text-z-ink-muted">
          <div>
            <dt className="inline font-medium">Attempt:</dt>{" "}
            <dd className="inline">{execution.attempt}</dd>
          </div>
          {execution.requested_at && (
            <div>
              <dt className="inline font-medium">Requested:</dt>{" "}
              <dd className="inline">
                {new Date(execution.requested_at).toLocaleString()}
              </dd>
            </div>
          )}
          {execution.completed_at && (
            <div>
              <dt className="inline font-medium">Completed:</dt>{" "}
              <dd className="inline">
                {new Date(execution.completed_at).toLocaleString()}
              </dd>
            </div>
          )}
        </dl>
      )}
    </section>
  );
}
