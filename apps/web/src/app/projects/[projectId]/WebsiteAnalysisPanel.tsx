"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { apiRequest } from "@/lib/api";
import type { AnalysisResults, AnalysisRun } from "@/lib/types";

interface WebsiteAnalysisPanelProps {
  websiteId: string;
}

function isActive(run: AnalysisRun | undefined): boolean {
  return run?.status === "queued" || run?.status === "running";
}

export function WebsiteAnalysisPanel({ websiteId }: WebsiteAnalysisPanelProps) {
  const [history, setHistory] = useState<AnalysisRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
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
    try {
      const analysisRun = await apiRequest<AnalysisRun>(
        `/api/v1/websites/${websiteId}/analysis-runs`,
        { method: "POST" },
      );
      setHistory((current) => [analysisRun, ...current]);
    } catch (requestError) {
      setError(
        requestError instanceof Error ? requestError.message : "Unable to start analysis.",
      );
    } finally {
      setStarting(false);
    }
  }

  const statusLabel = useMemo(() => {
    if (!latestRun) return "Not started";
    return latestRun.status.charAt(0).toUpperCase() + latestRun.status.slice(1);
  }, [latestRun]);

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
        </div>
        <button
          className="rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
          disabled={starting || isActive(latestRun)}
          onClick={() => void startAnalysis()}
        >
          {starting
            ? "Queueing…"
            : isActive(latestRun)
              ? "Analysis in progress"
              : latestRun
                ? "Start new analysis"
                : "Start analysis"}
        </button>
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
            {(["performance_score", "accessibility_score", "best_practices_score", "seo_score"] as const).map((key) => (
              <div key={key}><dt className="capitalize text-slate-500">{key.replaceAll("_", " ")}</dt><dd className="font-medium">{results.lighthouse_metrics[key] ?? "Unavailable"}</dd></div>
            ))}
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
            {history.map((run) => (
              <li className="rounded-lg bg-slate-50 p-3 text-sm" key={run.id}>
                <span className="font-semibold capitalize">{run.status}</span>
                <span className="text-slate-500"> · {run.progress_percent}% · {new Date(run.created_at).toLocaleString()}</span>
              </li>
            ))}
          </ul>
        )}
      </details>
      <button className="mt-3 text-xs font-semibold text-slate-600" onClick={() => void loadHistory().catch((requestError: unknown) => setError(requestError instanceof Error ? requestError.message : "Unable to refresh analysis history."))}>Refresh analysis history</button>
    </section>
  );
}
