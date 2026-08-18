"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { ApiError, apiRequest } from "@/lib/api";
import type { AnalysisReport, AnalysisFinding, AnalysisStatus, DiagnosticGroup } from "@/lib/types";
import { QUALITY_STYLES, type ReportQuality } from "@/lib/report-quality";
import { PerformanceIntelligence } from "@/components/performance/PerformanceIntelligence";
import {
  AccessibilityIntelligence,
  AccessibilityData,
} from "@/components/accessibility/AccessibilityIntelligence";
import { ReanalysisComparisonPanel } from "@/components/comparisons/ReanalysisComparisonPanel";
import { ScoreValue } from "@/components/metrics/ScoreValue";
import { MetricRatingBadge } from "@/components/metrics/MetricRatingBadge";
import { MetricInterpretation } from "@/components/metrics/types";
import { SiteDiagnosticsPanel } from "@/components/diagnostics/SiteDiagnosticsPanel";
import { AgentExecutionPanel } from "@/components/agents/AgentExecutionPanel";
import { ScoringIntelligencePanel } from "@/components/scoring/ScoringIntelligencePanel";
import { ReportDeliveryPanel } from "@/components/reports/ReportDeliveryPanel";
import ExtractedContentPanel from "@/components/content/ExtractedContentPanel";
import { SectionErrorBoundary } from "@/components/SectionErrorBoundary";
import { BrowserUatPanel } from "@/components/browser-uat/BrowserUatPanel";
import type { WorkflowProgress } from "@/components/reports/types";
import { analysisComparisonApi } from "@/lib/analysis-comparison-api";
import { ENGINE_LABELS } from "@/lib/browser-engines";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { ScoreBar } from "@/components/ui/ScoreBadge";
import { UrlCell } from "@/components/ui/UrlCell";
import { EmptyState } from "@/components/ui/EmptyState";
import { MetricStat } from "@/components/ui/MetricStat";
import { IssueRegister } from "@/components/findings/IssueRegister";
import { ConceptInfoButton } from "@/components/metrics/ConceptInfoButton";
// ---------------------------------------------------------------------------
// Retry infrastructure (unchanged from previous)
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Utility helpers
// ---------------------------------------------------------------------------

function display(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number")
    return Number.isInteger(value) ? String(value) : value.toFixed(2);
  return String(value);
}

function formatLabel(value: string | null | undefined): string {
  if (!value) return "Unknown";
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

type Obs = Record<string, unknown>;
function s(v: unknown): string {
  return v == null ? "" : String(v);
}
function sa(v: unknown): string[] {
  return Array.isArray(v) ? v.map(String) : [];
}
function num(v: unknown): number {
  return typeof v === "number" ? v : 0;
}

// ---------------------------------------------------------------------------
// Signal card — used in Website Signals section
// ---------------------------------------------------------------------------

const SIGNAL_COLORS: Record<string, string> = {
  current: "border-emerald-200 bg-emerald-50/60",
  present: "border-emerald-200 bg-emerald-50/60",
  detected: "border-emerald-200 bg-emerald-50/60",
  valid: "border-emerald-200 bg-emerald-50/60",
  strong: "border-emerald-200 bg-emerald-50/60",
  good: "border-emerald-200 bg-emerald-50/60",
  older_than_one_year: "border-amber-200 bg-amber-50/60",
  possibly_outdated: "border-amber-200 bg-amber-50/60",
  partial: "border-amber-200 bg-amber-50/60",
  issues_found: "border-amber-200 bg-amber-50/60",
  needs_attention: "border-amber-200 bg-amber-50/60",
  date_not_published: "border-slate-200 bg-slate-50",
  unavailable: "border-slate-200 bg-slate-50",
  inconclusive: "border-slate-200 bg-slate-50",
  missing: "border-red-200 bg-red-50/60",
  weak: "border-red-200 bg-red-50/60",
  high_observable_risk: "border-red-200 bg-red-50/60",
  not_detected: "border-slate-200 bg-slate-50",
};

const SIGNAL_ICONS: Record<string, string> = {
  current: "text-emerald-600",
  present: "text-emerald-600",
  detected: "text-emerald-600",
  valid: "text-emerald-600",
  strong: "text-emerald-600",
  good: "text-emerald-600",
  partial: "text-amber-600",
  needs_attention: "text-amber-600",
  missing: "text-red-600",
  weak: "text-red-600",
  high_observable_risk: "text-red-600",
};

function SignalCard({
  title,
  status,
  detail,
  metric,
}: {
  title: string;
  status: string;
  detail?: string;
  metric?: string;
}) {
  const color =
    SIGNAL_COLORS[status] ?? "border-slate-200 bg-white";
  const iconColor = SIGNAL_ICONS[status] ?? "text-slate-400";
  const isPositive = [
    "current",
    "present",
    "detected",
    "valid",
    "strong",
    "good",
  ].includes(status);

  return (
    <div className={`rounded-lg border p-3 ${color}`}>
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm font-medium text-slate-700">{title}</p>
        <span className={`text-sm ${iconColor}`}>
          {isPositive ? "✓" : status === "missing" || status === "weak" ? "✗" : "—"}
        </span>
      </div>
      {metric && (
        <p className="mt-1 text-lg font-bold text-slate-900">{metric}</p>
      )}
      {!metric && (
        <p className="mt-1 text-sm font-semibold capitalize text-slate-800">
          {formatLabel(status)}
        </p>
      )}
      {detail && (
        <p className="mt-0.5 text-xs text-slate-500">{detail}</p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Website Signals section (Executive View)
// ---------------------------------------------------------------------------

function WebsiteSignalsSection({
  diagnostics,
}: {
  diagnostics: Record<string, DiagnosticGroup>;
}) {
  const policy = diagnostics.policy_diagnostics?.verified_observations as
    | Obs
    | undefined;
  const policyDetail = (policy?.privacy_policy_detail ?? null) as Obs | null;
  const copyrightData = (diagnostics.policy_diagnostics?.copyright
    ?.verified_observations ?? null) as Obs | null;
  const securityMatrix = diagnostics.security_diagnostics?.verified_observations
    ?.security_header_matrix;
  const matrixItems = Array.isArray(securityMatrix)
    ? (securityMatrix as Obs[])
    : [];
  const analyticsData = (diagnostics.analytics_diagnostics
    ?.verified_observations ?? null) as Obs | null;
  const responsiveData = (diagnostics.responsive_diagnostics
    ?.verified_observations ?? null) as Obs | null;
  const htmlStdData = (diagnostics.html_standards_diagnostics
    ?.verified_observations ?? null) as Obs | null;
  const secDiagObs = (diagnostics.security_diagnostics?.verified_observations ??
    null) as Obs | null;
  const securityRisk = secDiagObs?.page_security_risk as Obs | null | undefined;

  const privacyStatus = s(
    policyDetail?.freshness_status ||
      (policy?.privacy_policy ? "detected" : "unavailable"),
  );
  const privacyDetail = policyDetail?.explicit_update_date
    ? `Updated ${s(policyDetail.explicit_update_date)}`
    : policyDetail?.found
      ? "Date not published"
      : undefined;

  const copyrightStatus = s(copyrightData?.freshness_status || "unavailable");
  const copyrightDetail = copyrightData?.raw_text
    ? s(copyrightData.raw_text).slice(0, 60)
    : undefined;

  const presentHeaders = matrixItems.filter(
    (h) => h.status === "present" || h.status === "not_applicable",
  ).length;
  const totalHeaders = matrixItems.length;
  const headerStatus =
    totalHeaders === 0
      ? "unavailable"
      : presentHeaders === totalHeaders
        ? "present"
        : presentHeaders > 0
          ? "partial"
          : "missing";

  const analyticsProviders = sa(analyticsData?.providers);
  const analyticsStatus = analyticsData?.detected ? "detected" : "not_detected";

  const testedVp = responsiveData?.tested_viewports as number | undefined;
  const successVp = responsiveData?.successful_viewports as number | undefined;
  const responsiveStatus =
    testedVp == null || testedVp === 0
      ? "unavailable"
      : successVp === testedVp
        ? "present"
        : (successVp ?? 0) > 0
          ? "partial"
          : "missing";

  const htmlStdScore = htmlStdData?.standards_score as
    | number
    | null
    | undefined;
  const htmlStdStatus = s(htmlStdData?.validation_status || "unavailable");
  const secRiskScore = securityRisk?.score as number | null | undefined;
  const secRiskBand = s(securityRisk?.risk_band || "unavailable");

  return (
    <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
      <SignalCard
        title="Privacy Policy"
        status={privacyStatus}
        detail={privacyDetail}
      />
      <SignalCard
        title="Copyright"
        status={copyrightStatus}
        detail={copyrightDetail}
      />
      <SignalCard
        title="Security Headers"
        status={headerStatus}
        metric={
          totalHeaders > 0
            ? `${presentHeaders} / ${totalHeaders}`
            : undefined
        }
        detail={totalHeaders > 0 ? "headers present" : undefined}
      />
      <SignalCard
        title="Analytics"
        status={analyticsStatus}
        detail={
          analyticsProviders.length > 0
            ? analyticsProviders.join(", ")
            : undefined
        }
      />
      <SignalCard
        title="Responsiveness"
        status={responsiveStatus}
        metric={
          testedVp != null && testedVp > 0
            ? `${successVp ?? 0} / ${testedVp}`
            : undefined
        }
        detail={
          testedVp != null && testedVp > 0 ? "viewports passed" : undefined
        }
      />
      <SignalCard
        title="HTML Quality"
        status={htmlStdStatus}
        metric={htmlStdScore != null ? `${htmlStdScore} / 100` : undefined}
        detail="ZuiGO structural score"
      />
      <SignalCard
        title="Passive Security Posture"
        status={secRiskScore != null ? secRiskBand : "unavailable"}
        metric={secRiskScore != null ? `${secRiskScore} / 100` : undefined}
        detail={
          secRiskScore != null
            ? `${s(securityRisk?.confidence)} confidence`
            : undefined
        }
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Website Signals technical evidence (Technical View)
// ---------------------------------------------------------------------------

function WebsiteSignalsTechnicalEvidence({
  diagnostics,
}: {
  diagnostics: Record<string, DiagnosticGroup>;
}) {
  const policy = diagnostics.policy_diagnostics?.verified_observations as
    | Obs
    | undefined;
  const policyDetail = (policy?.privacy_policy_detail ?? null) as Obs | null;
  const copyrightData = (diagnostics.policy_diagnostics?.copyright
    ?.verified_observations ?? null) as Obs | null;
  const securityMatrix = diagnostics.security_diagnostics?.verified_observations
    ?.security_header_matrix;
  const matrixItems = Array.isArray(securityMatrix)
    ? (securityMatrix as Obs[])
    : [];
  const analyticsData = (diagnostics.analytics_diagnostics
    ?.verified_observations ?? null) as Obs | null;
  const htmlStdData = (diagnostics.html_standards_diagnostics
    ?.verified_observations ?? null) as Obs | null;
  const htmlStdIssues = Array.isArray(htmlStdData?.issues)
    ? (htmlStdData.issues as Obs[])
    : [];
  const secDiagObs = (diagnostics.security_diagnostics?.verified_observations ??
    null) as Obs | null;
  const securityRisk = secDiagObs?.page_security_risk as Obs | null | undefined;
  const secRiskDeductions = Array.isArray(securityRisk?.deductions)
    ? (securityRisk.deductions as Obs[])
    : [];
  const analyticsProviders = sa(analyticsData?.providers);
  const analyticsTech = sa(analyticsData?.technologies);
  const analyticsIds = sa(analyticsData?.public_identifiers);

  return (
    <div className="grid gap-6 text-sm">
      {!!policyDetail && (
        <div>
          <h4 className="font-semibold text-slate-900">Privacy Policy</h4>
          <dl className="mt-2 grid gap-x-6 gap-y-1 sm:grid-cols-2">
            <div>
              <dt className="text-slate-500">Found</dt>
              <dd>{policyDetail.found ? "Yes" : "No"}</dd>
            </div>
            {policyDetail.url ? (
              <div className="sm:col-span-2">
                <dt className="text-slate-500">URL</dt>
                <dd>
                  <UrlCell url={s(policyDetail.url)} />
                </dd>
              </div>
            ) : null}
            <div>
              <dt className="text-slate-500">Freshness</dt>
              <dd className="capitalize">{formatLabel(s(policyDetail.freshness_status))}</dd>
            </div>
            {policyDetail.explicit_update_date ? (
              <div>
                <dt className="text-slate-500">Update date</dt>
                <dd>{s(policyDetail.explicit_update_date)}</dd>
              </div>
            ) : null}
            {policyDetail.age_days != null ? (
              <div>
                <dt className="text-slate-500">Age</dt>
                <dd>{s(policyDetail.age_days)} days</dd>
              </div>
            ) : null}
          </dl>
        </div>
      )}

      {!!copyrightData && (
        <div>
          <h4 className="font-semibold text-slate-900">Copyright</h4>
          <dl className="mt-2 grid gap-x-6 gap-y-1 sm:grid-cols-2">
            <div>
              <dt className="text-slate-500">Detected</dt>
              <dd>{copyrightData.detected ? "Yes" : "No"}</dd>
            </div>
            {copyrightData.raw_text ? (
              <div>
                <dt className="text-slate-500">Text</dt>
                <dd>{s(copyrightData.raw_text)}</dd>
              </div>
            ) : null}
            {copyrightData.start_year ? (
              <div>
                <dt className="text-slate-500">Year range</dt>
                <dd>
                  {s(copyrightData.start_year)}
                  {copyrightData.end_year !== copyrightData.start_year
                    ? `–${s(copyrightData.end_year)}`
                    : ""}
                </dd>
              </div>
            ) : null}
            <div>
              <dt className="text-slate-500">Freshness</dt>
              <dd className="capitalize">
                {formatLabel(s(copyrightData.freshness_status))}
              </dd>
            </div>
          </dl>
        </div>
      )}

      {matrixItems.length > 0 && (
        <div>
          <h4 className="font-semibold text-slate-900">Security Header Matrix</h4>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full min-w-[600px] text-left text-xs">
              <thead>
                <tr className="border-b border-slate-200">
                  <th className="pb-2 pr-3 font-semibold text-slate-500">Header</th>
                  <th className="pb-2 pr-3 font-semibold text-slate-500">Status</th>
                  <th className="pb-2 pr-3 font-semibold text-slate-500">Value</th>
                  <th className="pb-2 font-semibold text-slate-500">Recommendation</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {matrixItems.map((item) => (
                  <tr key={s(item.header)}>
                    <td className="py-1.5 pr-3 font-mono text-xs">
                      {s(item.header)}
                    </td>
                    <td className="py-1.5 pr-3">
                      <StatusBadge status={s(item.status)} size="xs" />
                    </td>
                    <td className="max-w-48 break-all py-1.5 pr-3">
                      {item.observed_value
                        ? s(item.observed_value).slice(0, 120)
                        : "—"}
                    </td>
                    <td className="max-w-64 py-1.5">
                      {item.recommendation ? s(item.recommendation) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {!!analyticsData && (
        <div>
          <h4 className="font-semibold text-slate-900">Analytics / Tagging</h4>
          <dl className="mt-2 grid gap-x-6 gap-y-1 sm:grid-cols-2">
            <div>
              <dt className="text-slate-500">Detected</dt>
              <dd>{analyticsData.detected ? "Yes" : "No"}</dd>
            </div>
            {analyticsProviders.length > 0 && (
              <div>
                <dt className="text-slate-500">Providers</dt>
                <dd>{analyticsProviders.join(", ")}</dd>
              </div>
            )}
            {analyticsTech.length > 0 && (
              <div>
                <dt className="text-slate-500">Technologies</dt>
                <dd>{analyticsTech.join(", ")}</dd>
              </div>
            )}
            {analyticsIds.length > 0 && (
              <div className="sm:col-span-2">
                <dt className="text-slate-500">Public identifiers</dt>
                <dd className="font-mono text-xs">
                  {analyticsIds.join(", ")}
                </dd>
              </div>
            )}
          </dl>
          <p className="mt-2 text-xs text-slate-400">
            Detection only. No traffic, visitors, or conversion data is
            reported.
          </p>
        </div>
      )}

      {!!htmlStdData && htmlStdIssues.length > 0 && (
        <div>
          <h4 className="font-semibold text-slate-900">
            HTML Standards Issues ({htmlStdIssues.length})
          </h4>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full min-w-[500px] text-left text-xs">
              <thead>
                <tr className="border-b border-slate-200">
                  <th className="pb-2 pr-3 font-semibold text-slate-500">Code</th>
                  <th className="pb-2 pr-3 font-semibold text-slate-500">Severity</th>
                  <th className="pb-2 font-semibold text-slate-500">Message</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {htmlStdIssues.slice(0, 20).map((issue, i) => (
                  <tr key={i}>
                    <td className="py-1.5 pr-3 font-mono">{s(issue.code)}</td>
                    <td className="py-1.5 pr-3">
                      <StatusBadge status={s(issue.severity)} size="xs" />
                    </td>
                    <td className="max-w-80 py-1.5">{s(issue.message)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-xs text-slate-400">
            ZuiGO HTML Standards Score, not an official W3C validation result.
          </p>
        </div>
      )}

      {!!securityRisk && (securityRisk.score as number) != null && (
        <div>
          <h4 className="font-semibold text-slate-900">Security & Risk Detail</h4>
          <dl className="mt-2 grid gap-x-6 gap-y-1 sm:grid-cols-3">
            <div>
              <dt className="text-slate-500">Score</dt>
              <dd className="text-lg font-bold">
                {s(securityRisk.score)}/100
              </dd>
            </div>
            <div>
              <dt className="text-slate-500">Risk Band</dt>
              <dd className="capitalize">
                {formatLabel(s(securityRisk.risk_band))}
              </dd>
            </div>
            <div>
              <dt className="text-slate-500">Confidence</dt>
              <dd className="capitalize">{s(securityRisk.confidence)}</dd>
            </div>
          </dl>
          {secRiskDeductions.length > 0 && (
            <div className="mt-3 overflow-x-auto">
              <table className="w-full min-w-[400px] text-left text-xs">
                <thead>
                  <tr className="border-b border-slate-200">
                    <th className="pb-2 pr-3 font-semibold text-slate-500">Finding</th>
                    <th className="pb-2 pr-3 font-semibold text-slate-500">Reason</th>
                    <th className="pb-2 text-right font-semibold text-slate-500">Points</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {secRiskDeductions.map((d, i) => (
                    <tr key={i}>
                      <td className="py-1.5 pr-3 font-mono">{s(d.code)}</td>
                      <td className="max-w-64 py-1.5 pr-3">{s(d.reason)}</td>
                      <td className="py-1.5 text-right text-red-600">
                        -{s(d.points)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="mt-2 text-xs text-slate-400">
            Observable security posture only. Not a penetration-test result.
          </p>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Grouped findings for executive view — deduplicate by finding_code
// ---------------------------------------------------------------------------

interface GroupedFinding {
  finding_code: string;
  title: string;
  description: string;
  severity: string;
  category: string;
  totalOccurrences: number;
  affectedUrls: Set<string>;
  confidence: number;
  ids: string[];
}

function groupFindings(findings: AnalysisFinding[]): GroupedFinding[] {
  const groups = new Map<string, GroupedFinding>();
  for (const f of findings) {
    const existing = groups.get(f.finding_code);
    if (existing) {
      existing.totalOccurrences += 1;
      existing.affectedUrls.add(f.affected_url);
      existing.ids.push(f.id);
    } else {
      groups.set(f.finding_code, {
        finding_code: f.finding_code,
        title: f.title,
        description: f.description,
        severity: f.severity,
        category: f.category,
        totalOccurrences: 1,
        affectedUrls: new Set([f.affected_url]),
        confidence: f.confidence_percent,
        ids: [f.id],
      });
    }
  }
  const severityOrder: Record<string, number> = {
    critical: 0,
    high: 1,
    medium: 2,
    low: 3,
    informational: 4,
  };
  return [...groups.values()].sort(
    (a, b) =>
      (severityOrder[a.severity] ?? 5) - (severityOrder[b.severity] ?? 5) ||
      b.affectedUrls.size - a.affectedUrls.size,
  );
}

// ---------------------------------------------------------------------------
// Diagnostic card (Technical View)
// ---------------------------------------------------------------------------

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

function HumanValue({ value }: { value: unknown }) {
  if (Array.isArray(value)) {
    if (!value.length) return <span className="text-slate-400">None observed</span>;
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
        {Object.entries(value as Record<string, unknown>).map(
          ([key, nested]) => (
            <div className="min-w-0" key={key}>
              <dt className="text-xs font-medium text-slate-500">
                {formatLabel(key)}
              </dt>
              <dd className="break-words text-sm">
                <HumanValue value={nested} />
              </dd>
            </div>
          ),
        )}
      </dl>
    );
  }
  return <span>{display(value)}</span>;
}

// ---------------------------------------------------------------------------
// Browser compatibility — executive-friendly presentation
// ---------------------------------------------------------------------------

const BRANDED_BROWSERS: {
  browser: string;
  engine: string;
  versionScope: string;
  platforms: string;
}[] = [
  {
    browser: "Google Chrome",
    engine: "chromium",
    versionScope: "Latest 2 stable versions",
    platforms: "Windows 10/11, macOS 13+, Android 12+",
  },
  {
    browser: "Microsoft Edge",
    engine: "chromium",
    versionScope: "Latest 2 stable versions",
    platforms: "Windows 10/11",
  },
  {
    browser: "Apple Safari",
    engine: "webkit",
    versionScope: "16.4+",
    platforms: "macOS 13+, iOS 16+",
  },
];

function BrowserSummary({
  diagnostics,
  viewMode,
}: {
  diagnostics: Record<string, DiagnosticGroup>;
  viewMode: "executive" | "technical";
}) {
  const bcDiag = diagnostics.browser_compatibility;
  const obs = bcDiag?.verified_observations as Obs | undefined;
  const engines = Array.isArray(obs?.engines_tested)
    ? (obs.engines_tested as Obs[])
    : [];

  const engineMap: Record<string, Obs> = {};
  for (const eng of engines) {
    engineMap[s(eng.engine)] = eng;
  }

  if (viewMode === "technical") {
    if (engines.length === 0) {
      return (
        <div className="space-y-4">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
            Engine-Level Engineering Evidence
          </p>
          <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
            <p className="text-sm text-slate-500">No technical engine evidence available.</p>
          </div>
        </div>
      );
    }
    return (
      <div className="space-y-4">
        <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
          Engine-Level Engineering Evidence
        </p>
        <div className="grid gap-3 sm:grid-cols-3">
          {engines.map((engine) => {
            const name = s(engine.engine);
            const isUnavailable =
              s(engine.availability_status) === "unavailable";
            const tested = num(engine.tested_pages);
            const eligible = num(engine.eligible_pages);
            return (
              <div
                key={name}
                className={`rounded-lg border p-4 ${isUnavailable ? "border-slate-200 bg-slate-50" : "border-slate-200 bg-white"}`}
              >
                <p className="text-sm font-semibold text-slate-700">
                  {ENGINE_LABELS[name] ?? formatLabel(name)}
                </p>
                {isUnavailable ? (
                  <p className="mt-1 text-sm text-slate-500">
                    Unavailable in this environment
                  </p>
                ) : (
                  <p className="mt-1 text-xl font-bold text-slate-900">
                    {tested}/{eligible} pages tested
                  </p>
                )}
              </div>
            );
          })}
        </div>
        <p className="text-xs text-slate-400">
          Engine evidence is not equivalent to branded browser verification.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
        Customer-Facing Browser Verification
      </p>
      <div className="grid gap-3 sm:grid-cols-3">
        {(() => {
          interface BrowserUATMatrixRow {
            browser: string;
            required_version_policy: string;
            platforms: string;
            verification_state: string;
            verification_state_label?: string;
            related_engine: string;
            engine_tested_pages?: number;
          }
          const browserUat = obs?.browser_uat as { matrix?: BrowserUATMatrixRow[] } | undefined;
          if (browserUat && Array.isArray(browserUat.matrix)) {
            return browserUat.matrix.map((bb: BrowserUATMatrixRow) => {
              const tested = Number(bb.engine_tested_pages) || 0;
              const hasEvidence = tested > 0;

              let badgeStatus = "unavailable";
              if (bb.verification_state === "VERIFIED") badgeStatus = "completed";
              if (bb.verification_state === "PARTIALLY_VERIFIED") badgeStatus = "partial";
              if (bb.verification_state === "NOT_VERIFIED" && hasEvidence) badgeStatus = "unavailable";

              return (
                <div
                  key={bb.browser}
                  className={`rounded-lg border p-4 ${bb.verification_state === "VERIFIED" ? "border-z-success bg-white" : hasEvidence ? "border-slate-200 bg-white" : "border-slate-200 bg-slate-50"}`}
                >
                  <p className="text-sm font-semibold text-slate-700">
                    {bb.browser}
                  </p>
                  <p className="mt-0.5 text-xs text-slate-400">
                    {bb.required_version_policy} · {bb.platforms}
                  </p>
                  <StatusBadge
                    status={badgeStatus}
                    label={bb.verification_state_label || "Not verified in current environment"}
                  />
                  <p className="mt-1 text-xs text-slate-400">
                    {hasEvidence && bb.verification_state !== "VERIFIED"
                      ? `${ENGINE_LABELS[bb.related_engine] ?? bb.related_engine} evidence available in technical view`
                      : !hasEvidence
                        ? "No branded-browser execution evidence retained"
                        : "Verified by branded channel"}
                  </p>
                </div>
              );
            });
          }

          // Legacy Fallback
          return BRANDED_BROWSERS.map((bb) => {
            const engineTested = engineMap[bb.engine];
            const tested = engineTested ? num(engineTested.tested_pages) : 0;
            const isUnavailable = !engineTested || s(engineTested.availability_status) === "unavailable";
            const hasEvidence = !isUnavailable && tested > 0;
            return (
              <div
                key={bb.browser}
                className={`rounded-lg border p-4 ${hasEvidence ? "border-slate-200 bg-white" : "border-slate-200 bg-slate-50"}`}
              >
                <p className="text-sm font-semibold text-slate-700">
                  {bb.browser}
                </p>
                <p className="mt-0.5 text-xs text-slate-400">
                  {bb.versionScope} · {bb.platforms}
                </p>
                <StatusBadge
                  status="unavailable"
                  label="Not verified in current environment"
                />
                <p className="mt-1 text-xs text-slate-400">
                  {hasEvidence
                    ? `${ENGINE_LABELS[bb.engine] ?? bb.engine} evidence available in technical view`
                    : "No branded-browser execution evidence retained"}
                </p>
              </div>
            );
          });
        })()}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Report quality label
// ---------------------------------------------------------------------------

const ANALYSIS_STATUS_DOT: Record<AnalysisStatus, string> = {
  completed: "bg-emerald-500",
  running: "bg-blue-400",
  queued: "bg-slate-400",
  failed: "bg-red-500",
};

function qualityFromScore(
  analysisStatus: AnalysisStatus,
  score: {
    overall_score: number | null;
    confidence_percent: number;
    available_categories: string[];
  },
): ReportQuality {
  // A genuinely failed run must always read FAILED, regardless of whatever
  // partial score data happened to be persisted before the failure.
  if (analysisStatus === "failed") return "FAILED";
  const availableCount = Array.isArray(score.available_categories) ? score.available_categories.length : 0;
  if (
    availableCount === 0 ||
    score.overall_score == null
  )
    return "INCONCLUSIVE";
  if (score.confidence_percent >= 50 && availableCount >= 4)
    return "COMPLETE";
  return "PARTIAL";
}

// ---------------------------------------------------------------------------
// Metric labels
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Collapsible section wrapper
// ---------------------------------------------------------------------------

function CollapsibleSection({
  title,
  defaultOpen = false,
  children,
  id,
}: {
  title: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
  id?: string;
}) {
  return (
    <details className="group" open={defaultOpen} id={id}>
      <summary className="flex cursor-pointer items-center gap-2 py-3 text-sm font-semibold text-slate-700 hover:text-slate-900">
        <svg
          className="h-4 w-4 shrink-0 transition-transform group-open:rotate-90"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
        </svg>
        {title}
      </summary>
      <div className="pb-4">{children}</div>
    </details>
  );
}

// ---------------------------------------------------------------------------
// Main page component
// ---------------------------------------------------------------------------

export default function AnalysisReportPage() {
  const { analysisRunId } = useParams<{ analysisRunId: string }>();
  const searchParams = useSearchParams();
  const projectId = searchParams.get("projectId") ?? undefined;
  const websiteId = searchParams.get("websiteId") ?? undefined;
  const workflowExecutionId =
    searchParams.get("workflowExecutionId") ?? undefined;
  const baselineRunId = searchParams.get("baselineRunId") ?? undefined;

  const [report, setReport] = useState<AnalysisReport | null>(null);
  const [performanceData, setPerformanceData] = useState<
    Record<string, unknown>[]
  >([]);
  const [accessibilityData, setAccessibilityData] =
    useState<AccessibilityData | null>(null);
  const [interpretations, setInterpretations] = useState<
    MetricInterpretation[]
  >([]);
  const [interpretationsUnavailable, setInterpretationsUnavailable] =
    useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [interruptedResources, setInterruptedResources] = useState<string[]>(
    [],
  );
  const [workflowProgress, setWorkflowProgress] =
    useState<WorkflowProgress | null>(null);
  const [currentReportAvailable, setCurrentReportAvailable] = useState(false);
  const [baselineAvailable, setBaselineAvailable] = useState(false);
  const [comparisonDataAvailable, setComparisonDataAvailable] = useState(false);
  type TabId = "overview" | "findings" | "performance" | "accessibility" | "seo" | "technical" | "browser" | "pages" | "actions" | "evidence";
  const [activeTab, setActiveTab] = useState<TabId>("overview");

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
  const handleReportAvailabilityChange = useCallback(
    (available: boolean) => {
      setCurrentReportAvailable(available);
    },
    [],
  );

  // ---- Data fetching (same as before) ----

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
          )
            return;
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
        onSuccess: (response) => setPerformanceData(response.data ?? []),
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
        setInterpretationsUnavailable(false);
      },
      onConnectionChange: () => {},
      onPermanentFailure: () => setInterpretationsUnavailable(true),
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
    )
      return;
    return startRetriedRequest({
      request: async () => {
        try {
          return await analysisComparisonApi.detail(
            analysisRunId,
            baselineRunId,
          );
        } catch (requestError) {
          if (
            !(requestError instanceof ApiError) ||
            requestError.status !== 404
          )
            throw requestError;
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

  // ---- In-progress state ----

  if (!report && websiteId && workflowExecutionId) {
    return (
      <main className="mx-auto min-h-screen max-w-6xl px-6 py-12">
        <Link className="text-sm font-medium text-slate-500 hover:text-slate-700" href="/">
          ← Start another analysis
        </Link>
        <h1 className="mt-6 text-2xl font-bold text-slate-900">
          Website analysis in progress
        </h1>
        <p className="mt-2 text-sm text-slate-600">
          Real evidence is being collected from the submitted website.
        </p>
        {essentialConnectionInterrupted && (
          <p className="mt-4 text-sm text-amber-800" role="status">
            Connection interrupted — retrying
          </p>
        )}
        {loading && (
          <p className="mt-4 text-sm text-slate-500" role="status">
            Loading analysis progress…
          </p>
        )}
        {error && (
          <p className="mt-4 text-sm text-amber-800" role="status">
            The final report is not available yet. Progress remains available
            below.
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

  if (loading)
    return (
      <main className="mx-auto max-w-6xl px-6 py-12">
        <p role="status" className="text-sm text-slate-500">
          Loading analysis report…
        </p>
      </main>
    );

  if (error || !report)
    return (
      <main className="mx-auto max-w-6xl px-6 py-12">
        <h1 className="text-2xl font-bold">Report unavailable</h1>
        <p className="mt-4 text-red-700" role="alert">
          {error ?? "The report could not be found."}
        </p>
      </main>
    );

  // ---- Derived data ----

  const categoryScores: Record<string, number | null> = {
    Performance: report.score.performance_score,
    Accessibility: report.score.accessibility_score,
    "Best Practices": report.score.best_practices_score,
    SEO: report.score.seo_score,
    "Technical Quality": report.score.technical_quality_score,
  };
  const diagnostics = Object.entries(report.diagnostics);
  const copyright = report.diagnostics.policy_diagnostics?.copyright;
  if (copyright) diagnostics.splice(3, 0, ["copyright_diagnostics", copyright]);
  const auditBreakdown = Array.isArray(
    report.lighthouse_metrics.lighthouse_audit_breakdown,
  )
    ? (report.lighthouse_metrics.lighthouse_audit_breakdown as Array<
        Record<string, unknown>
      >)
    : [];
  const technology = report.playwright_measurements.technology_indicators;
  const comparisonReady = Boolean(
    baselineRunId &&
      baselineAvailable &&
      comparisonTerminal &&
      currentReportAvailable &&
      comparisonDataAvailable,
  );

  const quality = qualityFromScore(report.analysis_status, report.score);
  const safeFindings = Array.isArray(report.findings) ? report.findings : [];
  const grouped = groupFindings(safeFindings);
  const topFindings = grouped
    .filter((g) => ["critical", "high"].includes(g.severity))
    .slice(0, 5);

  const interpretation = report.interpretation;
  const topActions =
    interpretation?.priority_recommendations.slice(0, 5) ?? [];

  // Collect all limitations from diagnostics
  const allLimitations = new Set<string>();
  for (const [, diag] of diagnostics) {
    for (const lim of Array.isArray(diag.limitations) ? diag.limitations : []) {
      allLimitations.add(lim);
    }
  }
  const unavailableCategories = Array.isArray(report.score.unavailable_categories) ? report.score.unavailable_categories : [];
  if (unavailableCategories.length > 0) {
    allLimitations.add(
      `Unavailable scoring categories: ${unavailableCategories.join(", ")}`,
    );
  }

  // ---- Render ----

  const TABS = [
    { id: "overview", label: "Overview" },
    { id: "findings", label: "Findings" },
    { id: "performance", label: "Performance" },
    { id: "accessibility", label: "Accessibility" },
    { id: "seo", label: "SEO & Content" },
    { id: "technical", label: "Security & Technical" },
    { id: "browser", label: "Browser UAT & Responsive" },
    { id: "pages", label: "Pages" },
    { id: "actions", label: "Action Plan" },
    { id: "evidence", label: "Evidence & Limitations" },
  ] as const;

  return (
    <main className="mx-auto min-h-screen max-w-[90rem] px-4 py-8">
      {/* Top Breadcrumb */}
      <Link className="text-sm font-medium text-slate-500 hover:text-slate-700 mb-6 inline-block" href="/projects">
        ← Projects
      </Link>

      {/* NEW Run Header */}
      <header className="overflow-hidden rounded-xl border border-z-border bg-z-surface shadow-sm mb-6">
        <div className="bg-slate-900 px-6 py-5 border-b border-slate-800">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0">
              <p className="text-xs font-bold uppercase tracking-widest text-emerald-400">
                ZuiGO WebIQ
              </p>
              <h1 className="mt-2 text-2xl font-black text-white">
                {report.website.name || "Website Analysis"}
              </h1>
            </div>
            <div className="flex items-center gap-2">
              <span className={`rounded-full border px-3 py-1 text-xs font-bold ${QUALITY_STYLES[quality] ?? "bg-slate-100 text-slate-700 border-slate-300"}`}>
                {quality}
              </span>
            </div>
          </div>

          <div className="mt-5 flex flex-wrap gap-x-8 gap-y-3 text-sm">
             <div className="flex gap-2 items-center text-slate-200"><span className={`w-2 h-2 rounded-full ${ANALYSIS_STATUS_DOT[report.analysis_status] ?? "bg-slate-400"}`}></span><span className="capitalize font-semibold">Analysis: {report.analysis_status}</span></div>
             <div className="text-slate-300">Started {new Date(report.result.analysis_started_at).toLocaleString()}</div>
             {report.result.analysis_completed_at && <div className="text-slate-300">Completed {new Date(report.result.analysis_completed_at).toLocaleString()}</div>}
             <div className="text-slate-300 font-mono text-xs">{report.result.requested_url}</div>
          </div>
        </div>

        {comparisonReady && (
          <div className="mx-6 mt-4 flex items-center justify-between rounded-xl bg-blue-50 border border-blue-200 p-4 shadow-sm">
            <div className="flex items-center gap-3">
              <span className="flex h-8 w-8 items-center justify-center rounded-full bg-blue-100 text-blue-700">
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline></svg>
              </span>
              <div>
                <p className="font-semibold text-blue-900">Reanalysis comparison available</p>
                <p className="text-xs text-blue-700">Compare these results with the baseline analysis.</p>
              </div>
            </div>
            <Link
              href={`/analysis-runs/${analysisRunId}/compare/${baselineRunId}${projectId ? `?projectId=${projectId}` : ""}`}
              className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600"
            >
              View comparison
            </Link>
          </div>
        )}

        <div className="flex flex-wrap items-center justify-between gap-6 px-6 py-4 bg-z-surface">
           <div className="flex items-baseline gap-2">
            <span className="text-4xl font-bold text-z-ink">
              {report.score.overall_score != null ? (
                <ScoreValue metricId="overall_score" value={report.score.overall_score} />
              ) : "—"}
            </span>
            {(() => {
              const interpretation = interpretations.find(i => i.metric_id === "overall_score");
              if (!interpretation || ["unavailable", "not_applicable"].includes(interpretation.rating)) return null;
              return (
                <div className="ml-2">
                  <MetricRatingBadge interpretation={interpretation} />
                </div>
              );
            })()}
          </div>
          <div className="text-sm font-medium text-z-ink-secondary flex gap-4 items-center">
             <span>Confidence {report.score.confidence_percent}%</span>
             <span>Formula {report.score.formula_version}</span>
             {allLimitations.size > 0 ? (
               <button onClick={() => setActiveTab("evidence")} className="text-amber-600 hover:text-amber-700 flex items-center gap-1 border-l pl-4 border-z-border underline decoration-amber-600/30 underline-offset-4">
                 <span className="hidden sm:inline">Limitations: {allLimitations.size} evidence/scope limitation{allLimitations.size !== 1 ? 's' : ''}</span>
                 <span className="sm:hidden">{allLimitations.size} limitation{allLimitations.size !== 1 ? 's' : ''}</span>
               </button>
             ) : (
               <span className="text-emerald-600 flex items-center gap-1 border-l pl-4 border-z-border">No evidence limitations flagged</span>
             )}
          </div>
        </div>
      </header>

      {essentialConnectionInterrupted && (
        <p className="mt-4 text-sm text-amber-800 bg-amber-50 p-2 rounded" role="status">
          Connection interrupted — retrying
        </p>
      )}

      {/* Secondary Sticky Navigation */}
      <div className="sticky top-0 z-40 -mx-4 px-4 sm:mx-0 sm:px-0 mb-8 bg-z-surface/95 backdrop-blur-md border-b border-z-border overflow-x-auto custom-scrollbar">
         <nav className="flex space-x-1 min-w-max" aria-label="Tabs">
            {TABS.map(tab => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id as TabId)}
                className={`whitespace-nowrap flex-shrink-0 px-4 py-3 text-sm font-bold border-b-2 transition-colors ${
                  activeTab === tab.id
                  ? 'border-z-accent text-z-accent'
                  : 'border-transparent text-z-ink-muted hover:text-z-ink hover:border-z-border'
                }`}
              >
                {tab.label}
              </button>
            ))}
         </nav>
      </div>

      <div className="min-h-[600px] mb-20">
         {/* OVERVIEW TAB */}
         {activeTab === 'overview' && (
           <div className="space-y-8 animate-in fade-in slide-in-from-bottom-2 duration-300">
             {/* Category Scores */}
              <section className="rounded-xl border border-z-border bg-z-surface p-6">
                <h2 className="text-lg font-bold text-z-ink">Category Scores</h2>
                {interpretationsUnavailable && (
                  <p className="mt-2 text-xs text-z-ink-muted">
                    Metric interpretation help is unavailable. Scores remain available.
                  </p>
                )}
                <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
                  {Object.entries(categoryScores).map(([name, score]) => {
                    const mId = name.toLowerCase().replace(" ", "_") + "_score";
                    return (
                      <div key={name} className="bg-z-surface p-4 rounded-lg border border-z-border">
                        <ScoreBar score={score} label={name} />
                        <div className="mt-2 flex justify-end">
                          <MetricRatingBadge interpretation={interpretations.find((i) => i.metric_id === mId)} />
                        </div>
                      </div>
                    );
                  })}
                </div>
              </section>

              {/* Website Signals */}
              <SectionErrorBoundary sectionName="Website Signals">
                <section className="rounded-xl border border-z-border bg-z-surface p-6">
                  <h2 className="text-lg font-bold text-z-ink">Website Signals</h2>
                  <p className="mt-1 text-sm text-z-ink-muted">Evidence-based detection of privacy, copyright, security, analytics, responsiveness, HTML standards, and security posture.</p>
                  <div className="mt-6">
                    <WebsiteSignalsSection diagnostics={report.diagnostics} />
                  </div>
                </section>
              </SectionErrorBoundary>

              {/* Top Findings */}
              <section className="rounded-xl border border-z-border bg-z-surface p-6">
                <div className="flex items-baseline justify-between mb-4">
                  <h2 className="text-lg font-bold text-z-ink">Top Findings</h2>
                  <span className="text-sm font-semibold text-z-ink-muted bg-z-surface px-3 py-1 rounded-full border border-z-border">
                    {grouped.length} unique · {safeFindings.length} total
                  </span>
                </div>
                {topFindings.length > 0 ? (
                  <div className="space-y-3">
                    {topFindings.map((finding) => (
                      <div key={finding.finding_code} className="flex items-start gap-4 rounded-lg border border-z-border p-4 bg-z-surface hover:border-z-border-strong transition-colors">
                        <StatusBadge status={finding.severity} />
                        <div className="min-w-0 flex-1">
                          <p className="font-bold text-z-ink">{finding.title}</p>
                          <p className="mt-1 text-sm text-z-ink-secondary line-clamp-2">{finding.description}</p>
                          <div className="mt-3 flex flex-wrap gap-4 text-xs font-semibold text-z-ink-muted">
                            <span className="flex items-center gap-1">
                              <span className="w-4 h-4 flex items-center justify-center bg-z-surface rounded border border-z-border">{finding.affectedUrls.size}</span>
                              Page{finding.affectedUrls.size !== 1 ? "s" : ""}
                            </span>
                            <span className="flex items-center gap-1">
                              <span className="w-4 h-4 flex items-center justify-center bg-z-surface rounded border border-z-border">{finding.totalOccurrences}</span>
                              Occurrences
                            </span>
                            <span className="capitalize px-2 py-0.5 bg-z-surface rounded border border-z-border">{formatLabel(finding.category)}</span>
                          </div>
                        </div>
                        <button
                          type="button"
                          className="shrink-0 text-sm font-bold text-z-accent hover:text-z-accent-hover bg-z-accent/10 px-3 py-1.5 rounded-md"
                          onClick={() => setActiveTab("findings")}
                        >
                          Details
                        </button>
                      </div>
                    ))}
                  </div>
                ) : (
                  <EmptyState title="No critical or high-severity findings detected" description="Review all findings in Findings Register." />
                )}
                {grouped.length > 5 && (
                  <div className="mt-4 text-center">
                    <button
                      type="button"
                      className="text-sm font-bold text-z-ink hover:text-z-accent border border-z-border bg-z-surface px-4 py-2 rounded-lg transition-colors"
                      onClick={() => setActiveTab("findings")}
                    >
                      View all {grouped.length} findings
                    </button>
                  </div>
                )}
              </section>
           </div>
         )}

         {/* FINDINGS TAB */}
         {activeTab === 'findings' && (
            <div className="animate-in fade-in slide-in-from-bottom-2 duration-300 h-full min-h-[600px]">
              <IssueRegister findings={safeFindings} />
            </div>
         )}

         {/* PERFORMANCE TAB */}
         {activeTab === 'performance' && (
            <div className="space-y-8 animate-in fade-in slide-in-from-bottom-2 duration-300">
               <SectionErrorBoundary sectionName="Performance Intelligence">
                 <PerformanceIntelligence data={performanceData as unknown as React.ComponentProps<typeof PerformanceIntelligence>['data']} />
               </SectionErrorBoundary>

               <section className="rounded-xl border border-z-border bg-z-surface p-6">
                  <h2 className="text-lg font-bold text-z-ink">Lighthouse Metrics</h2>
                  <dl className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                    {Object.entries(metricLabels).map(([key, name]) => (
                      <div key={key} className="rounded-lg border border-z-border bg-z-surface p-4">
                        <dt className="flex items-center justify-between gap-2 text-sm font-semibold text-z-ink-secondary">
                          {name}
                          <MetricRatingBadge interpretation={interpretations.find(i => i.metric_id === key.replace("_ms", ""))} />
                        </dt>
                        <dd className="mt-2 text-2xl font-black text-z-ink tabular-nums">
                          {display(report.lighthouse_metrics[key])}
                        </dd>
                      </div>
                    ))}
                  </dl>
               </section>

               <section className="rounded-xl border border-z-border bg-z-surface p-6">
                  <h2 className="text-lg font-bold text-z-ink">Page Measurements</h2>
                  <dl className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                    <div className="rounded-lg border border-z-border bg-z-surface p-4">
                      <dt className="text-sm font-semibold text-z-ink-secondary">HTTP status</dt>
                      <dd className="mt-2 text-xl font-black text-z-ink tabular-nums">{display(report.result.http_status_code)}</dd>
                    </div>
                    {Object.entries(measurementLabels).map(([key, name]) => (
                      <div key={key} className="rounded-lg border border-z-border bg-z-surface p-4">
                        <dt className="text-sm font-semibold text-z-ink-secondary">{name}</dt>
                        <dd className="mt-2 text-xl font-black text-z-ink tabular-nums">{display(report.playwright_measurements[key])}</dd>
                      </div>
                    ))}
                  </dl>
               </section>

               {!!technology && (
                 <section className="rounded-xl border border-z-border bg-z-surface p-6">
                   <CollapsibleSection title="Technology Detection" defaultOpen>
                     <div className="bg-z-surface p-4 rounded-lg border border-z-border mt-2">
                       <HumanValue value={technology} />
                     </div>
                   </CollapsibleSection>
                 </section>
               )}
            </div>
         )}

         {/* ACCESSIBILITY TAB */}
         {activeTab === 'accessibility' && (
            <div className="space-y-8 animate-in fade-in slide-in-from-bottom-2 duration-300">
               <SectionErrorBoundary sectionName="Accessibility Intelligence">
                  <AccessibilityIntelligence accessibilityData={accessibilityData} />
               </SectionErrorBoundary>

               {auditBreakdown.length > 0 && (
                 <section className="rounded-xl border border-z-border bg-z-surface p-6">
                   <CollapsibleSection title={`Lighthouse Audit Breakdown (${auditBreakdown.length})`} defaultOpen>
                     <div className="bg-z-surface p-4 rounded-lg border border-z-border mt-2 overflow-x-auto">
                       <HumanValue value={auditBreakdown} />
                     </div>
                   </CollapsibleSection>
                   <p className="mt-4 text-xs font-semibold text-z-ink-muted">Lighthouse automated checks. A score of 100 does not prove complete accessibility compliance.</p>
                 </section>
               )}
            </div>
         )}

         {/* SEO & CONTENT TAB */}
         {activeTab === 'seo' && (
            <div className="space-y-8 animate-in fade-in slide-in-from-bottom-2 duration-300">
               <SectionErrorBoundary sectionName="Extracted Content">
                 <section className="rounded-xl border border-z-border bg-z-surface p-6">
                   <h2 className="text-lg font-bold text-z-ink">Extracted Content</h2>
                   <div className="mt-4">
                     <ExtractedContentPanel analysisRunId={analysisRunId} />
                   </div>
                 </section>
               </SectionErrorBoundary>
            </div>
         )}

         {/* SECURITY & TECHNICAL TAB */}
         {activeTab === 'technical' && (
            <div className="space-y-8 animate-in fade-in slide-in-from-bottom-2 duration-300">
               <SectionErrorBoundary sectionName="Verified Diagnostics">
                  <section className="rounded-xl border border-z-border bg-z-surface p-6">
                    <h2 className="text-lg font-bold text-z-ink mb-4">Verified Diagnostics</h2>
                    <div className="space-y-4">
                      {diagnostics.map(([name, diagnostic]) => (
                        <div key={name} className="border border-z-border rounded-lg bg-z-surface p-4">
                          <CollapsibleSection title={`${diagnosticTitles[name] ?? formatLabel(name)} — ${formatLabel(diagnostic.status)}`}>
                            <div className="grid gap-4 text-sm sm:grid-cols-3 mt-4">
                              <MetricStat label="Status" value={formatLabel(diagnostic.status)} />
                              <div className="flex items-start gap-1">
                                <MetricStat
                                  label="Evidence"
                                  value={formatLabel(diagnostic.evidence_completeness ?? diagnostic.status)}
                                />
                                <div className="pt-0.5">
                                  <ConceptInfoButton conceptId="evidence_completeness" title="Evidence completeness" />
                                </div>
                              </div>
                              <MetricStat label="Collected" value={new Date(diagnostic.collected_at).toLocaleString()} />
                            </div>
                            {!!diagnostic.score && (
                              <div className="mt-4 rounded-lg bg-z-surface border border-z-border p-4">
                                <p className="text-xs font-bold uppercase text-z-ink-muted mb-2">{diagnostic.score.label}</p>
                                <div className="flex flex-wrap gap-x-8 gap-y-4">
                                  <div>
                                    <span className="text-xs font-semibold text-z-ink-secondary block mb-1">Raw Base</span>
                                    <span className="font-mono">{diagnostic.score.starting_score}</span>
                                  </div>
                                  <div>
                                    <span className="text-xs font-semibold text-z-ink-secondary block mb-1">Deductions</span>
                                    <span className="font-mono text-red-600">-{Array.isArray(diagnostic.score?.deductions) ? diagnostic.score.deductions.reduce((a: number, b: { points: number }) => a + b.points, 0) : 0}</span>
                                  </div>
                                  <div>
                                    <span className="text-xs font-semibold text-z-ink-secondary block mb-1">Final Index</span>
                                    <span className="font-mono font-bold">{diagnostic.score.final_score}</span>
                                  </div>
                                </div>
                              </div>
                            )}
                          </CollapsibleSection>
                        </div>
                      ))}
                    </div>
                  </section>
               </SectionErrorBoundary>

               <SectionErrorBoundary sectionName="Website Signals Evidence">
                 <section className="rounded-xl border border-z-border bg-z-surface p-6">
                   <h2 className="text-lg font-bold text-z-ink mb-4">Website Signals — Technical Evidence</h2>
                   <WebsiteSignalsTechnicalEvidence diagnostics={report.diagnostics} />
                 </section>
               </SectionErrorBoundary>

               <SectionErrorBoundary sectionName="Score Transparency">
                 <section className="rounded-xl border border-z-border bg-z-surface p-6">
                   <h2 className="text-lg font-bold text-z-ink">Score Transparency</h2>
                   <div className="mt-4 space-y-2 text-sm text-z-ink-secondary">
                     <p><strong>Available:</strong> {Array.isArray(report.score.available_categories) ? report.score.available_categories.join(", ") : "None"}</p>
                     <p><strong>Unavailable:</strong> {Array.isArray(report.score.unavailable_categories) ? report.score.unavailable_categories.join(", ") : "None"}</p>
                   </div>
                   {Array.isArray(report.score.deductions) && report.score.deductions.length > 0 && (
                     <div className="mt-6">
                       <CollapsibleSection title={`Technical Quality deductions (${report.score.deductions.length})`}>
                         <div className="bg-z-surface border border-z-border rounded-lg p-4 mt-2">
                           <HumanValue value={report.score.deductions} />
                         </div>
                       </CollapsibleSection>
                     </div>
                   )}
                 </section>
               </SectionErrorBoundary>
            </div>
         )}

         {/* BROWSER & RESPONSIVE TAB */}
         {activeTab === 'browser' && (
            <div className="space-y-8 animate-in fade-in slide-in-from-bottom-2 duration-300">
               <SectionErrorBoundary sectionName="Browser Compatibility">
                 <section className="rounded-xl border border-z-border bg-z-surface p-6">
                   <h2 className="text-lg font-bold text-z-ink mb-2">Browser UAT & Responsive Verification</h2>
                   <p className="text-sm text-z-ink-muted mb-6">Browser UAT scope across Google Chrome, Microsoft Edge, and Apple Safari.</p>
                   <BrowserSummary diagnostics={report.diagnostics} viewMode="executive" />
                 </section>
               </SectionErrorBoundary>

               <SectionErrorBoundary sectionName="Real Browser Verification">
                 <BrowserUatPanel analysisRunId={analysisRunId} />
               </SectionErrorBoundary>

               <SectionErrorBoundary sectionName="Reanalysis Comparison">
                 <ReanalysisComparisonPanel analysisRunId={analysisRunId} projectId={projectId} />
               </SectionErrorBoundary>
            </div>
         )}

         {/* PAGES TAB */}
         {activeTab === 'pages' && (
            <div className="space-y-8 animate-in fade-in slide-in-from-bottom-2 duration-300">
               <SectionErrorBoundary sectionName="Pages Analysis">
                 <section className="rounded-xl border border-z-border bg-z-surface p-6">
                   <h2 className="text-lg font-bold text-z-ink mb-4">Discovered Pages Analysis</h2>
                   <SiteDiagnosticsPanel websiteId={report.website.id} />
                 </section>
               </SectionErrorBoundary>
            </div>
         )}

         {/* ACTION PLAN TAB */}
         {activeTab === 'actions' && (
            <div className="space-y-8 animate-in fade-in slide-in-from-bottom-2 duration-300">
               <section className="rounded-xl border border-z-border bg-z-surface p-6">
                 <h2 className="text-lg font-bold text-z-ink mb-4">Priority Action Plan</h2>
                 {topActions.length > 0 ? (
                   <div className="space-y-4">
                     {topActions.map((action, i) => (
                       <div key={action.recommendation_id} className="rounded-xl border border-z-border bg-z-surface p-5 shadow-sm">
                         <div className="flex items-start gap-4">
                           <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-z-dark-surface text-sm font-black text-white shadow-sm">
                             {i + 1}
                           </span>
                           <div className="min-w-0 flex-1">
                             <div className="flex items-start justify-between gap-2">
                               <p className="font-bold text-z-ink text-lg">{action.title}</p>
                               <StatusBadge status={action.priority} />
                             </div>
                             <p className="mt-2 text-sm leading-relaxed text-z-ink-secondary">
                               {action.explanation}
                             </p>
                             <div className="mt-4 flex flex-wrap gap-4 text-xs font-semibold text-z-ink-muted bg-z-surface p-3 rounded-lg border border-z-border">
                               <div><span className="text-z-ink-secondary block mb-1">Owner</span>{action.responsible_role}</div>
                               <div className="border-l border-z-border pl-4"><span className="text-z-ink-secondary block mb-1">Effort</span>{action.estimated_effort}</div>
                               <div className="border-l border-z-border pl-4"><span className="text-z-ink-secondary block mb-1">Confidence</span>{action.confidence_percent}%</div>
                             </div>
                           </div>
                         </div>
                       </div>
                     ))}
                   </div>
                 ) : (
                   <EmptyState title="No evidence-grounded actions available" description="This may indicate that no actionable findings were retained, or an AI-prioritized plan was unavailable." />
                 )}
               </section>
            </div>
         )}

         {/* EVIDENCE & LIMITATIONS TAB */}
         {activeTab === 'evidence' && (
            <div className="space-y-8 animate-in fade-in slide-in-from-bottom-2 duration-300">
               <SectionErrorBoundary sectionName="Agent Execution">
                  <AgentExecutionPanel analysisRunId={analysisRunId} />
               </SectionErrorBoundary>

               <SectionErrorBoundary sectionName="Scoring Intelligence">
                  <ScoringIntelligencePanel analysisRunId={analysisRunId} websiteId={report.website.id} />
               </SectionErrorBoundary>

               <SectionErrorBoundary sectionName="Methodology">
                 <section className="rounded-xl border border-z-border bg-z-surface p-6">
                   <h2 className="text-lg font-bold text-z-ink mb-4">Methodology</h2>
                   <dl className="grid gap-4 text-sm sm:grid-cols-2 lg:grid-cols-4">
                     <div className="bg-z-surface border border-z-border p-4 rounded-lg">
                       <dt className="text-z-ink-secondary font-semibold mb-1">Scoring formula</dt>
                       <dd className="font-mono text-xs">v{report.score.formula_version}</dd>
                     </div>
                     <div className="bg-z-surface border border-z-border p-4 rounded-lg">
                       <dt className="text-z-ink-secondary font-semibold mb-1">Lighthouse version</dt>
                       <dd className="font-mono text-xs">{report.result.lighthouse_version ?? "Not available"}</dd>
                     </div>
                     <div className="bg-z-surface border border-z-border p-4 rounded-lg">
                       <dt className="text-z-ink-secondary font-semibold mb-1">Analysis run</dt>
                       <dd className="font-mono text-xs break-all">{report.analysis_run_id}</dd>
                     </div>
                   </dl>
                 </section>
               </SectionErrorBoundary>

               {allLimitations.size > 0 && (
                 <SectionErrorBoundary sectionName="All Limitations">
                   <section className="rounded-xl border border-z-border bg-z-surface p-6">
                     <h2 className="text-lg font-bold text-z-ink mb-4 flex items-center gap-2">
                       <span className="text-amber-500">⚠</span> All Limitations
                     </h2>
                     <ul className="space-y-3">
                       {[...allLimitations].map((lim) => (
                         <li key={lim} className="flex items-start gap-3 text-sm text-z-ink-secondary bg-z-surface border border-z-border p-3 rounded-lg">
                           <span className="text-amber-500 font-bold">•</span>
                           <span>{lim}</span>
                         </li>
                       ))}
                     </ul>
                   </section>
                 </SectionErrorBoundary>
               )}

               <SectionErrorBoundary sectionName="Report Delivery">
                 <section>
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
               </SectionErrorBoundary>
            </div>
         )}
      </div>
    </main>
  );
}
