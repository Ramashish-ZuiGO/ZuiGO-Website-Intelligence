"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { SafeStructuredValue } from "@/components/agents/SafeStructuredValue";
import type {
  DeliveredReport,
  PaginatedReports,
  WorkflowProgress,
} from "@/components/reports/types";
import { reportDeliveryApi } from "@/lib/report-delivery-api";

const PAGE_SIZE = 5;
const TERMINAL_STATUSES = [
  "completed",
  "partial",
  "failed",
  "cancelled",
  "unavailable",
];

interface ReportDeliveryPanelProps {
  projectId?: string;
  websiteId: string;
  analysisRunId?: string;
  workflowExecutionId?: string;
  compact?: boolean;
  showStartAction?: boolean;
}

function executionKey(projectId: string, websiteId: string): string {
  return `analysis-journey:${projectId}:${websiteId}`;
}

function createKey(prefix: string): string {
  return `${prefix}-${new Date().toISOString()}-${crypto.randomUUID()}`;
}

function statusLabel(status: string): string {
  return status.replaceAll("_", " ");
}

function Coverage({
  numerator,
  denominator,
  percentage,
}: {
  numerator: number;
  denominator: number;
  percentage: number | null;
}) {
  return (
    <p className="text-sm">
      Evidence coverage: {numerator}/{denominator}
      {" · "}
      {percentage === null ? "Unavailable" : `${percentage.toFixed(1)}%`}
    </p>
  );
}

function ReportViewer({ report }: { report: DeliveredReport }) {
  return (
    <article
      aria-labelledby={`delivered-report-${report.report_id}`}
      className="mt-6 rounded-2xl border border-slate-300 bg-white p-5"
    >
      <header>
        <p className="text-xs font-bold uppercase tracking-wide text-slate-500">
          Immutable report snapshot · {statusLabel(report.status)}
        </p>
        <h3 className="mt-2 text-xl font-bold" id={`delivered-report-${report.report_id}`}>
          Final analysis report
        </h3>
        <p className="mt-1 break-all font-mono text-xs text-slate-500">
          Report ID: {report.report_id}
        </p>
        <div className="mt-3">
          <Coverage
            denominator={report.evidence_coverage_denominator}
            numerator={report.evidence_coverage_numerator}
            percentage={report.evidence_coverage_percentage}
          />
          <p className="text-sm">
            Confidence:{" "}
            {report.confidence_percent === null
              ? "Unavailable"
              : `${report.confidence_percent}%`}
          </p>
        </div>
      </header>

      {report.unavailable_sections.length > 0 && (
        <div className="mt-4 rounded-lg border border-amber-300 bg-amber-50 p-3" role="note">
          <p className="font-semibold">Partial evidence</p>
          <p className="mt-1 text-sm">
            Unavailable sections: {report.unavailable_sections.join(", ")}. These are
            not represented as successful or issue-free.
          </p>
        </div>
      )}

      <nav aria-label="Final report sections" className="mt-5 rounded-lg bg-slate-50 p-3">
        <h4 className="font-semibold">Report sections</h4>
        <ol className="mt-2 grid gap-1 text-sm sm:grid-cols-2">
          {report.sections.map((section) => (
            <li key={section.section_id}>
              <a
                className="underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-600"
                href={`#report-${report.report_id}-${section.section_key}`}
              >
                {section.position}. {section.title}
              </a>
            </li>
          ))}
        </ol>
      </nav>

      <section aria-labelledby={`exports-${report.report_id}`} className="mt-5">
        <h4 className="font-semibold" id={`exports-${report.report_id}`}>
          Export report
        </h4>
        <div className="mt-2 flex flex-wrap gap-2">
          {report.artifacts.map((artifact) => (
            <a
              className="rounded-lg border border-slate-400 px-3 py-2 text-sm font-semibold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-600"
              href={reportDeliveryApi.downloadUrl(report.report_id, artifact.format)}
              key={artifact.artifact_id}
            >
              Download {artifact.format.toUpperCase()}{" "}
              <span className="sr-only">
                ({artifact.size_bytes} bytes, checksum {artifact.checksum_sha256})
              </span>
            </a>
          ))}
        </div>
      </section>

      <div className="mt-5 grid gap-4">
        {report.sections.map((section) => (
          <section
            aria-labelledby={`report-${report.report_id}-${section.section_key}-heading`}
            className="scroll-mt-6 rounded-xl border border-slate-200 p-4"
            id={`report-${report.report_id}-${section.section_key}`}
            key={section.section_id}
          >
            <div className="flex flex-wrap items-start justify-between gap-2">
              <h4
                className="font-bold"
                id={`report-${report.report_id}-${section.section_key}-heading`}
              >
                {section.position}. {section.title}
              </h4>
              <span className="rounded-full border px-2 py-1 text-xs font-bold uppercase">
                {statusLabel(section.status)}
              </span>
            </div>
            {section.unavailable_reason && (
              <p className="mt-2 text-sm text-amber-800" role="note">
                {section.unavailable_reason}
              </p>
            )}
            <div className="mt-3">
              <SafeStructuredValue value={section.content} />
            </div>
            <details className="mt-3">
              <summary className="cursor-pointer text-sm font-semibold">
                Evidence references ({section.evidence_references.length})
              </summary>
              {section.evidence_references.length > 0 ? (
                <div className="mt-2">
                  <SafeStructuredValue value={section.evidence_references} />
                </div>
              ) : (
                <p className="mt-2 text-sm text-slate-500">
                  No evidence reference was available for this section.
                </p>
              )}
            </details>
          </section>
        ))}
      </div>
    </article>
  );
}

export function ReportDeliveryPanel({
  projectId,
  websiteId,
  analysisRunId,
  workflowExecutionId,
  compact = false,
  showStartAction = true,
}: ReportDeliveryPanelProps) {
  const [reports, setReports] = useState<PaginatedReports>({
    items: [],
    total: 0,
    limit: PAGE_SIZE,
    offset: 0,
  });
  const [selected, setSelected] = useState<DeliveredReport | null>(null);
  const [progress, setProgress] = useState<WorkflowProgress | null>(null);
  const [executionId, setExecutionId] = useState(() => {
    if (workflowExecutionId) return workflowExecutionId;
    if (typeof window === "undefined" || !projectId) return "";
    return window.localStorage.getItem(executionKey(projectId, websiteId)) ?? "";
  });
  const [analysisId, setAnalysisId] = useState(analysisRunId ?? "");
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [acting, setActing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const resolvedAnalysisId = analysisRunId ?? analysisId;
  const resolvedExecutionId = workflowExecutionId ?? executionId;

  const loadReports = useCallback(async () => {
    setLoading(true);
    try {
      const result = resolvedAnalysisId
        ? await reportDeliveryApi.forRun(resolvedAnalysisId, PAGE_SIZE, offset)
        : await reportDeliveryApi.history(websiteId, PAGE_SIZE, offset);
      setReports(result);
      setSelected((current) => current ?? result.items[0] ?? null);
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Unable to load report history.",
      );
    } finally {
      setLoading(false);
    }
  }, [offset, resolvedAnalysisId, websiteId]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadReports(), 0);
    return () => window.clearTimeout(timer);
  }, [loadReports]);

  const loadProgress = useCallback(async () => {
    if (!resolvedExecutionId) return;
    try {
      const current = await reportDeliveryApi.progress(resolvedExecutionId);
      setProgress(current);
      if (current.analysis_run_id) setAnalysisId(current.analysis_run_id);
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Unable to load workflow progress.",
      );
    }
  }, [resolvedExecutionId]);

  useEffect(() => {
    if (!resolvedExecutionId) return;
    const initialTimer = window.setTimeout(() => void loadProgress(), 0);
    const timer = window.setInterval(() => void loadProgress(), 2000);
    return () => {
      window.clearTimeout(initialTimer);
      window.clearInterval(timer);
    };
  }, [loadProgress, resolvedExecutionId]);

  useEffect(() => {
    if (!progress || !TERMINAL_STATUSES.includes(progress.status)) return;
    const timer = window.setTimeout(() => void loadReports(), 0);
    return () => window.clearTimeout(timer);
  }, [loadReports, progress]);

  async function startAnalysis() {
    if (!projectId) return;
    setActing(true);
    setError(null);
    setNotice(null);
    try {
      const started = await reportDeliveryApi.startAnalysis(
        projectId,
        websiteId,
        createKey("full-analysis"),
      );
      setExecutionId(started.workflow_execution_id);
      setAnalysisId(started.analysis_run_id);
      window.localStorage.setItem(
        executionKey(projectId, websiteId),
        started.workflow_execution_id,
      );
      setNotice(
        started.reused
          ? "The existing idempotent analysis journey was reopened."
          : "Full analysis accepted. Evidence collection will run before the agent workflow.",
      );
      await loadProgress();
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Unable to start the full analysis.",
      );
    } finally {
      setActing(false);
    }
  }

  async function generateReport() {
    if (!resolvedAnalysisId) return;
    setActing(true);
    setError(null);
    setNotice(null);
    try {
      const report = await reportDeliveryApi.generate(
        resolvedAnalysisId,
        createKey("report"),
        resolvedExecutionId || undefined,
      );
      setSelected(report);
      setNotice(
        report.status === "completed"
          ? "Immutable report and all three exports were generated."
          : "A partial immutable report was generated with unavailable evidence identified.",
      );
      await loadReports();
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Unable to generate the report.",
      );
    } finally {
      setActing(false);
    }
  }

  const progressDescription = useMemo(() => {
    if (!progress) return "Workflow progress is unavailable.";
    return `${progress.progress_percentage.toFixed(0)} percent complete. Current stage ${statusLabel(progress.current_stage)}.`;
  }, [progress]);
  const canGenerate =
    Boolean(resolvedAnalysisId) &&
    (!progress || TERMINAL_STATUSES.includes(progress.status));

  return (
    <section
      aria-labelledby={`report-delivery-${websiteId}`}
      className={`${compact ? "mt-6" : "mt-8"} rounded-2xl border border-slate-200 bg-white p-5`}
    >
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-bold uppercase tracking-wide text-slate-500">
            End-to-end delivery
          </p>
          <h2 className="mt-1 text-xl font-bold" id={`report-delivery-${websiteId}`}>
            Analysis progress and final reports
          </h2>
          <p className="mt-1 text-sm text-slate-600">
            Persisted evidence remains the source of truth for every report section.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {projectId && showStartAction && (
            <button
              className="rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-600"
              disabled={acting || Boolean(progress && !TERMINAL_STATUSES.includes(progress.status))}
              onClick={() => void startAnalysis()}
              type="button"
            >
              {acting ? "Starting…" : "Start full analysis"}
            </button>
          )}
          <button
            className="rounded-lg border border-slate-400 px-4 py-2 text-sm font-semibold disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-600"
            disabled={acting || !canGenerate}
            onClick={() => void generateReport()}
            type="button"
          >
            Generate immutable report
          </button>
        </div>
      </header>

      <div aria-live="polite" className="mt-4" role="status">
        {progress ? (
          <>
            <div
              aria-label={progressDescription}
              aria-valuemax={100}
              aria-valuemin={0}
              aria-valuenow={progress.progress_percentage}
              className="h-3 overflow-hidden rounded-full bg-slate-200"
              role="progressbar"
            >
              <div
                className="h-full bg-blue-700 transition-[width]"
                style={{ width: `${progress.progress_percentage}%` }}
              />
            </div>
            <p className="mt-2 text-sm font-semibold">
              {statusLabel(progress.status)} · {progressDescription}
            </p>
            <p className="mt-1 text-sm">
              Completed agents: {progress.completed_agent_ids.join(", ") || "None yet"}.
              Partial: {progress.partial_agent_ids.join(", ") || "None"}.
              Pending: {progress.pending_agent_ids.join(", ") || "None"}.
            </p>
            <Coverage
              denominator={progress.evidence_coverage.denominator}
              numerator={progress.evidence_coverage.numerator}
              percentage={progress.evidence_coverage.percentage}
            />
            <p className="text-sm">
              Attempt {progress.attempt} · elapsed {progress.elapsed_seconds.toFixed(1)}s ·
              resume {progress.resume_available ? "available" : "unavailable"} · retry{" "}
              {progress.retry_available ? "available" : "unavailable"}
            </p>
            {(progress.unavailable_tools.length > 0 ||
              progress.unavailable_providers.length > 0) && (
              <p className="mt-1 text-sm text-amber-800">
                Unavailable tools/providers:{" "}
                {[...progress.unavailable_tools, ...progress.unavailable_providers].join(", ")}
              </p>
            )}
            {progress.safe_error_summaries.map((item) => (
              <p className="mt-1 text-sm text-red-700" key={`${item.code}-${item.message}`}>
                {item.code}: {item.message}
              </p>
            ))}
          </>
        ) : (
          <p className="text-sm text-slate-600">
            No active workflow is retained in this browser. Report history remains available
            below.
          </p>
        )}
      </div>

      {notice && <p className="mt-3 text-sm text-emerald-700" role="status">{notice}</p>}
      {error && <p className="mt-3 text-sm text-red-700" role="alert">{error}</p>}

      <section aria-labelledby={`report-history-${websiteId}`} className="mt-6">
        <h3 className="font-bold" id={`report-history-${websiteId}`}>
          Report history
        </h3>
        {loading ? (
          <p className="mt-2 text-sm text-slate-600" role="status">
            Loading immutable report history…
          </p>
        ) : reports.items.length === 0 ? (
          <p className="mt-2 text-sm text-slate-600">
            No report has been generated. This does not mean that no issues exist.
          </p>
        ) : (
          <ul className="mt-3 grid gap-2">
            {reports.items.map((report) => (
              <li className="rounded-lg border border-slate-200 p-3 text-sm" key={report.report_id}>
                <button
                  className="w-full text-left focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-600"
                  onClick={() => setSelected(report)}
                  type="button"
                >
                  <span className="font-semibold capitalize">{statusLabel(report.status)}</span>
                  {" · "}
                  {new Date(report.created_at).toLocaleString()}
                  {" · "}
                  coverage {report.evidence_coverage_numerator}/
                  {report.evidence_coverage_denominator}
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="mt-3 flex gap-2">
          <button
            className="rounded border px-3 py-1 text-sm disabled:opacity-50"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            type="button"
          >
            Previous
          </button>
          <button
            className="rounded border px-3 py-1 text-sm disabled:opacity-50"
            disabled={offset + PAGE_SIZE >= reports.total}
            onClick={() => setOffset(offset + PAGE_SIZE)}
            type="button"
          >
            Next
          </button>
        </div>
      </section>

      {selected && <ReportViewer report={selected} />}
    </section>
  );
}
