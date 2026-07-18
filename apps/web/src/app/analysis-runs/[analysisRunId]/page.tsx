"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { apiRequest } from "@/lib/api";
import type { AnalysisReport } from "@/lib/types";

function display(value: unknown): string {
  if (value === null || value === undefined || value === "") return "Not available";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

const metrics = {
  first_contentful_paint_ms: "First Contentful Paint (ms)",
  largest_contentful_paint_ms: "Largest Contentful Paint (ms)",
  total_blocking_time_ms: "Total Blocking Time (ms)",
  cumulative_layout_shift: "Cumulative Layout Shift",
  speed_index_ms: "Speed Index (ms)",
  time_to_interactive_ms: "Time to Interactive (ms)",
};

const measurements = {
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
  technology_indicators: "Technology indicators",
};

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

  return (
    <main className="mx-auto min-h-screen max-w-6xl px-6 py-12">
      <Link className="text-sm font-semibold text-slate-600" href="/projects">← Projects</Link>
      <header className="mt-6 rounded-2xl bg-slate-950 p-7 text-white">
        <p className="text-sm text-slate-300">Report {report.report_id}</p>
        <h1 className="mt-2 text-3xl font-bold">{report.website.name || "Website analysis"}</h1>
        <dl className="mt-5 grid gap-3 text-sm sm:grid-cols-2">
          <div><dt className="text-slate-400">Requested URL</dt><dd className="break-all">{report.result.requested_url}</dd></div>
          <div><dt className="text-slate-400">Final URL</dt><dd className="break-all">{report.result.final_url}</dd></div>
          <div><dt className="text-slate-400">Analysis date</dt><dd>{new Date(report.result.analysis_completed_at).toLocaleString()}</dd></div>
          <div><dt className="text-slate-400">Status</dt><dd className="capitalize">{report.analysis_status}</dd></div>
        </dl>
      </header>

      <section className="mt-6 grid gap-4 md:grid-cols-3">
        <div className="rounded-2xl border bg-white p-6"><p className="text-sm text-slate-500">Overall score</p><p className="mt-2 text-6xl font-bold">{display(report.score.overall_score)}</p><p className="mt-3 text-sm">Confidence: {report.score.confidence_percent}%</p><p className="text-sm">Formula: {report.score.formula_version}</p></div>
        <div className="grid gap-3 sm:grid-cols-2 md:col-span-2">{Object.entries(categoryScores).map(([label, score]) => <div className="rounded-xl border bg-white p-4" key={label}><p className="text-sm text-slate-500">{label}</p><p className="mt-1 text-3xl font-bold">{display(score)}</p></div>)}</div>
      </section>

      <section className="mt-6 rounded-2xl border bg-white p-6">
        <h2 className="text-xl font-bold">Score transparency</h2>
        <p className="mt-3 text-sm text-slate-600">Available weights are normalized when measurements are missing. Lighthouse findings are not deducted from Technical Quality.</p>
        <p className="mt-3 text-sm"><strong>Available:</strong> {report.score.available_categories.join(", ") || "None"}</p>
        <p className="mt-1 text-sm"><strong>Unavailable:</strong> {report.score.unavailable_categories.join(", ") || "None"}</p>
        <div className="mt-4 grid gap-2 sm:grid-cols-5">{Object.entries(report.score.weights).map(([name, weight]) => <div className="rounded-lg bg-slate-50 p-3 text-sm" key={name}>{name.replaceAll("_", " ")}: {weight}%</div>)}</div>
        <h3 className="mt-5 font-semibold">Technical Quality deductions</h3>
        {report.score.deductions.length ? <ul className="mt-2 grid gap-2">{report.score.deductions.map((item, index) => <li className="rounded-lg bg-slate-50 p-3 text-sm" key={`${String(item.finding_code)}-${index}`}>{String(item.finding_code)} · {String(item.severity)} · −{String(item.deduction_amount)}</li>)}</ul> : <p className="mt-2 text-sm text-slate-600">No eligible deductions.</p>}
      </section>

      <section className="mt-6 grid gap-6 lg:grid-cols-2">
        <div className="rounded-2xl border bg-white p-6"><h2 className="text-xl font-bold">Lighthouse metrics</h2><dl className="mt-4 grid gap-3">{Object.entries(metrics).map(([key, label]) => <div key={key}><dt className="text-sm text-slate-500">{label}</dt><dd className="font-semibold">{display(report.lighthouse_metrics[key])}</dd></div>)}</dl></div>
        <div className="rounded-2xl border bg-white p-6"><h2 className="text-xl font-bold">Page measurements</h2><dl className="mt-4 grid gap-3"><div><dt className="text-sm text-slate-500">HTTP status</dt><dd>{display(report.result.http_status_code)}</dd></div><div><dt className="text-sm text-slate-500">Page title</dt><dd>{display(report.result.page_title)}</dd></div><div><dt className="text-sm text-slate-500">Meta description</dt><dd>{display(report.result.meta_description)}</dd></div>{Object.entries(measurements).map(([key, label]) => <div key={key}><dt className="text-sm text-slate-500">{label}</dt><dd className="break-all">{display(report.playwright_measurements[key])}</dd></div>)}</dl></div>
      </section>

      <section className="mt-6 rounded-2xl border bg-white p-6"><h2 className="text-xl font-bold">Findings</h2>{report.findings.length === 0 ? <p className="mt-3 text-slate-600">No verified findings.</p> : <ul className="mt-4 grid gap-4">{report.findings.map((finding) => <li className="rounded-xl border p-4" key={finding.id}><p className="text-xs font-bold uppercase">{finding.severity} · {finding.category} · {finding.source}</p><h3 className="mt-2 font-bold">{finding.title}</h3><p className="mt-1 text-sm text-slate-600">{finding.description}</p><dl className="mt-3 grid gap-2 text-sm"><div><dt className="text-slate-500">Finding code</dt><dd>{finding.finding_code}</dd></div><div><dt className="text-slate-500">Affected URL</dt><dd className="break-all">{finding.affected_url}</dd></div><div><dt className="text-slate-500">Evidence</dt><dd className="break-all">{JSON.stringify(finding.evidence)}</dd></div><div><dt className="text-slate-500">Confidence</dt><dd>{finding.confidence_percent}%</dd></div></dl></li>)}</ul>}</section>
    </main>
  );
}
