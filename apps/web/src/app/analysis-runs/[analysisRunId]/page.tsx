"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { apiRequest } from "@/lib/api";
import type { AnalysisReport, DiagnosticGroup } from "@/lib/types";

function display(value: unknown): string {
  if (value === null || value === undefined || value === "") return "Not available";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(2);
  return String(value);
}

function label(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (character) => character.toUpperCase());
}

function HumanValue({ value }: { value: unknown }) {
  if (Array.isArray(value)) {
    if (!value.length) return <span className="text-slate-500">None observed</span>;
    return (
      <ul className="grid gap-2">
        {value.map((item, index) => (
          <li className="rounded-lg bg-slate-50 p-3" key={index}>
            <HumanValue value={item} />
          </li>
        ))}
      </ul>
    );
  }
  if (value && typeof value === "object") {
    return (
      <dl className="grid gap-2 sm:grid-cols-2">
        {Object.entries(value as Record<string, unknown>).map(([key, nested]) => (
          <div className="min-w-0" key={key}>
            <dt className="text-xs font-semibold text-slate-500">{label(key)}</dt>
            <dd className="break-words text-sm"><HumanValue value={nested} /></dd>
          </div>
        ))}
      </dl>
    );
  }
  return <span>{display(value)}</span>;
}

function CopyId({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      className="rounded border border-slate-600 px-2 py-1 text-xs"
      onClick={() => {
        void navigator.clipboard.writeText(value).then(() => {
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1200);
        });
      }}
      type="button"
    >
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

const metricLabels: Record<string, string> = {
  first_contentful_paint_ms: "First Contentful Paint (ms)",
  largest_contentful_paint_ms: "Largest Contentful Paint (ms)",
  total_blocking_time_ms: "Total Blocking Time (ms)",
  cumulative_layout_shift: "Cumulative Layout Shift",
  speed_index_ms: "Speed Index (ms)",
  time_to_interactive_ms: "Time to Interactive (ms)",
};

const measurementLabels: Record<string, string> = {
  canonical_url: "Canonical URL",
  html_language: "HTML language",
  h1_count: "H1 count",
  h1_texts: "H1 text",
  image_count: "Images",
  images_missing_alt: "Images missing alt text",
  internal_link_count: "Internal links",
  external_link_count: "External links",
  form_count: "Forms",
  button_count: "Buttons",
  console_errors: "Console errors",
  page_javascript_errors: "Page errors",
  failed_network_requests: "Failed network requests",
  https_usage: "HTTPS usage",
  responsive_viewport: "Responsive viewport",
};

const diagnosticTitles: Record<string, string> = {
  standards_diagnostics: "Web Standards",
  cache_diagnostics: "Cache Efficiency",
  policy_diagnostics: "Policies and Legal Metadata",
  copyright_diagnostics: "Copyright Metadata",
  security_diagnostics: "Security Posture",
  analytics_diagnostics: "Analytics and Tracking",
  responsive_diagnostics: "Responsive Testing",
  browser_compatibility: "Browser Compatibility",
};

const diagnosticWhy: Record<string, string> = {
  standards_diagnostics: "Valid markup improves browser interoperability and makes defects easier to diagnose.",
  cache_diagnostics: "Cache reuse can reduce repeat-load latency and transferred data.",
  policy_diagnostics: "Visible policy metadata helps visitors locate important public information.",
  copyright_diagnostics: "Current visible metadata can signal routine site maintenance.",
  security_diagnostics: "Restrictive browser security controls reduce exposure to common client-side attacks.",
  analytics_diagnostics: "Verified tracking evidence helps identify duplicate installation and consent risks.",
  responsive_diagnostics: "Viewport and target behavior affects mobile and touch usability.",
  browser_compatibility: "Explicit test coverage prevents Chromium-only evidence from being overstated.",
};

function DiagnosticCard({ name, diagnostic }: { name: string; diagnostic: DiagnosticGroup }) {
  const provisional =
    diagnostic.status === "partial" ||
    diagnostic.evidence_completeness === "html_only" ||
    diagnostic.verified_observations.score_qualification === "provisional_html_only";
  return (
    <details className="rounded-2xl border bg-white p-6" open={name === "cache_diagnostics"}>
      <summary className="cursor-pointer text-xl font-bold">{diagnosticTitles[name] ?? label(name)}</summary>
      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <div><p className="text-xs font-semibold text-slate-500">Status</p><p className="capitalize">{label(diagnostic.status)}</p></div>
        <div><p className="text-xs font-semibold text-slate-500">Evidence completeness</p><p>{label(diagnostic.evidence_completeness ?? diagnostic.status)}</p></div>
        <div><p className="text-xs font-semibold text-slate-500">Collected</p><p>{new Date(diagnostic.collected_at).toLocaleString()}</p></div>
      </div>
      {diagnostic.score && (
        <div className={`mt-4 rounded-xl p-4 ${provisional ? "border border-amber-300 bg-amber-50" : "bg-slate-50"}`}>
          <p className="text-xs font-bold uppercase">{diagnostic.score.label}</p>
          <p className="text-4xl font-bold">
            {diagnostic.score.final_score}
            {provisional && <span className="ml-2 text-base font-semibold text-amber-800">Provisional</span>}
          </p>
          <p className="text-sm">Formula {diagnostic.score.formula_version} · Confidence {diagnostic.score.confidence_percent}%</p>
          {name === "cache_diagnostics" && provisional && (
            <p className="mt-2 font-semibold text-amber-900">Static asset analysis unavailable or incomplete; this is not a fully verified perfect result.</p>
          )}
        </div>
      )}
      <h3 className="mt-5 font-semibold">Why this matters</h3>
      <p className="mt-1 text-sm text-slate-700">{diagnostic.why_it_matters || diagnosticWhy[name]}</p>
      <h3 className="mt-5 font-semibold">Verified observations</h3>
      <div className="mt-2"><HumanValue value={diagnostic.verified_observations} /></div>
      {diagnostic.score?.deductions.length ? (
        <>
          <h3 className="mt-5 font-semibold">Deductions</h3>
          <ul className="mt-2 grid gap-2 text-sm">
            {diagnostic.score.deductions.map((item, index) => (
              <li className="rounded-lg bg-rose-50 p-3" key={`${item.code}-${index}`}>
                <strong>{item.code}</strong>: −{item.points} — {item.reason}
              </li>
            ))}
          </ul>
        </>
      ) : diagnostic.score ? <p className="mt-4 text-sm"><strong>Deductions:</strong> None under this formula.</p> : null}
      <h3 className="mt-5 font-semibold">Evidence</h3>
      {diagnostic.evidence.length ? <HumanValue value={diagnostic.evidence} /> : <p className="mt-1 text-sm text-slate-500">No additional bounded evidence.</p>}
      <p className="mt-5 text-sm"><strong>Unavailable measurements:</strong> {diagnostic.unavailable_observations.map(label).join(", ") || "None"}</p>
      {diagnostic.limitations.length > 0 && (
        <div className="mt-4 rounded-lg bg-slate-50 p-3">
          <p className="font-semibold">Limitations</p>
          <ul className="mt-1 grid gap-1 text-sm text-slate-600">{diagnostic.limitations.map((item) => <li key={item}>• {item}</li>)}</ul>
        </div>
      )}
      <details className="mt-4">
        <summary className="cursor-pointer text-sm font-semibold">Technical details (JSON)</summary>
        <pre className="mt-2 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-950 p-3 text-xs text-slate-100">{JSON.stringify(diagnostic, null, 2)}</pre>
      </details>
    </details>
  );
}

export default function AnalysisReportPage() {
  const { analysisRunId } = useParams<{ analysisRunId: string }>();
  const [report, setReport] = useState<AnalysisReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void apiRequest<AnalysisReport>(`/api/v1/analysis-runs/${analysisRunId}/report`)
      .then((loaded) => { if (!cancelled) setReport(loaded); })
      .catch((requestError: unknown) => {
        if (!cancelled) setError(requestError instanceof Error ? requestError.message : "Unable to load report.");
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [analysisRunId]);

  if (loading) return <main className="mx-auto max-w-6xl px-6 py-12"><p role="status">Loading analysis report…</p></main>;
  if (error || !report) return <main className="mx-auto max-w-6xl px-6 py-12"><h1 className="text-3xl font-bold">Report unavailable</h1><p className="mt-4 text-red-700" role="alert">{error ?? "The report could not be found."}</p></main>;

  const categoryScores = {
    Performance: report.score.performance_score,
    Accessibility: report.score.accessibility_score,
    "Best Practices": report.score.best_practices_score,
    SEO: report.score.seo_score,
    "Technical Quality": report.score.technical_quality_score,
  };
  const diagnostics = Object.entries(report.diagnostics);
  const copyright = report.diagnostics.policy_diagnostics?.copyright;
  if (copyright) diagnostics.splice(3, 0, ["copyright_diagnostics", copyright]);
  const lighthouseContext = report.lighthouse_metrics.lighthouse_context;
  const auditBreakdown = Array.isArray(report.lighthouse_metrics.lighthouse_audit_breakdown)
    ? report.lighthouse_metrics.lighthouse_audit_breakdown as Array<Record<string, unknown>>
    : [];
  const technology = report.playwright_measurements.technology_indicators;

  return (
    <main className="mx-auto min-h-screen max-w-6xl px-6 py-12">
      <Link className="text-sm font-semibold text-slate-600" href="/projects">← Projects</Link>
      <header className="mt-6 rounded-2xl bg-slate-950 p-7 text-white">
        <h1 className="text-3xl font-bold">{report.website.name || "Website analysis"}</h1>
        <dl className="mt-5 grid gap-3 text-sm sm:grid-cols-2">
          <div><dt className="text-slate-400">Analysis Run ID</dt><dd className="flex items-center gap-2 break-all">{report.analysis_run_id}<CopyId value={report.analysis_run_id} /></dd></div>
          <div><dt className="text-slate-400">Report ID</dt><dd className="flex items-center gap-2 break-all">{report.report_id}<CopyId value={report.report_id} /></dd></div>
          <div><dt className="text-slate-400">Requested URL</dt><dd className="break-all">{report.result.requested_url}</dd></div>
          <div><dt className="text-slate-400">Final URL</dt><dd className="break-all">{report.result.final_url}</dd></div>
          <div><dt className="text-slate-400">Analysis date</dt><dd>{new Date(report.result.analysis_completed_at).toLocaleString()}</dd></div>
          <div><dt className="text-slate-400">Status</dt><dd className="capitalize">{report.analysis_status}</dd></div>
        </dl>
      </header>

      {report.interpretation && (
        <section className="mt-6 grid gap-6">
          <div className="rounded-2xl border bg-white p-6">
            <div className="flex flex-wrap items-center gap-3"><h2 className="text-xl font-bold">Executive Summary</h2><span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-bold uppercase">{report.interpretation.generation_mode === "ai" ? "AI generated" : "Deterministic fallback"}</span></div>
            <p className="mt-4 text-slate-700">{report.interpretation.executive_summary}</p>
            <h3 className="mt-5 font-semibold">Overall assessment</h3><p className="mt-2 text-slate-700">{report.interpretation.overall_assessment}</p>
          </div>
          <div className="grid gap-6 lg:grid-cols-2">
            <div className="rounded-2xl border bg-white p-6"><h2 className="text-xl font-bold">Key Strengths</h2>{report.interpretation.strengths.length ? <ul className="mt-4 grid gap-3">{report.interpretation.strengths.map((item, index) => <li className="rounded-lg bg-emerald-50 p-3 text-sm" key={`${item.text}-${index}`}>{item.text}</li>)}</ul> : <p className="mt-3 text-sm text-slate-600">Insufficient verified evidence is available.</p>}</div>
            <div className="rounded-2xl border bg-white p-6"><h2 className="text-xl font-bold">Priority Weaknesses</h2>{report.interpretation.weaknesses.length ? <ul className="mt-4 grid gap-3">{report.interpretation.weaknesses.map((item, index) => <li className="rounded-lg bg-amber-50 p-3 text-sm" key={`${item.text}-${index}`}>{item.text}<p className="mt-1 font-mono text-xs">{item.related_finding_codes.join(", ")}</p></li>)}</ul> : <p className="mt-3 text-sm text-slate-600">No verified weaknesses were available.</p>}</div>
          </div>
          <div className="rounded-2xl border bg-white p-6"><h2 className="text-xl font-bold">Recommended Actions</h2>{report.interpretation.priority_recommendations.length ? <ul className="mt-4 grid gap-4">{report.interpretation.priority_recommendations.map((item) => <li className="rounded-xl border p-4" key={item.recommendation_id}><p className="text-xs font-bold uppercase">{item.priority} · {item.related_finding_codes.join(", ")}</p><h3 className="mt-2 font-bold">{item.title}</h3><p className="mt-2 text-sm text-slate-600">{item.explanation}</p><dl className="mt-3 grid gap-2 text-sm sm:grid-cols-2"><div><dt className="text-slate-500">Business impact</dt><dd>{item.business_impact}</dd></div><div><dt className="text-slate-500">Recommended fix</dt><dd>{item.recommended_fix}</dd></div><div><dt className="text-slate-500">Effort</dt><dd>{item.estimated_effort}</dd></div><div><dt className="text-slate-500">Confidence</dt><dd>{item.confidence_percent}%</dd></div></dl></li>)}</ul> : <p className="mt-3 text-sm text-slate-600">No evidence-grounded actions were generated.</p>}</div>
        </section>
      )}

      <section className="mt-6 grid gap-4 md:grid-cols-3">
        <div className="rounded-2xl border bg-white p-6"><p className="text-sm text-slate-500">Overall score</p><p className="mt-2 text-6xl font-bold">{display(report.score.overall_score)}</p><p className="mt-3 text-sm">Confidence: {report.score.confidence_percent}%</p><p className="text-sm">Formula: {report.score.formula_version}</p></div>
        <div className="grid gap-3 sm:grid-cols-2 md:col-span-2">{Object.entries(categoryScores).map(([name, score]) => <div className="rounded-xl border bg-white p-4" key={name}><p className="text-sm text-slate-500">{name}</p><p className="mt-1 text-3xl font-bold">{display(score)}</p></div>)}</div>
      </section>

      <section className="mt-6 rounded-2xl border bg-white p-6">
        <h2 className="text-xl font-bold">Score transparency</h2>
        <p className="mt-3 text-sm text-slate-600">Available weights are normalized when measurements are missing. Lighthouse findings are not deducted from Technical Quality.</p>
        <p className="mt-3 text-sm"><strong>Available:</strong> {report.score.available_categories.join(", ") || "None"}</p>
        <p className="mt-1 text-sm"><strong>Unavailable:</strong> {report.score.unavailable_categories.join(", ") || "None"}</p>
        <h3 className="mt-5 font-semibold">Technical Quality deductions</h3>
        {report.score.deductions.length ? <HumanValue value={report.score.deductions} /> : <p className="mt-2 text-sm text-slate-600">No eligible deductions.</p>}
      </section>

      <section className="mt-6 grid gap-5">
        <h2 className="text-2xl font-bold">Verified diagnostics</h2>
        {diagnostics.map(([name, diagnostic]) => <DiagnosticCard diagnostic={diagnostic} key={name} name={name} />)}
      </section>

      <section className="mt-6 grid gap-6 lg:grid-cols-2">
        <div className="rounded-2xl border bg-white p-6">
          <h2 className="text-xl font-bold">Lighthouse metrics</h2>
          <dl className="mt-4 grid gap-3">{Object.entries(metricLabels).map(([key, name]) => <div key={key}><dt className="text-sm text-slate-500">{name}</dt><dd className="font-semibold">{display(report.lighthouse_metrics[key])}</dd>{key === "time_to_interactive_ms" && <p className="text-xs text-slate-500">Legacy/supplementary; not a current Core Web Vital and not necessarily included in the performance score.</p>}</div>)}</dl>
        </div>
        <div className="rounded-2xl border bg-white p-6"><h2 className="text-xl font-bold">Lighthouse execution context</h2><div className="mt-4"><HumanValue value={lighthouseContext} /></div></div>
      </section>

      <section className="mt-6 rounded-2xl border bg-white p-6">
        <h2 className="text-xl font-bold">Lighthouse audit breakdown</h2>
        {auditBreakdown.length ? <HumanValue value={auditBreakdown} /> : <p className="mt-3 text-sm text-slate-500">No failed or manual-check audit breakdown was retained for this report.</p>}
        <div className="mt-5 rounded-lg bg-blue-50 p-4 text-sm"><strong>Accessibility context:</strong> Lighthouse performs automated checks. A score of 100 does not prove complete accessibility compliance; manual accessibility testing is still required.</div>
      </section>

      <section className="mt-6 grid gap-6 lg:grid-cols-2">
        <div className="rounded-2xl border bg-white p-6"><h2 className="text-xl font-bold">Technology detection</h2><div className="mt-4"><HumanValue value={technology} /></div><p className="mt-4 text-sm text-slate-500">Technology claims require framework-specific or corroborating indicators; a lone weak signal is reported as uncertain.</p></div>
        <div className="rounded-2xl border bg-white p-6"><h2 className="text-xl font-bold">Page measurements</h2><dl className="mt-4 grid gap-3"><div><dt className="text-sm text-slate-500">HTTP status</dt><dd>{display(report.result.http_status_code)}</dd></div><div><dt className="text-sm text-slate-500">Page title</dt><dd>{display(report.result.page_title)}</dd></div>{Object.entries(measurementLabels).map(([key, name]) => <div key={key}><dt className="text-sm text-slate-500">{name}</dt><dd className="break-all"><HumanValue value={report.playwright_measurements[key]} /></dd></div>)}</dl></div>
      </section>

      <section className="mt-6 rounded-2xl border bg-white p-6"><h2 className="text-xl font-bold">Findings</h2>{report.findings.length === 0 ? <p className="mt-3 text-slate-600">No verified findings.</p> : <ul className="mt-4 grid gap-4">{report.findings.map((finding) => <li className="rounded-xl border p-4" key={finding.id}><p className="text-xs font-bold uppercase">{finding.severity} · {finding.category} · {finding.source}</p><h3 className="mt-2 font-bold">{finding.title}</h3><p className="mt-1 text-sm text-slate-600">{finding.description}</p><dl className="mt-3 grid gap-2 text-sm"><div><dt className="text-slate-500">Finding code</dt><dd>{finding.finding_code}</dd></div><div><dt className="text-slate-500">Affected URL</dt><dd className="break-all">{finding.affected_url}</dd></div><div><dt className="text-slate-500">Evidence</dt><dd><HumanValue value={finding.evidence} /></dd></div><div><dt className="text-slate-500">Confidence</dt><dd>{finding.confidence_percent}%</dd></div></dl></li>)}</ul>}</section>
    </main>
  );
}
