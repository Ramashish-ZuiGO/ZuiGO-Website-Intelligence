"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { apiRequest } from "@/lib/api";
import type { AnalysisResults, AnalysisRun } from "@/lib/types";

import { MetricInfoButton } from "@/components/metrics/MetricInfoButton";
import { PerformanceIntelligence } from '@/components/performance/PerformanceIntelligence';
import { AccessibilityIntelligence, AccessibilityData } from '@/components/accessibility/AccessibilityIntelligence';
import { ScoreValue } from "@/components/metrics/ScoreValue";
import { SiteDiagnosticsPanel } from "@/components/diagnostics/SiteDiagnosticsPanel";
import { AgentExecutionPanel } from "@/components/agents/AgentExecutionPanel";
import { ScoringIntelligencePanel } from "@/components/scoring/ScoringIntelligencePanel";
import { ReportDeliveryPanel } from "@/components/reports/ReportDeliveryPanel";
import { SectionErrorBoundary } from "@/components/SectionErrorBoundary";
import { reportDeliveryApi } from "@/lib/report-delivery-api";

interface WebsiteAnalysisPanelProps {
  projectId?: string;
  websiteId: string;
}

function isActive(run: AnalysisRun | undefined): boolean {
  return run?.status === "queued" || run?.status === "running";
}

function scoreChangeFromPrevious(history: AnalysisRun[], index: number): number | null {
  const current = history[index];
  const previous = history
    .slice(index + 1)
    .find(
      (candidate) =>
        candidate.status === "completed" &&
        candidate.result_summary?.overall_score != null,
    );
  const currentScore = current.result_summary?.overall_score;
  const previousScore = previous?.result_summary?.overall_score;
  return current.status === "completed" &&
    currentScore != null &&
    previousScore != null
    ? currentScore - previousScore
    : null;
}

function scoreChangeLabel(history: AnalysisRun[], index: number): string {
  const change = scoreChangeFromPrevious(history, index);
  return change === null ? "" : ` · ${change > 0 ? "+" : ""}${change} from previous`;
}

export function WebsiteAnalysisPanel({
  projectId,
  websiteId,
}: WebsiteAnalysisPanelProps) {
  const [history, setHistory] = useState<AnalysisRun[]>([]);
  const [performanceData, setPerformanceData] = useState<{snapshots: Record<string, unknown>[], disagreement?: boolean, explanation?: string}>({snapshots: []});
  const [accessibilityData, setAccessibilityData] = useState<AccessibilityData | null>(null);
  useEffect(() => {
    if (websiteId) {
      apiRequest<{snapshots?: Record<string, unknown>[], disagreement?: boolean, explanation?: string}>(`/api/v1/websites/${websiteId}/performance/comparison`)
        .then((res) => setPerformanceData({
          snapshots: (res.snapshots || []) as Record<string, unknown>[],
          disagreement: res.disagreement,
          explanation: res.explanation
        }))
        .catch(console.error);

      apiRequest<AccessibilityData>(`/api/v1/websites/${websiteId}/accessibility`)
        .then((res) => setAccessibilityData(res))
        .catch(console.error);
    }
  }, [websiteId]);

  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [workflowExecutionId, setWorkflowExecutionId] = useState<string>();
  const [selectedComparisonRuns, setSelectedComparisonRuns] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<AnalysisResults | null>(null);
  const latestRun = history[0];

  const loadHistory = useCallback(async () => {
    const runs = await apiRequest<AnalysisRun[]>(
      `/api/v1/websites/${websiteId}/analysis-runs`,
    );
    setHistory(runs);
  }, [websiteId]);

  useEffect(() => {
    let cancelled = false;
    void apiRequest<AnalysisRun[]>(`/api/v1/websites/${websiteId}/analysis-runs`)
      .then((runs) => {
        if (!cancelled) setHistory(runs);
      })
      .catch((requestError: unknown) => {
        if (!cancelled) {
          setError(
            requestError instanceof Error
              ? requestError.message
              : "Unable to load analysis history.",
          );
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [websiteId]);

  useEffect(() => {
    if (!isActive(latestRun)) return;

    const timer = window.setInterval(() => {
      void apiRequest<AnalysisRun>(`/api/v1/analysis-runs/${latestRun.id}`)
        .then((updatedRun) => {
          setHistory((current) => [
            updatedRun,
            ...current.filter((run) => run.id !== updatedRun.id),
          ]);
        })
        .catch((requestError: unknown) => {
          setError(
            requestError instanceof Error
              ? requestError.message
              : "Unable to refresh analysis status.",
          );
        });
    }, 1000);

    return () => window.clearInterval(timer);
  }, [latestRun]);

  useEffect(() => {
    if (latestRun?.status !== "completed") {
      return;
    }
    let cancelled = false;
    void apiRequest<AnalysisResults>(`/api/v1/analysis-runs/${latestRun.id}/results`)
      .then((loadedResults) => {
        if (!cancelled) setResults(loadedResults);
      })
      .catch((requestError: unknown) => {
        if (!cancelled) {
          setError(
            requestError instanceof Error ? requestError.message : "Unable to load results.",
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [latestRun]);

  async function startAnalysis() {
    setStarting(true);
    setError(null);
    setResults(null);
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 30_000);
    try {
      const signal = controller.signal;
      const analysisRun = projectId
        ? await reportDeliveryApi
            .startAnalysis(
              projectId,
              websiteId,
              `full-analysis-${new Date().toISOString()}-${crypto.randomUUID()}`,
            )
            .then(async (journey) => {
              setWorkflowExecutionId(journey.workflow_execution_id);
              window.localStorage.setItem(
                `analysis-journey:${projectId}:${websiteId}`,
                journey.workflow_execution_id,
              );
              return apiRequest<AnalysisRun>(
                `/api/v1/analysis-runs/${journey.analysis_run_id}`,
                { signal },
              );
            })
        : await apiRequest<AnalysisRun>(
            `/api/v1/websites/${websiteId}/analysis-runs`,
            { method: "POST", signal },
          );
      setHistory((current) => [analysisRun, ...current]);
    } catch (requestError) {
      if (requestError instanceof DOMException && requestError.name === "AbortError") {
        setError("Starting the analysis timed out. The server may be busy — try again.");
      } else {
        setError(
          requestError instanceof Error ? requestError.message : "Unable to start analysis.",
        );
      }
    } finally {
      window.clearTimeout(timeout);
      setStarting(false);
    }
  }

  const statusLabel = useMemo(() => {
    if (!latestRun) return "Not started";
    const s = latestRun.status ?? "unknown";
    return s.charAt(0).toUpperCase() + s.slice(1);
  }, [latestRun]);
  const comparisonHref = useMemo(() => {
    if (selectedComparisonRuns.length !== 2) return null;
    const selected = history
      .filter((run) => selectedComparisonRuns.includes(run.id))
      .sort(
        (left, right) =>
          new Date(right.created_at).getTime() - new Date(left.created_at).getTime(),
      );
    return selected.length === 2
      ? `/analysis-runs/${selected[0].id}/compare/${selected[1].id}`
      : null;
  }, [history, selectedComparisonRuns]);

  if (loading) {
    return <p className="mt-4 text-sm text-slate-600">Loading analysis history…</p>;
  }

  return (
    <section className="mt-5 border-t border-slate-200 pt-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-slate-700">Latest analysis</p>
          <p className="mt-1 text-sm text-slate-600">
            {statusLabel}
            {latestRun ? ` · ${latestRun.progress_percent}%` : ""}
          </p>
          {latestRun?.current_step && (
            <p className="mt-1 text-sm text-slate-500">{latestRun.current_step}</p>
          )}
          {latestRun?.status === "failed" && latestRun.error_message && (
            <p className="mt-1 text-sm text-red-700">{latestRun.error_message}</p>
          )}
          {latestRun?.result_summary?.overall_score != null && (
            <p className="mt-1 text-lg font-bold text-slate-950 flex items-center gap-2">
              Overall score: <ScoreValue metricId="overall_score" value={latestRun.result_summary.overall_score} />
              <MetricInfoButton metricId="overall_score" />
            </p>
          )}
        </div>
        <form
          aria-label="Start a complete website analysis"
          onSubmit={(event) => {
            event.preventDefault();
            void startAnalysis();
          }}
        >
        <button
          className="rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
          disabled={starting || isActive(latestRun)}
          type="submit"
        >
          {starting
            ? "Queueing…"
            : isActive(latestRun)
              ? "Analysis in progress"
              : latestRun
                ? "Start new analysis"
                : "Start analysis"}
        </button>
        </form>
      </div>

      {latestRun && (
        <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-200" aria-label={`Analysis progress ${latestRun.progress_percent}%`}>
          <div className="h-full bg-emerald-600 transition-all" style={{ width: `${latestRun.progress_percent}%` }} />
        </div>
      )}
      {error && <p className="mt-3 text-sm text-red-700" role="alert">{error}</p>}

      {results && (
        <section className="mt-5 rounded-lg bg-slate-50 p-4">
          <h3 className="font-semibold text-slate-900">Verified homepage results</h3>
          <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-2">
            <div><dt className="text-slate-500">Final URL</dt><dd className="break-all font-medium">{results.result.final_url}</dd></div>
            <div><dt className="text-slate-500">HTTP status</dt><dd className="font-medium">{results.result.http_status_code ?? "Unavailable"}</dd></div>
            <div><dt className="text-slate-500">Page title</dt><dd className="font-medium">{results.result.page_title || "Missing"}</dd></div>
            {(["performance_score", "accessibility_score", "best_practices_score", "seo_score"] as const).map((key) => {
              const value = results.lighthouse_metrics[key] as number | undefined;
              return <div key={key}><dt className="capitalize text-slate-500 flex items-center gap-1">{key.replaceAll("_", " ")} <MetricInfoButton metricId={key} /></dt><dd className="font-medium"><ScoreValue metricId={key} value={value ?? null} /></dd></div>;
            })}
            <div><dt className="text-slate-500">Total findings</dt><dd className="font-medium">{results.findings.length}</dd></div>
          </dl>
          <h4 className="mt-5 font-semibold">Findings</h4>
          {results.findings.length === 0 ? (
            <p className="mt-2 text-sm text-slate-600">No findings were generated from the measured thresholds.</p>
          ) : (
            <ul className="mt-3 grid gap-3">
              {results.findings.map((finding) => (
                <li className="rounded-lg border border-slate-200 bg-white p-3 text-sm" key={finding.id}>
                  <p className="font-semibold"><span className="uppercase text-slate-500">{finding.severity}</span> · {finding.title}</p>
                  <p className="mt-1 text-slate-600">{finding.category} · {JSON.stringify(finding.evidence)}</p>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      <details className="mt-4">
        <summary className="cursor-pointer text-sm font-semibold text-slate-700">Analysis history ({history.length})</summary>
        {history.length === 0 ? (
          <p className="mt-2 text-sm text-slate-500">No analysis runs yet.</p>
        ) : (
          <ul className="mt-3 grid gap-2">
            <li className="text-sm text-slate-600">
              Select any two completed analyses of this website to compare.
            </li>
            {history.map((run, index) => (
              <li className="rounded-lg bg-slate-50 p-3 text-sm" key={run.id}>
                <label className="mr-3 inline-flex items-center gap-2">
                  <input
                    aria-label={`Select analysis from ${new Date(run.created_at).toLocaleString()} for comparison`}
                    checked={selectedComparisonRuns.includes(run.id)}
                    disabled={
                      run.status !== "completed" ||
                      (!selectedComparisonRuns.includes(run.id) &&
                        selectedComparisonRuns.length >= 2)
                    }
                    onChange={(event) =>
                      setSelectedComparisonRuns((current) =>
                        event.target.checked
                          ? [...current, run.id]
                          : current.filter((id) => id !== run.id),
                      )
                    }
                    type="checkbox"
                  />
                  <span className="sr-only">Compare</span>
                </label>
                <span className="font-semibold capitalize">{run.status}</span>
                <span className="text-slate-500"> · {run.progress_percent}% · {new Date(run.created_at).toLocaleString()}</span>
                {run.status === "completed" && (
                  <a
                    className="ml-3 inline-block font-semibold text-slate-900 underline"
                    href={`/analysis-runs/${run.id}`}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    View Analysis
                  </a>
                )}
                <span className="mt-1 block text-slate-600">
                  Overall score:{" "}
                  {run.result_summary?.overall_score == null
                    ? "Unavailable"
                    : `${run.result_summary.overall_score}/100`}
                  {scoreChangeLabel(history, index)}
                </span>
              </li>
            ))}
            {comparisonHref && (() => {
              const selected = history.filter((run) => selectedComparisonRuns.includes(run.id)).sort((left, right) => new Date(right.created_at).getTime() - new Date(left.created_at).getTime());
              return (
                <li>
                  <a
                    className="inline-block rounded-lg bg-slate-950 px-4 py-2 font-semibold text-white"
                    href={comparisonHref}
                  >
                    Compare Current ({new Date(selected[0].created_at).toLocaleDateString()}) vs Baseline ({new Date(selected[1].created_at).toLocaleDateString()})
                  </a>
                </li>
              );
            })()}
          </ul>
        )}
      </details>
      <SectionErrorBoundary sectionName="Performance Intelligence">
        <div className="mt-8">
          <PerformanceIntelligence
            data={performanceData.snapshots as unknown as { id: string; metric_id: string; evidence_type: string; raw_value: number; url_or_origin?: string; form_factor?: string; evidence_source?: string }[]}
            disagreement={performanceData.disagreement}
            explanation={performanceData.explanation}
          />
        </div>
      </SectionErrorBoundary>

      <SectionErrorBoundary sectionName="Accessibility Intelligence">
        <div className="mt-8">
          <AccessibilityIntelligence
            accessibilityData={accessibilityData}
          />
        </div>
      </SectionErrorBoundary>

      <SectionErrorBoundary sectionName="Site Diagnostics">
        <div className="mt-8">
          <SiteDiagnosticsPanel
            analysisRunId={latestRun?.status === "completed" ? latestRun.id : undefined}
            websiteId={websiteId}
          />
        </div>
      </SectionErrorBoundary>

      <SectionErrorBoundary sectionName="Agent Execution">
        <AgentExecutionPanel
          analysisRunId={latestRun?.status === "completed" ? latestRun.id : undefined}
          compact
          projectId={projectId}
          websiteId={websiteId}
        />
      </SectionErrorBoundary>
      <SectionErrorBoundary sectionName="Scoring Intelligence">
        <ScoringIntelligencePanel
          analysisRunId={latestRun?.status === "completed" ? latestRun.id : undefined}
          compact
          websiteId={websiteId}
        />
      </SectionErrorBoundary>
      <SectionErrorBoundary sectionName="Report Delivery">
        <ReportDeliveryPanel
          analysisRunId={latestRun?.id}
          compact
          projectId={projectId}
          showStartAction={false}
          websiteId={websiteId}
          workflowExecutionId={workflowExecutionId}
        />
      </SectionErrorBoundary>

      <button className="mt-3 text-xs font-semibold text-slate-600" onClick={() => void loadHistory().catch((requestError: unknown) => setError(requestError instanceof Error ? requestError.message : "Unable to refresh analysis history."))}>Refresh analysis history</button>
    </section>
  );
}
