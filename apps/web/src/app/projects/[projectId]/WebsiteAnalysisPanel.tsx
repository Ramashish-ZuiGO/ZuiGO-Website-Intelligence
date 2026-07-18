"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { apiRequest } from "@/lib/api";
import type { AnalysisRun } from "@/lib/types";

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

  async function startAnalysis() {
    setStarting(true);
    setError(null);
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
          {starting ? "Queueing…" : isActive(latestRun) ? "Analysis in progress" : "Start analysis"}
        </button>
      </div>

      {latestRun && (
        <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-200" aria-label={`Analysis progress ${latestRun.progress_percent}%`}>
          <div className="h-full bg-emerald-600 transition-all" style={{ width: `${latestRun.progress_percent}%` }} />
        </div>
      )}
      {error && <p className="mt-3 text-sm text-red-700" role="alert">{error}</p>}

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
