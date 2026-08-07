"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import type {
  AnalysisComparison,
  ComparisonFinding,
} from "@/components/comparisons/types";
import { analysisComparisonApi } from "@/lib/analysis-comparison-api";
import { ApiError } from "@/lib/api";

function score(value: number | null): string {
  return value === null ? "Not comparable" : `${value}/100`;
}

function delta(value: number | null): string {
  if (value === null) return "Not comparable";
  return `${value > 0 ? "+" : ""}${value}`;
}

function FindingGroup({
  title,
  findings,
  empty,
}: {
  title: string;
  findings: ComparisonFinding[];
  empty: string;
}) {
  return (
    <section className="rounded-2xl border bg-white p-6">
      <h2 className="text-2xl font-bold">{title}</h2>
      {findings.length === 0 ? (
        <p className="mt-3 text-slate-600">{empty}</p>
      ) : (
        <ul className="mt-4 grid gap-4">
          {findings.map((finding, index) => (
            <li className="rounded-xl border border-slate-200 p-4" key={`${finding.title}-${index}`}>
              <div className="flex flex-wrap gap-2 text-xs font-bold uppercase">
                <span>{finding.category}</span>
                <span aria-hidden="true"> / </span>
                <span>{finding.classification}</span>
              </div>
              <h3 className="mt-2 text-lg font-bold">{finding.title}</h3>
              <p className="mt-2">{finding.observed_change}</p>
              <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
                <div>
                  <dt className="font-semibold">Severity before / after</dt>
                  <dd>{finding.severity_before} / {finding.severity_after}</dd>
                </div>
                <div>
                  <dt className="font-semibold">Affected pages before / after</dt>
                  <dd>{finding.affected_page_count_before} / {finding.affected_page_count_after}</dd>
                </div>
                {finding.browser.length > 0 && (
                  <div>
                    <dt className="font-semibold">Browsers</dt>
                    <dd>{finding.browser.map((item) => item.replaceAll("_", " ")).join(", ")}</dd>
                  </div>
                )}
              </dl>
              <p className="mt-3 text-sm">
                <strong>Next action:</strong> {finding.recommended_next_action}
              </p>
              {finding.evidence_limitation && (
                <p className="mt-2 text-sm text-amber-900">
                  <strong>Evidence limitation:</strong> {finding.evidence_limitation}
                </p>
              )}
              <details className="mt-3">
                <summary className="cursor-pointer font-semibold">
                  View all affected page addresses ({finding.affected_urls.length})
                </summary>
                <div className="mt-2 grid gap-4 text-sm sm:grid-cols-2">
                  <div>
                    <h4 className="font-semibold">Before</h4>
                    <ul className="grid gap-1">
                      {finding.affected_urls_before.map((url) => (
                        <li className="break-all" key={url}>{url}</li>
                      ))}
                    </ul>
                  </div>
                  <div>
                    <h4 className="font-semibold">After</h4>
                    <ul className="grid gap-1">
                      {finding.affected_urls_after.map((url) => (
                        <li className="break-all" key={url}>{url}</li>
                      ))}
                    </ul>
                  </div>
                </div>
              </details>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export default function AnalysisComparisonPage() {
  const { analysisRunId, baselineRunId } = useParams<{
    analysisRunId: string;
    baselineRunId: string;
  }>();
  const currentRunId = analysisRunId;
  const [comparison, setComparison] = useState<AnalysisComparison | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        let value: AnalysisComparison;
        try {
          value = await analysisComparisonApi.detail(currentRunId, baselineRunId);
        } catch (reason) {
          if (!(reason instanceof ApiError) || reason.status !== 404) throw reason;
          value = await analysisComparisonApi.generate(
            currentRunId,
            baselineRunId,
            `comparison-${currentRunId}-${baselineRunId}`,
          );
        }
        if (!cancelled) setComparison(value);
      } catch (reason) {
        if (!cancelled) {
          setError(
            reason instanceof Error ? reason.message : "The comparison could not be generated.",
          );
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [baselineRunId, currentRunId]);

  if (error) {
    return (
      <main className="mx-auto min-h-screen max-w-5xl px-6 py-12">
        <h1 className="text-3xl font-bold">Comparison unavailable</h1>
        <p className="mt-4 text-red-700" role="alert">{error}</p>
        <p className="mt-2 text-slate-600">
          Both analyses need completed evidence-backed reports. Missing evidence is never
          interpreted as improvement.
        </p>
      </main>
    );
  }
  if (!comparison) {
    return <main className="mx-auto max-w-5xl px-6 py-12"><p role="status">Preparing evidence comparison...</p></main>;
  }

  const payload = comparison.result_payload;
  return (
    <main className="mx-auto min-h-screen max-w-6xl px-6 py-12">
      <Link className="font-semibold underline" href={`/analysis-runs/${currentRunId}`}>
        Back to current analysis
      </Link>
      <header className="mt-6 rounded-3xl bg-slate-950 p-8 text-white">
        <p className="text-sm font-bold uppercase tracking-widest text-blue-200">
          Before and after
        </p>
        <h1 className="mt-2 text-4xl font-bold">{payload.website.name}</h1>
        <p className="mt-2 break-all text-slate-300">{payload.website.url}</p>
        <dl className="mt-6 grid gap-4 sm:grid-cols-2">
          <div><dt className="text-slate-400">Baseline analysis</dt><dd>{new Date(payload.baseline.analysis_date).toLocaleString()}</dd></div>
          <div><dt className="text-slate-400">Current analysis</dt><dd>{new Date(payload.current.analysis_date).toLocaleString()}</dd></div>
        </dl>
      </header>

      <nav aria-label="Comparison sections" className="mt-5 rounded-xl border bg-white p-4">
        <ul className="flex flex-wrap gap-4 text-sm font-semibold">
          {["Scores", "Coverage", "Browsers", "Findings", "Action Plan", "Limitations", "Exports"].map((item) => (
            <li key={item}><a className="underline focus-visible:outline-4" href={`#${item.toLowerCase().replace(" ", "-")}`}>{item}</a></li>
          ))}
        </ul>
      </nav>

      <section className="mt-6 rounded-2xl border bg-white p-6">
        <h2 className="text-2xl font-bold">Overall improvement summary</h2>
        <p className="mt-3 text-4xl font-bold">{payload.summary.direction}</p>
        <p className="mt-3">
          {payload.summary.resolved_count} resolved, {payload.summary.persistent_count} persistent,
          {" "}{payload.summary.new_count} new, and {payload.summary.regression_count} regressed.
        </p>
        {payload.summary.inconclusive_count > 0 && (
          <p className="mt-2 text-amber-900">
            {payload.summary.inconclusive_count} changes remain inconclusive because comparable
            evidence was unavailable.
          </p>
        )}
      </section>

      <section className="mt-6 rounded-2xl border bg-white p-6" id="scores">
        <h2 className="text-2xl font-bold">Score comparison</h2>
        <div className="mt-4 grid gap-4 sm:grid-cols-3">
          <div><p className="text-sm">Before</p><p className="text-4xl font-bold">{score(payload.scores.overall_score_before)}</p></div>
          <div><p className="text-sm">After</p><p className="text-4xl font-bold">{score(payload.scores.overall_score_after)}</p></div>
          <div><p className="text-sm">Change</p><p className="text-4xl font-bold">{delta(payload.scores.overall_delta)}</p><p>{payload.scores.direction}</p></div>
        </div>
        <p className="mt-3 text-sm">
          Formula before: {payload.scores.formula_version_before ?? "Unavailable"}; after:
          {" "}{payload.scores.formula_version_after ?? "Unavailable"}. Historical scores are not recalculated.
        </p>
        <p className="mt-1 text-sm">
          Score confidence before / after: {payload.scores.confidence_before == null ? "Unavailable" : `${payload.scores.confidence_before}%`}
          {" / "}
          {payload.scores.confidence_after == null ? "Unavailable" : `${payload.scores.confidence_after}%`}.
          Confidence is shown separately from score.
        </p>
        <div className="mt-5 overflow-x-auto">
          <table className="w-full min-w-[42rem] border-collapse text-left">
            <thead><tr>{["Category", "Before", "After", "Change", "Status before / after", "Direction"].map((item) => <th className="border bg-slate-100 p-3" key={item} scope="col">{item}</th>)}</tr></thead>
            <tbody>{payload.scores.categories.map((item) => <tr key={item.category}><th className="border p-3 capitalize" scope="row">{item.category}</th><td className="border p-3">{score(item.score_before)}</td><td className="border p-3">{score(item.score_after)}</td><td className="border p-3">{delta(item.delta)}</td><td className="border p-3">{item.status_before ?? "Unavailable"} / {item.status_after ?? "Unavailable"}</td><td className="border p-3">{item.direction}</td></tr>)}</tbody>
          </table>
        </div>
      </section>

      <section className="mt-6 rounded-2xl border bg-white p-6" id="coverage">
        <h2 className="text-2xl font-bold">Page coverage comparison</h2>
        <p className="mt-2 font-semibold">{payload.coverage.direction}</p>
        <dl className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {(["discovered", "scheduled", "visited", "successfully_analysed", "coverage_percentage"] as const).map((key) => {
            const item = payload.coverage[key];
            return <div className="rounded-lg bg-slate-50 p-3" key={key}><dt className="text-sm capitalize">{key.replaceAll("_", " ")}</dt><dd className="mt-1 font-bold">{item.before ?? "Unavailable"} to {item.after ?? "Unavailable"}</dd><dd className="text-sm">Change {delta(item.delta)}</dd></div>;
          })}
        </dl>
        {payload.coverage.limitation && <p className="mt-4 text-amber-900">{payload.coverage.limitation}</p>}
      </section>

      <section className="mt-6 rounded-2xl border bg-white p-6" id="browsers">
        <h2 className="text-2xl font-bold">Browser compatibility comparison</h2>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[58rem] border-collapse text-left">
            <thead><tr>{["Browser", "Tested before / after", "Passed before / after", "Partial before / after", "Failed before / after", "Unavailable or inconclusive before / after", "Result"].map((item) => <th className="border bg-slate-100 p-3" key={item} scope="col">{item}</th>)}</tr></thead>
            <tbody>{payload.browser_compatibility.engines.map((engine) => <tr key={engine.engine}><th className="border p-3 capitalize" scope="row">{engine.engine}</th><td className="border p-3">{engine.before.tested} / {engine.after.tested}</td><td className="border p-3">{engine.before.passed} / {engine.after.passed}</td><td className="border p-3">{engine.before.partial} / {engine.after.partial}</td><td className="border p-3">{engine.before.failed} / {engine.after.failed}</td><td className="border p-3">{(engine.before.unavailable ?? 0) + (engine.before.inconclusive ?? 0)} / {(engine.after.unavailable ?? 0) + (engine.after.inconclusive ?? 0)}</td><td className="border p-3">{engine.direction}{engine.limitation && <span className="mt-1 block text-xs text-amber-900">{engine.limitation}</span>}</td></tr>)}</tbody>
          </table>
        </div>
      </section>

      <div className="mt-6 grid gap-6" id="findings">
        <FindingGroup empty="No finding was safely classified as resolved." findings={payload.findings.resolved} title="Resolved findings" />
        <FindingGroup empty="No persistent findings were retained." findings={payload.findings.persistent} title="Persistent findings" />
        <FindingGroup empty="No new findings were supported by comparable evidence." findings={payload.findings.new} title="New findings" />
        <FindingGroup empty="No evidence-backed regression was retained." findings={payload.findings.regressions} title="Regressions" />
        <FindingGroup empty="No inconclusive finding changes were retained." findings={payload.findings.inconclusive} title="Inconclusive changes" />
      </div>

      <section className="mt-6 rounded-2xl border bg-white p-6" id="action-plan">
        <h2 className="text-2xl font-bold">Action Plan progress</h2>
        <ul className="mt-4 grid gap-3">
          {payload.action_plan.map((action, index) => (
            <li className="rounded-xl bg-slate-50 p-4" key={`${action.title}-${index}`}>
              <h3 className="font-bold">{action.title}</h3>
              <p className="mt-1">{action.classification}</p>
              <p className="mt-2 text-sm"><strong>Evidence:</strong> {action.supporting_evidence}</p>
              <p className="mt-1 text-sm"><strong>Verify:</strong> {action.verification_method}</p>
            </li>
          ))}
        </ul>
      </section>

      <section className="mt-6 rounded-2xl border bg-amber-50 p-6" id="limitations">
        <h2 className="text-2xl font-bold">Evidence limitations</h2>
        <ul className="mt-3 list-disc space-y-2 pl-6">{payload.limitations.map((item) => <li key={item}>{item}</li>)}</ul>
      </section>

      <section className="mt-6 rounded-2xl border bg-white p-6" id="exports">
        <h2 className="text-2xl font-bold">Export comparison</h2>
        <div className="mt-4 flex flex-wrap gap-3">
          {comparison.artifacts.map((artifact) => (
            <a className="rounded-lg border border-slate-800 px-4 py-2 font-semibold focus-visible:outline-4" href={analysisComparisonApi.downloadUrl(comparison.comparison_id, artifact.format)} key={artifact.format}>
              Comparison {artifact.format.toUpperCase()}
            </a>
          ))}
        </div>
      </section>
    </main>
  );
}
