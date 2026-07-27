"use client";

import { useCallback, useEffect, useState } from "react";

import { SafeStructuredValue } from "@/components/agents/SafeStructuredValue";
import type {
  ScoreBreakdown,
  ScoreExecution,
  ScoringFormula,
  ScoringProfile,
} from "@/components/scoring/types";
import { ApiError } from "@/lib/api";
import { scoringApi } from "@/lib/scoring-api";

const PAGE_SIZE = 10;

function key(): string {
  return typeof crypto !== "undefined" && crypto.randomUUID
    ? crypto.randomUUID()
    : `score-${Date.now()}`;
}

function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    const request = error.requestId ? ` Request ID: ${error.requestId}` : "";
    if (error.status === 404) return `Not found: ${error.message}${request}`;
    if (error.status === 409) return `Evidence unavailable or conflict: ${error.message}${request}`;
    if (error.status === 422) return `Validation error: ${error.message}${request}`;
    return `${error.message}${request}`;
  }
  return error instanceof Error ? error.message : "Score data could not be loaded.";
}

function scoreText(value: number | null): string {
  return value === null ? "Unavailable" : `${value}/100`;
}

function Trend({ trend }: { trend: Record<string, unknown> }) {
  const state = String(trend.state ?? "unavailable");
  return (
    <div className="rounded-lg bg-slate-50 p-3 text-sm">
      <p className="font-semibold capitalize">Trend: {state.replaceAll("_", " ")}</p>
      {typeof trend.score_delta === "number" && (
        <p>Overall delta: {trend.score_delta > 0 ? "+" : ""}{trend.score_delta}</p>
      )}
      {typeof trend.evidence_coverage_delta === "number" && (
        <p>Evidence coverage delta: {trend.evidence_coverage_delta > 0 ? "+" : ""}
          {trend.evidence_coverage_delta.toFixed(1)} percentage points
        </p>
      )}
      {typeof trend.reason === "string" && <p className="text-slate-600">{trend.reason}</p>}
    </div>
  );
}

interface Props {
  websiteId: string;
  analysisRunId?: string;
  compact?: boolean;
}

export function ScoringIntelligencePanel({
  websiteId,
  analysisRunId,
  compact = false,
}: Props) {
  const [execution, setExecution] = useState<ScoreExecution | null>(null);
  const [breakdown, setBreakdown] = useState<ScoreBreakdown | null>(null);
  const [formula, setFormula] = useState<ScoringFormula | null>(null);
  const [profiles, setProfiles] = useState<ScoringProfile[]>([]);
  const [history, setHistory] = useState<ScoreExecution[]>([]);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [statusFilter, setStatusFilter] = useState("");
  const [profileFilter, setProfileFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [calculating, setCalculating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [formulas, loadedProfiles, loadedHistory] = await Promise.all([
        scoringApi.formulas(),
        scoringApi.profiles(),
        scoringApi.history(websiteId, {
          status: statusFilter || undefined,
          profileId: profileFilter || undefined,
          limit: PAGE_SIZE,
          offset,
        }),
      ]);
      setFormula(formulas[0] ?? null);
      setProfiles(loadedProfiles);
      setHistory(loadedHistory.items);
      setHistoryTotal(loadedHistory.total);
      let selected: ScoreExecution | null = null;
      if (analysisRunId) {
        const runScores = await scoringApi.listForRun(analysisRunId, 1, 0);
        selected = runScores.items[0] ?? null;
      } else {
        selected = await scoringApi.latestForWebsite(websiteId).catch((requestError) => {
          if (requestError instanceof ApiError && requestError.status === 404) return null;
          throw requestError;
        });
      }
      setExecution(selected);
      setBreakdown(selected ? await scoringApi.breakdown(selected.execution_id) : null);
      setError(null);
    } catch (requestError) {
      setError(errorText(requestError));
    } finally {
      setLoading(false);
    }
  }, [analysisRunId, offset, profileFilter, statusFilter, websiteId]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  async function calculate() {
    if (!analysisRunId) return;
    setCalculating(true);
    try {
      const created = await scoringApi.calculate(analysisRunId, key());
      setExecution(created);
      setBreakdown(await scoringApi.breakdown(created.execution_id));
      setError(null);
      await load();
    } catch (requestError) {
      setError(errorText(requestError));
    } finally {
      setCalculating(false);
    }
  }

  const scope = `scoring-intelligence-${websiteId}`;
  return (
    <section
      aria-labelledby={`${scope}-heading`}
      className={`scroll-mt-6 rounded-2xl border bg-white ${compact ? "mt-6 p-5" : "mt-8 p-6"}`}
      id={scope}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-bold uppercase tracking-wide text-indigo-700">
            Deterministic and reproducible
          </p>
          <h2 className="mt-1 text-2xl font-bold" id={`${scope}-heading`}>
            Explainable Scoring Intelligence
          </h2>
          <p className="mt-2 max-w-3xl text-sm text-slate-600">
            Shows the stored evidence, normalized weights, contributions, exclusions,
            confidence, and limitations behind the score. An LLM cannot calculate or
            modify these values.
          </p>
        </div>
        {analysisRunId && (
          <button
            className="rounded-lg bg-indigo-800 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-700"
            disabled={calculating}
            onClick={() => void calculate()}
            type="button"
          >
            {calculating ? "Calculating..." : execution ? "Create new snapshot" : "Calculate score"}
          </button>
        )}
      </div>
      {loading && <p className="mt-4" role="status">Loading score evidence...</p>}
      {error && <p className="mt-4 rounded-lg bg-red-50 p-3 text-red-800" role="alert">{error}</p>}
      {!loading && !execution && !error && (
        <div className="mt-5 rounded-xl border border-dashed p-5">
          <p className="font-semibold">Score not yet calculated</p>
          <p className="mt-1 text-sm text-slate-600">
            This is not a zero score and does not mean the website has perfect evidence.
          </p>
        </div>
      )}
      {execution && breakdown && (
        <>
          <section aria-labelledby={`${scope}-overview`} className="mt-6">
            <h3 className="text-lg font-semibold" id={`${scope}-overview`}>Overall Score Overview</h3>
            <div className="mt-3 grid gap-3 sm:grid-cols-4">
              <div className="rounded-xl bg-slate-950 p-4 text-white">
                <p className="text-xs uppercase">Overall score</p>
                <p className="mt-1 text-4xl font-bold">{scoreText(execution.overall_score)}</p>
              </div>
              <div className="rounded-xl bg-slate-50 p-4">
                <p className="text-xs text-slate-500">Status</p>
                <p className="mt-1 font-bold capitalize">{execution.status}</p>
              </div>
              <div className="rounded-xl bg-slate-50 p-4">
                <p className="text-xs text-slate-500">Confidence</p>
                <p className="mt-1 font-bold">
                  {execution.confidence_percent === null ? "Unavailable" : `${execution.confidence_percent}%`}
                  {" · "}{execution.confidence_classification}
                </p>
              </div>
              <div className="rounded-xl bg-slate-50 p-4">
                <p className="text-xs text-slate-500">Evidence coverage</p>
                <p className="mt-1 font-bold">
                  {execution.evidence_coverage_numerator}/{execution.evidence_coverage_denominator}
                  {" · "}
                  {execution.evidence_coverage_percentage === null
                    ? "Unavailable"
                    : `${execution.evidence_coverage_percentage.toFixed(1)}%`}
                </p>
              </div>
            </div>
          </section>
          <section aria-labelledby={`${scope}-categories`} className="mt-7 border-t pt-5">
            <h3 className="text-lg font-semibold" id={`${scope}-categories`}>Category Score Breakdown</h3>
            <ul className="mt-3 grid gap-3 md:grid-cols-2">
              {breakdown.categories.map((category) => (
                <li className="rounded-xl border p-4" key={category.category_id}>
                  <div className="flex justify-between gap-3">
                    <strong className="capitalize">{category.category_id.replaceAll("_", " ")}</strong>
                    <span>{scoreText(category.final_score)}</span>
                  </div>
                  <p className="mt-1 text-sm capitalize">Band: {category.band.replaceAll("_", " ")}</p>
                  {category.included ? (
                    <p className="mt-1 text-xs text-slate-600">
                      Weight {(category.configured_weight * 100).toFixed(0)}%;
                      normalized {((category.normalized_weight ?? 0) * 100).toFixed(2)}%;
                      contribution {category.contribution?.toFixed(3)}
                    </p>
                  ) : (
                    <p className="mt-1 text-sm text-amber-800">
                      Excluded metric: {category.exclusion_reason}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          </section>
          <section aria-labelledby={`${scope}-metrics`} className="mt-7 border-t pt-5">
            <h3 className="text-lg font-semibold" id={`${scope}-metrics`}>Metric Contributions</h3>
            <div className="mt-3 overflow-x-auto">
              <table className="min-w-[760px] text-left text-sm">
                <thead><tr className="border-b"><th className="p-2">Metric</th><th>Raw</th><th>Normalized</th><th>Weight</th><th>Contribution</th><th>Decision</th></tr></thead>
                <tbody>{breakdown.contributions.map((item) => (
                  <tr className="border-b" key={item.metric_id}>
                    <th className="p-2 font-mono">{item.metric_id}</th>
                    <td>{String(item.raw_value.value ?? "Unavailable")}</td>
                    <td>{item.normalized_value ?? "Unavailable"}</td>
                    <td>{item.normalized_weight === null ? "Excluded" : `${(item.normalized_weight * 100).toFixed(2)}%`}</td>
                    <td>{item.contribution?.toFixed(3) ?? "Unavailable"}</td>
                    <td className="capitalize">{item.inclusion_status}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          </section>
          <section aria-labelledby={`${scope}-explanation`} className="mt-7 grid gap-4 border-t pt-5 lg:grid-cols-2">
            <div>
              <h3 className="text-lg font-semibold" id={`${scope}-explanation`}>Score Explanation</h3>
              <p className="mt-2 text-sm">{breakdown.explanation.formula_summary}</p>
              <p className="mt-2 text-sm">{breakdown.explanation.profile_summary}</p>
              <details className="mt-3"><summary className="cursor-pointer font-semibold">Normalization, deductions, and evidence</summary><div className="mt-2"><SafeStructuredValue value={{
                normalization: breakdown.explanation.normalization_decisions,
                caps_floors_deductions: breakdown.explanation.caps_floors_deductions,
                evidence_references: breakdown.snapshot.evidence_references,
              }} /></div></details>
            </div>
            <div>
              <h3 className="text-lg font-semibold">Confidence and Limitations</h3>
              <ul className="mt-2 list-disc space-y-1 pl-5 text-sm">{breakdown.explanation.limitations.map((item) => <li key={item}>{item}</li>)}</ul>
              {execution.unavailable_metrics.length > 0 && <p className="mt-3 text-sm text-amber-800">Unavailable: {execution.unavailable_metrics.join(", ")}</p>}
            </div>
          </section>
          <section aria-labelledby={`${scope}-trend`} className="mt-7 border-t pt-5">
            <h3 className="text-lg font-semibold" id={`${scope}-trend`}>Historical Trends</h3>
            <div className="mt-3"><Trend trend={breakdown.trend} /></div>
            <p className="mt-2 text-xs text-slate-500">Incompatible formula or profile versions are not presented as directly comparable.</p>
          </section>
          <section aria-labelledby={`${scope}-formula`} className="mt-7 border-t pt-5">
            <h3 className="text-lg font-semibold" id={`${scope}-formula`}>Formula and Profile Details</h3>
            <p className="mt-2 text-sm">Formula {execution.formula_id} v{execution.formula_version}; profile {execution.scoring_profile_id} v{execution.scoring_profile_version}; metric registry v{execution.metric_registry_version}.</p>
            {formula && <p className="mt-1 text-sm">Rounding: {formula.rounding}. Missing evidence: {formula.unavailable_behavior}.</p>}
          </section>
        </>
      )}
      <section aria-labelledby={`${scope}-history`} className="mt-7 border-t pt-5">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h3 className="text-lg font-semibold" id={`${scope}-history`}>Score History</h3>
          <div className="flex gap-2">
            <label className="text-xs">Status<select className="ml-1 rounded border p-1" onChange={(event) => { setStatusFilter(event.target.value); setOffset(0); }} value={statusFilter}><option value="">All</option><option value="completed">Completed</option><option value="partial">Partial</option><option value="unavailable">Unavailable</option></select></label>
            <label className="text-xs">Profile<select className="ml-1 rounded border p-1" onChange={(event) => { setProfileFilter(event.target.value); setOffset(0); }} value={profileFilter}><option value="">All</option>{profiles.map((profile) => <option key={profile.profile_id} value={profile.profile_id}>{profile.name}</option>)}</select></label>
          </div>
        </div>
        {history.length === 0 ? <p className="mt-3 text-sm text-slate-600">No historical scoring executions match these filters.</p> : <ul className="mt-3 space-y-2">{history.map((item) => <li className="rounded-lg bg-slate-50 p-3 text-sm" key={item.execution_id}><strong>{scoreText(item.overall_score)}</strong> · {new Date(item.created_at).toLocaleString()} · {item.scoring_profile_id} v{item.scoring_profile_version}<div className="mt-2"><Trend trend={item.trend ?? { state: "unavailable" }} /></div></li>)}</ul>}
        <div className="mt-3 flex justify-between text-sm"><button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))} type="button">Previous</button><span>{historyTotal === 0 ? 0 : offset + 1}-{Math.min(offset + PAGE_SIZE, historyTotal)} of {historyTotal}</span><button disabled={offset + PAGE_SIZE >= historyTotal} onClick={() => setOffset(offset + PAGE_SIZE)} type="button">Next</button></div>
      </section>
    </section>
  );
}
