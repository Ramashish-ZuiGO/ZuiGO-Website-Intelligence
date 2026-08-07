"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { ApiError, apiRequest } from "@/lib/api";
import type { AnalysisReport, DiagnosticGroup } from "@/lib/types";
import { PerformanceIntelligence } from "@/components/performance/PerformanceIntelligence";
import { AccessibilityIntelligence, AccessibilityData } from "@/components/accessibility/AccessibilityIntelligence";
import { ReanalysisComparisonPanel } from "@/components/comparisons/ReanalysisComparisonPanel";
import { ScoreValue } from "@/components/metrics/ScoreValue";
import { MetricRatingBadge } from "@/components/metrics/MetricRatingBadge";
import { MetricInterpretation } from "@/components/metrics/types";
import { SiteDiagnosticsPanel } from "@/components/diagnostics/SiteDiagnosticsPanel";
import { AgentExecutionPanel } from "@/components/agents/AgentExecutionPanel";
import { ScoringIntelligencePanel } from "@/components/scoring/ScoringIntelligencePanel";
import { ReportDeliveryPanel } from "@/components/reports/ReportDeliveryPanel";
import ExtractedContentPanel from "@/components/content/ExtractedContentPanel";
import type { WorkflowProgress } from "@/components/reports/types";
import { analysisComparisonApi } from "@/lib/analysis-comparison-api";

const RETRY_DELAYS_MS = [2_000, 4_000, 8_000, 15_000] as const;

function isTransientConnectionError(error: unknown): boolean {
  return (
    error instanceof TypeError ||
    (error instanceof Error &&
      /failed to fetch|networkerror|load failed/i.test(error.message))
  );
}

function startRetriedRequest<T>({
  request,
  onSuccess,
  onConnectionChange,
  onPermanentFailure,
}: {
  request: () => Promise<T>;
  onSuccess: (value: T) => void;
  onConnectionChange: (interrupted: boolean) => void;
  onPermanentFailure?: (error: unknown) => void;
}): () => void {
  let cancelled = false;
  let timer: number | undefined;
  let failureCount = 0;

  async function run() {
    try {
      const value = await request();
      if (cancelled) return;
      failureCount = 0;
      onConnectionChange(false);
      onSuccess(value);
    } catch (error) {
      if (cancelled) return;
      if (!isTransientConnectionError(error)) {
        onConnectionChange(false);
        onPermanentFailure?.(error);
        return;
      }
      onConnectionChange(true);
      const delay =
        RETRY_DELAYS_MS[Math.min(failureCount, RETRY_DELAYS_MS.length - 1)];
      failureCount += 1;
      timer = window.setTimeout(() => void run(), delay);
    }
  }

  timer = window.setTimeout(() => void run(), 0);
  return () => {
    cancelled = true;
    if (timer !== undefined) window.clearTimeout(timer);
  };
}

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

function SignalCard({ title, status, detail }: { title: string; status: string; detail?: string }) {
  const colors: Record<string, string> = {
    current: "border-emerald-300 bg-emerald-50",
    present: "border-emerald-300 bg-emerald-50",
    detected: "border-emerald-300 bg-emerald-50",
    valid: "border-emerald-300 bg-emerald-50",
    strong: "border-emerald-300 bg-emerald-50",
    good: "border-emerald-300 bg-emerald-50",
    older_than_one_year: "border-amber-300 bg-amber-50",
    possibly_outdated: "border-amber-300 bg-amber-50",
    partial: "border-amber-300 bg-amber-50",
    issues_found: "border-amber-300 bg-amber-50",
    needs_attention: "border-amber-300 bg-amber-50",
    date_not_published: "border-slate-300 bg-slate-50",
    unavailable: "border-slate-300 bg-slate-50",
    inconclusive: "border-slate-300 bg-slate-50",
    missing: "border-red-200 bg-red-50",
    weak: "border-red-200 bg-red-50",
    high_observable_risk: "border-red-200 bg-red-50",
    not_detected: "border-slate-300 bg-slate-50",
  };
  return (
    <div className={`rounded-xl border p-4 ${colors[status] ?? "border-slate-200 bg-white"}`}>
      <p className="text-sm font-semibold text-slate-700">{title}</p>
      <p className="mt-1 text-lg font-bold capitalize">{label(status)}</p>
      {detail && <p className="mt-1 text-xs text-slate-600">{detail}</p>}
    </div>
  );
}

type Obs = Record<string, unknown>;
function s(v: unknown): string { return v == null ? "" : String(v); }
function sa(v: unknown): string[] { return Array.isArray(v) ? v.map(String) : []; }

function WebsiteSignalsSection({ diagnostics }: { diagnostics: Record<string, DiagnosticGroup> }) {
  const policy = diagnostics.policy_diagnostics?.verified_observations as Obs | undefined;
  const policyDetail = (policy?.privacy_policy_detail ?? null) as Obs | null;
  const copyrightData = (diagnostics.policy_diagnostics?.copyright?.verified_observations ?? null) as Obs | null;
  const securityMatrix = diagnostics.security_diagnostics?.verified_observations?.security_header_matrix;
  const matrixItems = Array.isArray(securityMatrix) ? (securityMatrix as Obs[]) : [];
  const analyticsData = (diagnostics.analytics_diagnostics?.verified_observations ?? null) as Obs | null;
  const responsiveData = (diagnostics.responsive_diagnostics?.verified_observations ?? null) as Obs | null;

  const privacyStatus = s(policyDetail?.freshness_status || (policy?.privacy_policy ? "detected" : "unavailable"));
  const privacyDetail = policyDetail?.explicit_update_date
    ? `Updated ${s(policyDetail.explicit_update_date)}`
    : policyDetail?.found ? "Date not published" : undefined;

  const copyrightStatus = s(copyrightData?.freshness_status || "unavailable");
  const copyrightDetail = copyrightData?.raw_text ? s(copyrightData.raw_text).slice(0, 60) : undefined;

  const presentHeaders = matrixItems.filter((h) => h.status === "present" || h.status === "not_applicable").length;
  const totalHeaders = matrixItems.length;
  const headerStatus = totalHeaders === 0 ? "unavailable" : presentHeaders === totalHeaders ? "present" : presentHeaders > 0 ? "partial" : "missing";
  const headerDetail = totalHeaders > 0 ? `${presentHeaders} of ${totalHeaders} headers present` : undefined;

  const analyticsProviders = sa(analyticsData?.providers);
  const analyticsTech = sa(analyticsData?.technologies);
  const analyticsIds = sa(analyticsData?.public_identifiers);
  const analyticsStatus = analyticsData?.detected ? "detected" : "not_detected";
  const analyticsDetail = analyticsProviders.length ? analyticsProviders.join(", ") : undefined;

  const testedVp = responsiveData?.tested_viewports as number | undefined;
  const successVp = responsiveData?.successful_viewports as number | undefined;
  const responsiveStatus = testedVp == null || testedVp === 0 ? "unavailable" : successVp === testedVp ? "present" : (successVp ?? 0) > 0 ? "partial" : "missing";
  const responsiveDetail = testedVp != null && testedVp > 0 ? `${successVp ?? 0} of ${testedVp} viewports passed` : undefined;

  const htmlStdData = (diagnostics.html_standards_diagnostics?.verified_observations ?? null) as Obs | null;
  const htmlStdStatus = s(htmlStdData?.validation_status || "unavailable");
  const htmlStdScore = htmlStdData?.standards_score as number | null | undefined;
  const htmlStdDetail = htmlStdScore != null ? `Score: ${htmlStdScore}/100` : undefined;
  const htmlStdIssues = Array.isArray(htmlStdData?.issues) ? (htmlStdData.issues as Obs[]) : [];

  const secDiagObs = (diagnostics.security_diagnostics?.verified_observations ?? null) as Obs | null;
  const securityRisk = secDiagObs?.page_security_risk as Obs | null | undefined;
  const secRiskScore = securityRisk?.score as number | null | undefined;
  const secRiskBand = s(securityRisk?.risk_band || "unavailable");
  const secRiskStatus = secRiskScore != null ? secRiskBand : "unavailable";
  const secRiskDetail = secRiskScore != null ? `${secRiskScore}/100 · ${s(securityRisk?.confidence)} confidence` : undefined;
  const secRiskDeductions = Array.isArray(securityRisk?.deductions) ? (securityRisk.deductions as Obs[]) : [];

  return (
    <section className="mt-6 scroll-mt-6 rounded-2xl border bg-white p-6" id="website-signals">
      <h2 className="text-xl font-bold">Website Signals</h2>
      <p className="mt-1 text-sm text-slate-600">Evidence-based detection of privacy policy, copyright, security headers, analytics, responsiveness, HTML standards, and security posture.</p>
      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <SignalCard title="Privacy Policy" status={privacyStatus} detail={privacyDetail} />
        <SignalCard title="Copyright Year" status={copyrightStatus} detail={copyrightDetail} />
        <SignalCard title="Security Headers" status={headerStatus} detail={headerDetail} />
        <SignalCard title="Analytics / Tagging" status={analyticsStatus} detail={analyticsDetail} />
        <SignalCard title="Responsiveness" status={responsiveStatus} detail={responsiveDetail} />
        <SignalCard title="HTML Standards" status={htmlStdStatus} detail={htmlStdDetail} />
        <SignalCard title="Security & Risk" status={secRiskStatus} detail={secRiskDetail} />
      </div>
      <details className="mt-4">
        <summary className="cursor-pointer text-sm font-semibold">Technical evidence</summary>
        <div className="mt-3 grid gap-4 text-sm">
          {policyDetail && (
            <div>
              <h4 className="font-semibold">Privacy Policy</h4>
              <dl className="mt-1 grid gap-1 sm:grid-cols-2">
                <div><dt className="text-slate-500">Found</dt><dd>{policyDetail.found ? "Yes" : "No"}</dd></div>
                {policyDetail.url ? <div className="sm:col-span-2"><dt className="text-slate-500">URL</dt><dd className="break-all">{s(policyDetail.url)}</dd></div> : null}
                {policyDetail.title ? <div><dt className="text-slate-500">Title</dt><dd>{s(policyDetail.title)}</dd></div> : null}
                <div><dt className="text-slate-500">Freshness</dt><dd className="capitalize">{label(s(policyDetail.freshness_status))}</dd></div>
                {policyDetail.explicit_update_date ? <div><dt className="text-slate-500">Update date</dt><dd>{s(policyDetail.explicit_update_date)}</dd></div> : null}
                {policyDetail.age_days != null ? <div><dt className="text-slate-500">Age</dt><dd>{s(policyDetail.age_days)} days</dd></div> : null}
                {policyDetail.evidence_text ? <div className="sm:col-span-2"><dt className="text-slate-500">Evidence</dt><dd>{s(policyDetail.evidence_text)}</dd></div> : null}
              </dl>
            </div>
          )}
          {copyrightData && (
            <div>
              <h4 className="font-semibold">Copyright</h4>
              <dl className="mt-1 grid gap-1 sm:grid-cols-2">
                <div><dt className="text-slate-500">Detected</dt><dd>{copyrightData.detected ? "Yes" : "No"}</dd></div>
                {copyrightData.raw_text ? <div><dt className="text-slate-500">Text</dt><dd>{s(copyrightData.raw_text)}</dd></div> : null}
                {copyrightData.start_year ? <div><dt className="text-slate-500">Year range</dt><dd>{s(copyrightData.start_year)}{copyrightData.end_year !== copyrightData.start_year ? `–${s(copyrightData.end_year)}` : ""}</dd></div> : null}
                <div><dt className="text-slate-500">Freshness</dt><dd className="capitalize">{label(s(copyrightData.freshness_status))}</dd></div>
                {copyrightData.evidence_url ? <div className="sm:col-span-2"><dt className="text-slate-500">Evidence URL</dt><dd className="break-all">{s(copyrightData.evidence_url)}</dd></div> : null}
              </dl>
            </div>
          )}
          {matrixItems.length > 0 && (
            <div>
              <h4 className="font-semibold">Security Header Matrix</h4>
              <div className="mt-2 overflow-x-auto">
                <table className="w-full min-w-[600px] text-left text-xs">
                  <thead><tr className="border-b"><th className="p-2">Header</th><th>Status</th><th>Value</th><th>Recommendation</th></tr></thead>
                  <tbody>
                    {matrixItems.map((item) => (
                      <tr className="border-b" key={s(item.header)}>
                        <td className="p-2 font-mono">{s(item.header)}</td>
                        <td className="capitalize">{label(s(item.status))}</td>
                        <td className="max-w-48 break-all">{item.observed_value ? s(item.observed_value).slice(0, 120) : "—"}</td>
                        <td className="max-w-64">{item.recommendation ? s(item.recommendation) : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
          {analyticsData && (
            <div>
              <h4 className="font-semibold">Analytics / Tagging</h4>
              <dl className="mt-1 grid gap-1 sm:grid-cols-2">
                <div><dt className="text-slate-500">Detected</dt><dd>{analyticsData.detected ? "Yes" : "No"}</dd></div>
                {analyticsProviders.length > 0 && <div><dt className="text-slate-500">Providers</dt><dd>{analyticsProviders.join(", ")}</dd></div>}
                {analyticsTech.length > 0 && <div><dt className="text-slate-500">Technologies</dt><dd>{analyticsTech.join(", ")}</dd></div>}
                {analyticsIds.length > 0 && <div className="sm:col-span-2"><dt className="text-slate-500">Public identifiers</dt><dd className="font-mono text-xs">{analyticsIds.join(", ")}</dd></div>}
                <div><dt className="text-slate-500">Confidence</dt><dd>{s(analyticsData.confidence)}%</dd></div>
              </dl>
              <p className="mt-2 text-xs text-slate-500">Detection only. No traffic, visitors, or conversion data is reported.</p>
            </div>
          )}
          {htmlStdData && (
            <div>
              <h4 className="font-semibold">HTML Standards Validation</h4>
              <dl className="mt-1 grid gap-1 sm:grid-cols-2">
                <div><dt className="text-slate-500">Status</dt><dd className="capitalize">{label(htmlStdStatus)}</dd></div>
                <div><dt className="text-slate-500">Validator</dt><dd>{s(htmlStdData.validator_name)}</dd></div>
                {htmlStdScore != null ? <div><dt className="text-slate-500">ZuiGO HTML Standards Score</dt><dd className="font-bold">{htmlStdScore}/100</dd></div> : null}
                <div><dt className="text-slate-500">Errors</dt><dd>{s(htmlStdData.errors_count)}</dd></div>
                <div><dt className="text-slate-500">Warnings</dt><dd>{s(htmlStdData.warnings_count)}</dd></div>
              </dl>
              {htmlStdIssues.length > 0 ? (
                <div className="mt-2 overflow-x-auto">
                  <table className="w-full min-w-[500px] text-left text-xs">
                    <thead><tr className="border-b"><th className="p-2">Code</th><th>Severity</th><th>Message</th></tr></thead>
                    <tbody>
                      {htmlStdIssues.slice(0, 20).map((issue, i) => (
                        <tr className="border-b" key={i}>
                          <td className="p-2 font-mono">{s(issue.code)}</td>
                          <td className="capitalize">{s(issue.severity)}</td>
                          <td className="max-w-80">{s(issue.message)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : null}
              <p className="mt-2 text-xs text-slate-500">This is a ZuiGO HTML Standards Score, not an official W3C validation result.</p>
            </div>
          )}
          {securityRisk && secRiskScore != null ? (
            <div>
              <h4 className="font-semibold">Security & Risk Score</h4>
              <dl className="mt-1 grid gap-1 sm:grid-cols-3">
                <div><dt className="text-slate-500">Score</dt><dd className="text-lg font-bold">{secRiskScore}/100</dd></div>
                <div><dt className="text-slate-500">Risk Band</dt><dd className="capitalize">{label(secRiskBand)}</dd></div>
                <div><dt className="text-slate-500">Confidence</dt><dd className="capitalize">{s(securityRisk?.confidence)}</dd></div>
                <div><dt className="text-slate-500">Evidence Coverage</dt><dd>{s(securityRisk?.evidence_coverage)}%</dd></div>
              </dl>
              {secRiskDeductions.length > 0 ? (
                <div className="mt-2 overflow-x-auto">
                  <table className="w-full min-w-[400px] text-left text-xs">
                    <thead><tr className="border-b"><th className="p-2">Finding</th><th>Reason</th><th>Points</th></tr></thead>
                    <tbody>
                      {secRiskDeductions.map((d, i) => (
                        <tr className="border-b" key={i}>
                          <td className="p-2 font-mono">{s(d.code)}</td>
                          <td className="max-w-64">{s(d.reason)}</td>
                          <td className="text-right">-{s(d.points)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : null}
              <p className="mt-2 text-xs text-slate-500">This score reflects observable security posture only. It is not a penetration-test result and does not prove the absence of vulnerabilities.</p>
            </div>
          ) : null}
        </div>
      </details>
    </section>
  );
}

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
  const searchParams = useSearchParams();
  const projectId = searchParams.get("projectId") ?? undefined;
  const websiteId = searchParams.get("websiteId") ?? undefined;
  const workflowExecutionId = searchParams.get("workflowExecutionId") ?? undefined;
  const baselineRunId = searchParams.get("baselineRunId") ?? undefined;
  const [report, setReport] = useState<AnalysisReport | null>(null);
  const [performanceData, setPerformanceData] = useState<Record<string, unknown>[]>([]);
  const [accessibilityData, setAccessibilityData] = useState<AccessibilityData | null>(null);
  const [interpretations, setInterpretations] = useState<MetricInterpretation[]>([]);
  const [interpretationsInterrupted, setInterpretationsInterrupted] =
    useState(false);
  const [interpretationsUnavailable, setInterpretationsUnavailable] =
    useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [interruptedResources, setInterruptedResources] = useState<string[]>([]);
  const [workflowProgress, setWorkflowProgress] = useState<WorkflowProgress | null>(
    null,
  );
  const [currentReportAvailable, setCurrentReportAvailable] = useState(false);
  const [baselineAvailable, setBaselineAvailable] = useState(false);
  const [comparisonDataAvailable, setComparisonDataAvailable] = useState(false);

  const setResourceInterrupted = useCallback(
    (resource: string, interrupted: boolean) => {
      setInterruptedResources((current) =>
        interrupted
          ? current.includes(resource)
            ? current
            : [...current, resource]
          : current.filter((item) => item !== resource),
      );
    },
    [],
  );
  const handleProgressChange = useCallback((value: WorkflowProgress) => {
    setWorkflowProgress(value);
  }, []);
  const handleReportAvailabilityChange = useCallback((available: boolean) => {
    setCurrentReportAvailable(available);
  }, []);

  useEffect(
    () =>
      startRetriedRequest({
        request: () =>
          apiRequest<AnalysisReport>(
            `/api/v1/analysis-runs/${analysisRunId}/report`,
          ),
        onSuccess: (loaded) => {
          setReport(loaded);
          setError(null);
          setLoading(false);
        },
        onConnectionChange: (interrupted) =>
          setResourceInterrupted("analysis-report", interrupted),
        onPermanentFailure: (requestError) => {
          setLoading(false);
          if (
            workflowExecutionId &&
            requestError instanceof ApiError &&
            requestError.status === 404
          ) {
            return;
          }
          setError(
            requestError instanceof Error
              ? requestError.message
              : "Unable to load report.",
          );
        },
      }),
    [analysisRunId, setResourceInterrupted, workflowExecutionId],
  );

  useEffect(
    () =>
      startRetriedRequest({
        request: () =>
          apiRequest<{ data?: Record<string, unknown>[] }>(
            `/api/v1/analysis-runs/${analysisRunId}/performance`,
          ),
        onSuccess: (response) =>
          setPerformanceData(response.data ?? []),
        onConnectionChange: (interrupted) =>
          setResourceInterrupted("performance", interrupted),
      }),
    [analysisRunId, setResourceInterrupted],
  );

  useEffect(() => {
    if (!report) return;
    const stopInterpretations = startRetriedRequest({
      request: () =>
        apiRequest<MetricInterpretation[]>(
          `/api/v1/websites/${report.website.id}/metric-interpretations`,
        ),
      onSuccess: (loaded) => {
        setInterpretations(loaded);
        setInterpretationsInterrupted(false);
        setInterpretationsUnavailable(false);
      },
      onConnectionChange: setInterpretationsInterrupted,
      onPermanentFailure: () => {
        setInterpretationsInterrupted(false);
        setInterpretationsUnavailable(true);
      },
    });
    const stopAccessibility = startRetriedRequest({
      request: () =>
        apiRequest<AccessibilityData>(
          `/api/v1/websites/${report.website.id}/accessibility`,
        ),
      onSuccess: setAccessibilityData,
      onConnectionChange: (interrupted) =>
        setResourceInterrupted("accessibility", interrupted),
    });
    return () => {
      stopInterpretations();
      stopAccessibility();
    };
  }, [report, setResourceInterrupted]);

  useEffect(() => {
    if (!baselineRunId) return;
    return startRetriedRequest({
      request: () => analysisComparisonApi.settings(baselineRunId),
      onSuccess: (settings) =>
        setBaselineAvailable(
          settings.baseline_analysis_run_id === baselineRunId,
        ),
      onConnectionChange: (interrupted) =>
        setResourceInterrupted("comparison-baseline", interrupted),
      onPermanentFailure: () => setBaselineAvailable(false),
    });
  }, [baselineRunId, setResourceInterrupted]);

  const comparisonTerminal = Boolean(
    workflowProgress &&
      ["completed", "partial"].includes(workflowProgress.status),
  );
  const essentialConnectionInterrupted =
    interruptedResources.includes("analysis-report");

  useEffect(() => {
    if (
      !baselineRunId ||
      !baselineAvailable ||
      !comparisonTerminal ||
      !currentReportAvailable
    ) {
      return;
    }
    return startRetriedRequest({
      request: async () => {
        try {
          return await analysisComparisonApi.detail(
            analysisRunId,
            baselineRunId,
          );
        } catch (requestError) {
          if (!(requestError instanceof ApiError) || requestError.status !== 404) {
            throw requestError;
          }
          return analysisComparisonApi.generate(
            analysisRunId,
            baselineRunId,
            `comparison-${analysisRunId}-${baselineRunId}`,
          );
        }
      },
      onSuccess: (comparison) =>
        setComparisonDataAvailable(
          ["completed", "partial"].includes(comparison.status),
        ),
      onConnectionChange: (interrupted) =>
        setResourceInterrupted("comparison-data", interrupted),
      onPermanentFailure: () => setComparisonDataAvailable(false),
    });
  }, [
    analysisRunId,
    baselineAvailable,
    baselineRunId,
    comparisonTerminal,
    currentReportAvailable,
    setResourceInterrupted,
  ]);

  if (!report && websiteId && workflowExecutionId) {
    return (
      <main className="mx-auto min-h-screen max-w-6xl px-6 py-12">
        <Link className="text-sm font-semibold text-slate-600" href="/">
          ← Start another analysis
        </Link>
        <h1 className="mt-6 text-3xl font-bold">Website analysis in progress</h1>
        <p className="mt-2 text-slate-600">
          Real evidence is being collected from the submitted website. No prepared
          demo evidence is used in this analysis.
        </p>
        {essentialConnectionInterrupted && (
          <p className="mt-4 text-sm text-amber-800" role="status">
            Connection interrupted — retrying
          </p>
        )}
        {loading && <p className="mt-4" role="status">Loading analysis progress…</p>}
        {error && (
          <p className="mt-4 text-amber-800" role="status">
            The final report is not available yet. Progress and safe recovery actions
            remain available below.
          </p>
        )}
        <ReportDeliveryPanel
          analysisRunId={analysisRunId}
          onProgressChange={handleProgressChange}
          onReportAvailabilityChange={handleReportAvailabilityChange}
          projectId={projectId}
          showStartAction={false}
          websiteId={websiteId}
          workflowExecutionId={workflowExecutionId}
        />
      </main>
    );
  }
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
  const comparisonReady = Boolean(
    baselineRunId &&
      baselineAvailable &&
      comparisonTerminal &&
      currentReportAvailable &&
      comparisonDataAvailable,
  );

  return (
    <main className="mx-auto min-h-screen max-w-6xl px-6 py-12">
      <Link className="text-sm font-semibold text-slate-600" href="/projects">← Projects</Link>
      <header className="mt-6 rounded-2xl bg-slate-950 p-7 text-white">
        <h1 className="text-3xl font-bold">{report.website.name || "Website analysis"}</h1>
        <dl className="mt-5 grid gap-3 text-sm sm:grid-cols-2">
          <div><dt className="text-slate-400">Requested URL</dt><dd className="break-all">{report.result.requested_url}</dd></div>
          <div><dt className="text-slate-400">Final URL</dt><dd className="break-all">{report.result.final_url}</dd></div>
          <div><dt className="text-slate-400">Analysis date</dt><dd>{new Date(report.result.analysis_completed_at).toLocaleString()}</dd></div>
          <div><dt className="text-slate-400">Status</dt><dd className="capitalize">{report.analysis_status}</dd></div>
        </dl>
        <details className="mt-5 rounded-lg border border-slate-700 p-3">
          <summary className="cursor-pointer text-sm font-semibold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white">
            Technical identifiers
          </summary>
          <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-2">
            <div><dt className="text-slate-400">Analysis run</dt><dd className="flex items-center gap-2 break-all">{report.analysis_run_id}<CopyId value={report.analysis_run_id} /></dd></div>
            <div><dt className="text-slate-400">Legacy report</dt><dd className="flex items-center gap-2 break-all">{report.report_id}<CopyId value={report.report_id} /></dd></div>
          </dl>
        </details>
      </header>

      {essentialConnectionInterrupted && (
        <p className="mt-4 text-sm text-amber-800" role="status">
          Connection interrupted — retrying
        </p>
      )}

      {baselineRunId && (
        <section className="mt-6 rounded-2xl border border-emerald-300 bg-emerald-50 p-6">
          <h2 className="text-xl font-bold">
            {comparisonReady
              ? "Reanalysis evidence is ready"
              : comparisonTerminal
                ? "Preparing comparison evidence"
                : "Reanalysis in progress"}
          </h2>
          <p className="mt-2 text-sm text-slate-700">
            {comparisonReady
              ? "The current run is terminal, its report evidence is available, and the preserved baseline is ready."
              : comparisonTerminal
                ? "The run has finished, but comparison evidence is not available yet."
                : "Comparison becomes available after the new run finishes and its evidence is retained."}
          </p>
          {comparisonReady && (
            <Link
              className="mt-4 inline-block rounded-lg bg-emerald-800 px-4 py-2 font-semibold text-white"
              href={`/analysis-runs/${analysisRunId}/compare/${baselineRunId}`}
            >
              Compare with baseline
            </Link>
          )}
        </section>
      )}

      <ReanalysisComparisonPanel
        analysisRunId={analysisRunId}
        projectId={projectId}
      />

      <section className="mt-8" id={`report-delivery-${report.website.id}`}>
        <h2 className="mb-4 text-2xl font-bold">Final reports and exports</h2>
        <ReportDeliveryPanel
          analysisRunId={analysisRunId}
          onProgressChange={handleProgressChange}
          onReportAvailabilityChange={handleReportAvailabilityChange}
          projectId={projectId}
          showStartAction={false}
          websiteId={report.website.id}
          workflowExecutionId={workflowExecutionId}
        />
      </section>

      <details className="mt-8 rounded-2xl border bg-slate-50 p-5">
        <summary className="cursor-pointer text-lg font-bold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-700">
          Additional technical evidence
        </summary>
        <div className="mt-5">

      <section className="rounded-2xl border bg-white p-6">
        <ExtractedContentPanel analysisRunId={analysisRunId} />
      </section>

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

      <section className="mt-6 grid scroll-mt-6 gap-4 md:grid-cols-3" id="score-overview">
        {(interpretationsInterrupted || interpretationsUnavailable) && (
          <p
            className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 md:col-span-3"
            role="status"
          >
            {interpretationsInterrupted
              ? "Metric interpretation help is temporarily unavailable — retrying. Scores and report evidence remain available."
              : "Metric interpretation help is unavailable for this report. Scores and report evidence remain available."}
          </p>
        )}
        <div className="rounded-2xl border bg-white p-6">
          <div className="flex items-start justify-between">
            <p className="text-sm text-slate-500">Overall score</p>
            <MetricRatingBadge interpretation={interpretations.find(i => i.metric_id === "overall_score")} />
          </div>
          <p className="mt-2 text-6xl font-bold"><ScoreValue metricId="overall_score" value={report.score.overall_score} /></p>
          <p className="mt-3 text-sm">Confidence: {report.score.confidence_percent}%</p>
          <p className="text-sm">Formula: {report.score.formula_version}</p>
        </div>

        <div className="grid gap-3 sm:grid-cols-2 md:col-span-2">
          {Object.entries(categoryScores).map(([name, score]) => {
            const mId = name.toLowerCase().replace(" ", "_") + "_score";
            return (
              <div className="rounded-xl border bg-white p-4" key={name}>
                <div className="flex items-start justify-between">
                  <p className="text-sm text-slate-500">{name}</p>
                  <MetricRatingBadge interpretation={interpretations.find(i => i.metric_id === mId)} />
                </div>
                <p className="mt-1 text-3xl font-bold"><ScoreValue metricId={mId} value={score} /></p>
              </div>
            );
          })}
        </div>
      </section>

      <section className="mt-6 rounded-2xl border bg-white p-6">
        <h2 className="text-xl font-bold">Score transparency</h2>
        <p className="mt-3 text-sm text-slate-600">Available weights are normalized when measurements are missing. Lighthouse findings are not deducted from Technical Quality.</p>
        <p className="mt-3 text-sm"><strong>Available:</strong> {report.score.available_categories.join(", ") || "None"}</p>
        <p className="mt-1 text-sm"><strong>Unavailable:</strong> {report.score.unavailable_categories.join(", ") || "None"}</p>
        <h3 className="mt-5 font-semibold">Technical Quality deductions</h3>
        {report.score.deductions.length ? <HumanValue value={report.score.deductions} /> : <p className="mt-2 text-sm text-slate-600">No eligible deductions.</p>}
      </section>

      <section className="mt-6">
        <AccessibilityIntelligence accessibilityData={accessibilityData} />
      </section>

      <WebsiteSignalsSection diagnostics={report.diagnostics} />

      <section className="mt-6 grid scroll-mt-6 gap-5" id="verified-diagnostics">
        <h2 className="text-2xl font-bold">Verified diagnostics</h2>
        {diagnostics.map(([name, diagnostic]) => <DiagnosticCard diagnostic={diagnostic} key={name} name={name} />)}
      </section>

      <section className="mt-6 grid gap-6 lg:grid-cols-2">
        <div className="rounded-2xl border bg-white p-6">
          <h2 className="text-xl font-bold">Lighthouse metrics</h2>
          <dl className="mt-4 grid gap-3">
            {Object.entries(metricLabels).map(([key, name]) => (
              <div key={key}>
                <dt className="text-sm text-slate-500 flex items-center gap-2">
                  {name}
                  <MetricRatingBadge interpretation={interpretations.find(i => i.metric_id === key.replace('_ms', ''))} />
                </dt>
                <dd className="font-semibold">{display(report.lighthouse_metrics[key])}</dd>
                {key === "time_to_interactive_ms" && <p className="text-xs text-slate-500">Legacy/supplementary; not a current Core Web Vital and not necessarily included in the performance score.</p>}
              </div>
            ))}
          </dl>
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

      <div className="mt-8">
        <SiteDiagnosticsPanel
          analysisRunId={analysisRunId}
          restrictToAnalysisRun
          websiteId={report.website.id}
        />
      </div>

      <section className="mt-6" id={`agent-execution-${report.website.id}`}>
        <h2 className="mb-4 text-2xl font-bold">Agent execution</h2>
        <AgentExecutionPanel
          analysisRunId={analysisRunId}
          websiteId={report.website.id}
        />
      </section>
      <section className="mt-6" id={`scoring-intelligence-${report.website.id}`}>
        <h2 className="mb-4 text-2xl font-bold">Score explanation</h2>
        <ScoringIntelligencePanel
          analysisRunId={analysisRunId}
          websiteId={report.website.id}
        />
      </section>

      <div className="mt-8">
        <PerformanceIntelligence data={performanceData as unknown as { id: string; metric_id: string; evidence_type: string; raw_value: number }[]} />
      </div>
        </div>
      </details>
    </main>
  );
}
