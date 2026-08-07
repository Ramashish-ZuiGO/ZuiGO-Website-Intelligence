"use client";

import { useCallback, useEffect, useState } from "react";

import { apiRequest } from "@/lib/api";
import type {
  PageAnalysisActionRecommendation,
  PageAnalysisSummary,
  PageLevelScore,
  SiteCoverageDetail,
} from "@/lib/types";

import { ConceptInfoButton } from "@/components/metrics/ConceptInfoButton";
import { MetricInfoButton } from "@/components/metrics/MetricInfoButton";
import { ScoreValue } from "@/components/metrics/ScoreValue";
import { PercentageValue } from "@/components/metrics/PercentageValue";
import { SiteDiagnosticsReference } from "@/components/diagnostics/SiteDiagnosticsPanel";

interface PageAnalysisPanelProps {
  websiteId: string;
}

function AnalysisLevelBadge({ level }: { level: number }) {
  return (
    <span
      className={`inline-block rounded-full px-2 py-0.5 text-xs font-bold ${
        level === 1
          ? "bg-blue-100 text-blue-800"
          : "bg-purple-100 text-purple-800"
      }`}
    >
      L{level}
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    completed: "bg-emerald-100 text-emerald-800",
    partial: "bg-amber-100 text-amber-800",
    failed: "bg-red-100 text-red-800",
    skipped: "bg-slate-100 text-slate-600",
    pending: "bg-slate-100 text-slate-400",
    running: "bg-blue-100 text-blue-800",
  };
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-bold ${colors[status] ?? "bg-slate-100 text-slate-600"}`}>
      {status}
    </span>
  );
}



export function PageAnalysisPanel({ websiteId }: PageAnalysisPanelProps) {
  const [summary, setSummary] = useState<PageAnalysisSummary | null>(null);
  const [detail, setDetail] = useState<SiteCoverageDetail | null>(null);
  const [scores, setScores] = useState<PageLevelScore[]>([]);
  const [recommendations, setRecommendations] = useState<PageAnalysisActionRecommendation[]>([]);
  const [failedPages, setFailedPages] = useState<Array<Record<string, unknown>>>([]);
  const [activeTab, setActiveTab] = useState("coverage");
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [taskRunning, setTaskRunning] = useState(false);

  const load = useCallback(async () => {
    try {
      const [nextSummary, nextDetail, nextScores, nextRecs, nextFailed] = await Promise.all([
        apiRequest<PageAnalysisSummary>(
          `/api/v1/websites/${websiteId}/page-analysis/summary`
        ),
        apiRequest<SiteCoverageDetail>(
          `/api/v1/websites/${websiteId}/page-analysis/coverage`
        ),
        apiRequest<PageLevelScore[]>(
          `/api/v1/websites/${websiteId}/page-analysis/scores`
        ),
        apiRequest<PageAnalysisActionRecommendation[]>(
          `/api/v1/websites/${websiteId}/page-analysis/recommendations`
        ),
        apiRequest<Array<Record<string, unknown>>>(
          `/api/v1/websites/${websiteId}/page-analysis/failed-skipped`
        ),
      ]);
      setSummary(nextSummary);
      setDetail(nextDetail);
      setScores(nextScores);
      setRecommendations(nextRecs);
      setFailedPages(nextFailed);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to load page analysis.");
    }
  }, [websiteId]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load().catch((requestError: unknown) => {
        setError(requestError instanceof Error ? requestError.message : "Page analysis could not be loaded.");
      });
    }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  async function start() {
    setStarting(true);
    setError(null);
    try {
      const result = await apiRequest<{ status: string }>(
        `/api/v1/websites/${websiteId}/page-analysis/run`,
        { method: "POST" },
      );
      if (result.status === "queued") {
        setTaskRunning(true);
      }
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to start page analysis.");
    } finally {
      setStarting(false);
    }
  }

  return (
    <section className="mt-5 border-t pt-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="font-semibold">Site-wide Page Analysis</h3>
        <button
          className="rounded-lg border px-3 py-1.5 text-sm font-semibold disabled:opacity-50"
          disabled={starting || taskRunning}
          onClick={() => void start()}
          type="button"
        >
          {starting ? "Starting…" : taskRunning ? "Analysis running" : "Analyze all pages"}
        </button>
      </div>
      {error && <p className="mt-2 text-sm text-red-700" role="alert">{error}</p>}

      {summary && (
        <div className="mt-4">
          <div className="flex flex-wrap gap-2 border-b">
            {["coverage", "scores", "recommendations", "failed"].map((tab) => (
              <button
                className={`px-3 py-2 text-sm font-semibold ${
                  activeTab === tab ? "border-b-2 border-slate-950" : "text-slate-500"
                }`}
                key={tab}
                onClick={() => setActiveTab(tab)}
                type="button"
              >
                {tab.charAt(0).toUpperCase() + tab.slice(1).replace("_", " ")}
              </button>
            ))}
          </div>

          {activeTab === "coverage" && detail && (
            <div className="mt-4 grid gap-4">
              <div className="rounded-xl border bg-white p-4">
                <h4 className="font-semibold flex items-center gap-1">
                  Coverage
                  <MetricInfoButton metricId="analysis_coverage_percent" />
                </h4>
                <p className="mt-1 text-3xl font-bold">
                  <PercentageValue metricId="analysis_coverage_percent" value={detail.coverage_percent} />
                </p>
                <p className="text-sm text-slate-500">
                  {detail.level_1_attempted} of {detail.eligible_page_count} eligible pages
                </p>
              </div>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <div className="rounded-lg border bg-white p-3">
                  <p className="text-xs text-slate-500 flex items-center justify-between">Discovered <MetricInfoButton metricId="discovered_pages" /></p>
                  <p className="text-xl font-bold">{detail.discovered_page_count}</p>
                </div>
                <div className="rounded-lg border bg-white p-3">
                  <p className="text-xs text-slate-500 flex items-center justify-between">Eligible <MetricInfoButton metricId="eligible_pages" /></p>
                  <p className="text-xl font-bold">{detail.eligible_page_count}</p>
                </div>
                <div className="rounded-lg border bg-white p-3">
                  <p className="text-xs text-slate-500 flex items-center justify-between">Selected <ConceptInfoButton conceptId="page_selected" title="Selected pages" /></p>
                  <p className="text-xl font-bold">{detail.selected_page_count}</p>
                </div>
                <div className="rounded-lg border bg-white p-3">
                  <p className="text-xs text-slate-500 flex items-center justify-between">Clean pass <MetricInfoButton metricId="clean_pass_percent" /></p>
                  <p className="text-xl font-bold"><PercentageValue metricId="clean_pass_percent" value={detail.clean_pass_percent} /></p>
                </div>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="rounded-lg border bg-white p-3">
                  <p className="text-xs font-semibold text-slate-500 flex items-center gap-1">
                    Level 1 (Lightweight) <ConceptInfoButton conceptId="page_level_1" title="Level 1 Analysis" />
                  </p>
                  <dl className="mt-2 grid grid-cols-2 gap-2 text-sm">
                    <div><dt className="text-slate-400">Attempted</dt><dd className="font-semibold">{detail.level_1_attempted}</dd></div>
                    <div><dt className="text-slate-400">Successful</dt><dd className="font-semibold text-emerald-700">{detail.level_1_successful}</dd></div>
                    <div><dt className="text-slate-400">Failed</dt><dd className="font-semibold text-red-700">{detail.level_1_failed}</dd></div>
                    <div><dt className="text-slate-400">Partial</dt><dd className="font-semibold text-amber-700">{detail.level_1_partial}</dd></div>
                  </dl>
                </div>
                <div className="rounded-lg border bg-white p-3">
                  <p className="text-xs font-semibold text-slate-500 flex items-center gap-1">
                    Level 2 (Deep) <ConceptInfoButton conceptId="page_level_2" title="Level 2 Analysis" />
                  </p>
                  <dl className="mt-2 grid grid-cols-2 gap-2 text-sm">
                    <div><dt className="text-slate-400">Attempted</dt><dd className="font-semibold">{detail.level_2_attempted}</dd></div>
                    <div><dt className="text-slate-400">Successful</dt><dd className="font-semibold text-emerald-700">{detail.level_2_successful}</dd></div>
                    <div><dt className="text-slate-400">Failed</dt><dd className="font-semibold text-red-700">{detail.level_2_failed}</dd></div>
                    <div><dt className="text-slate-400">Partial</dt><dd className="font-semibold text-amber-700">{detail.level_2_partial}</dd></div>
                  </dl>
                </div>
              </div>
              {detail.coverage_limitations.length > 0 && (
                <div className="rounded-lg bg-amber-50 p-3 text-sm">
                  <p className="font-semibold text-amber-900">Limitations</p>
                  <ul className="mt-1 list-inside list-disc text-amber-800">
                    {detail.coverage_limitations.map((item, i) => <li key={i}>{item}</li>)}
                  </ul>
                </div>
              )}
              {detail.partial_result_status && (
                <div className="rounded-lg bg-amber-50 p-3 text-sm">
                  <p className="font-semibold text-amber-900">Partial results exist</p>
                  <p className="text-amber-800">Some pages have partial analysis results. Review the failed/skipped tab for details.</p>
                </div>
              )}
            </div>
          )}

          {activeTab === "scores" && (
            <div className="mt-4">
              {scores.length === 0 ? (
                <p className="text-sm text-slate-500">No page-level scores available yet. Run page analysis first.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[600px] text-left text-xs">
                    <thead>
                      <tr className="border-b">
                        <th className="p-2">Page URL</th>
                        <th>Title</th>
                        <th>Level</th>
                        <th>Status</th>
                        <th>Score <MetricInfoButton metricId="page_score" /></th>
                      </tr>
                    </thead>
                    <tbody>
                      {scores.map((item) => (
                        <tr className="border-b align-top" key={item.page_id}>
                          <td className="max-w-56 break-all p-2">{item.page_url}</td>
                          <td>{item.page_title || "—"}</td>
                          <td><AnalysisLevelBadge level={item.analysis_level} /></td>
                          <td><StatusBadge status={item.analysis_status} /></td>
                          <td>
                            {item.score_available ? (
                              <div className="flex items-baseline gap-1">
                                <span className="font-bold"><ScoreValue metricId="page_score" value={item.score} /></span>
                                <span className="text-xs font-normal text-slate-500">({item.confidence})</span>
                              </div>
                            ) : (
                              <span className="text-slate-400">—/100</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {activeTab === "recommendations" && (
            <div className="mt-4 grid gap-3">
              {recommendations.length === 0 ? (
                <p className="text-sm text-slate-500">No actionable recommendations found.</p>
              ) : (
                recommendations.map((rec, i) => (
                  <div className="rounded-xl border bg-white p-4" key={`${rec.page_id}-${rec.issue_title}-${i}`}>
                    <div className="flex flex-wrap items-center gap-2">
                      <StatusBadge status={rec.severity === "high" || rec.severity === "critical" ? "failed" : rec.severity === "medium" ? "partial" : "completed"} />
                      <span className="text-xs font-bold uppercase text-slate-500">{rec.issue_category}</span>
                      <AnalysisLevelBadge level={rec.analysis_level} />
                    </div>
                    <h4 className="mt-2 font-semibold">{rec.issue_title}</h4>
                    <p className="mt-1 text-sm break-all"><span className="text-slate-500">Page:</span> {rec.page_url}</p>
                    <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
                      <div>
                        <dt className="text-slate-500">Responsible area</dt>
                        <dd className="font-medium">{rec.responsible_area}</dd>
                      </div>
                      <div>
                        <dt className="text-slate-500">Responsible role</dt>
                        <dd className="font-medium">{rec.responsible_role}</dd>
                      </div>
                      <div className="sm:col-span-2">
                        <dt className="text-slate-500">Action location</dt>
                        <dd className="font-medium">{rec.action_location}</dd>
                      </div>
                      <div className="sm:col-span-2">
                        <dt className="text-slate-500">Remediation</dt>
                        <dd className="text-slate-700">{rec.remediation}</dd>
                      </div>
                      <div className="sm:col-span-2">
                        <dt className="text-slate-500">Verification</dt>
                        <dd className="text-slate-700">{rec.verification_method}</dd>
                      </div>
                      <div>
                        <dt className="text-slate-500">Confidence</dt>
                        <dd>{rec.confidence}</dd>
                      </div>
                      <div>
                        <dt className="text-slate-500">Source</dt>
                        <dd>{rec.source}</dd>
                      </div>
                    </dl>
                  </div>
                ))
              )}
            </div>
          )}

          {activeTab === "failed" && (
            <div className="mt-4">
              {failedPages.length === 0 ? (
                <p className="text-sm text-slate-500">No failed or skipped pages.</p>
              ) : (
                <div className="grid gap-3">
                  {failedPages.map((fp) => {
                    const pageUrl = String(fp.page_url ?? "");
                    const pageTitle = fp.page_title as string | null;
                    const statuses = fp.statuses as Record<string, { status: string; reason_code: string | null; reason_text: string | null }>;
                    return (
                      <div className="rounded-xl border bg-white p-4" key={fp.page_id as string}>
                        <p className="break-all text-sm font-semibold">{pageUrl}</p>
                        <p className="text-xs text-slate-500">{pageTitle || "—"}</p>
                        {Object.entries(statuses).map(([level, info]) => (
                          <div className="mt-2 rounded-lg bg-red-50 p-2 text-sm" key={level}>
                            <p className="font-semibold capitalize">{level.replace("_", " ")}</p>
                            <p className="text-red-700">
                              <StatusBadge status={info.status} />
                              {" "}
                              {info.reason_code && <code className="ml-1 rounded bg-red-100 px-1">{info.reason_code}</code>}
                            </p>
                            {info.reason_text && <p className="mt-1 text-slate-600">{info.reason_text}</p>}
                          </div>
                        ))}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {!summary && !error && <p className="mt-4 text-sm text-slate-500">Loading page analysis data…</p>}
      <SiteDiagnosticsReference context="page-analysis" websiteId={websiteId} />
      <aside className="mt-4 rounded-xl border bg-slate-50 p-4 text-sm">
        <strong>Site score context</strong>
        <p className="mt-1 text-slate-600">
          Page-level scores remain separate from the site score. Review normalized
          contributions, evidence coverage, and exclusions in the site explanation.
        </p>
        <a className="mt-2 inline-block font-semibold underline focus-visible:outline-2 focus-visible:outline-offset-2" href={`#scoring-intelligence-${websiteId}`}>
          Review explainable site score
        </a>
      </aside>
    </section>
  );
}
