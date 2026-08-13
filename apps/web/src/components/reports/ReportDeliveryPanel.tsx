"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import type {
  DeliveredReport,
  DetailedReportFinding,
  PaginatedReports,
  WorkflowProgress,
} from "@/components/reports/types";
import { ConceptInfoButton } from "@/components/metrics/ConceptInfoButton";
import { reportDeliveryApi } from "@/lib/report-delivery-api";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { ScoreBar } from "@/components/ui/ScoreBadge";
import { UrlCell } from "@/components/ui/UrlCell";
import { EmptyState } from "@/components/ui/EmptyState";
import { MetricStat } from "@/components/ui/MetricStat";
import { AnalysisProgressTimeline } from "@/components/reports/AnalysisProgressTimeline";

const PAGE_SIZE = 5;
const FINDINGS_PAGE_SIZE = 20;
const INVENTORY_PAGE_SIZE = 25;
const TERMINAL_STATUSES = [
  "completed",
  "partial",
  "failed",
  "cancelled",
  "unavailable",
];
const AGENT_LABELS: Record<string, string> = {
  discovery_agent: "Discovery Agent",
  performance_agent: "Performance Agent",
  accessibility_agent: "Accessibility Agent",
  site_diagnostics_agent: "Site Diagnostics Agent",
  repository_intelligence_agent: "Repository Intelligence Agent",
  evidence_validation_agent: "Evidence Validation Agent",
  remediation_agent: "Remediation Agent",
  report_agent: "Report Agent",
};
const ENGINE_LABELS: Record<string, string> = {
  chromium: "Chromium engine",
  firefox: "Firefox engine",
  webkit: "WebKit engine (internal signal only)",
};

interface ReportDeliveryPanelProps {
  projectId?: string;
  websiteId: string;
  analysisRunId?: string;
  workflowExecutionId?: string;
  compact?: boolean;
  showStartAction?: boolean;
  onProgressChange?: (progress: WorkflowProgress) => void;
  onReportAvailabilityChange?: (available: boolean) => void;
}

function executionKey(projectId: string, websiteId: string): string {
  return `analysis-journey:${projectId}:${websiteId}`;
}

function createKey(prefix: string): string {
  return `${prefix}-${new Date().toISOString()}-${crypto.randomUUID()}`;
}

function isTransientConnectionError(error: unknown): boolean {
  return (
    error instanceof TypeError ||
    (error instanceof Error &&
      /failed to fetch|networkerror|load failed/i.test(error.message))
  );
}

function statusLabel(status: string | null | undefined): string {
  if (!status) return "Unknown";
  return status
    .replaceAll("_", " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

type StatusContext = "active_stage" | "historical" | "optional_tool";

function displayStatus(
  status: string | null | undefined,
  context?: StatusContext,
): string {
  if (!status) {
    switch (context) {
      case "historical":
        return "Not recorded";
      case "optional_tool":
        return "Unavailable";
      default:
        return "Pending";
    }
  }
  const labels: Record<string, string> = {
    pending: "Queued",
    queued: "Queued",
    running: "Running",
    completed: "Completed",
    partial: "Partial",
    failed: "Failed",
    unavailable: "Unavailable",
    cancelled: "Cancelled",
    not_applicable: "Not applicable",
    not_started: "Not started",
    failed_to_start: "Failed to start",
    timed_out: "Timed out",
    execution_status_not_recorded:
      "Execution status was not recorded for this run",
  };
  return labels[status] ?? statusLabel(status);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function formatHumanTimestamp(value: unknown): string {
  if (typeof value !== "string" || !value) return "Not collected";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Not collected";
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  }).format(date);
}

function friendlyAgentName(agentId: unknown): string {
  const normalized = typeof agentId === "string" ? agentId : "";
  return AGENT_LABELS[normalized] ?? statusLabel(normalized || "Unknown agent");
}

function recordList(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? value.filter(isRecord) : [];
}

function numberValue(value: unknown): number {
  return typeof value === "number" ? value : 0;
}

function isFinding(value: unknown): value is DetailedReportFinding {
  return (
    isRecord(value) &&
    typeof value.finding_id === "string" &&
    typeof value.issue_title === "string" &&
    Array.isArray(value.exact_occurrences)
  );
}

function findingsFromReport(report: DeliveredReport): DetailedReportFinding[] {
  const findings = new Map<string, DetailedReportFinding>();
  if (!Array.isArray(report.sections)) return [];
  const section = report.sections.find(
    (candidate) => candidate.section_key === "page_level_findings",
  );
  const values = section?.content.findings;
  if (!Array.isArray(values)) return [];
  for (const value of values) {
    if (isFinding(value)) findings.set(value.finding_id, value);
  }
  return [...findings.values()];
}

function TruncatedUrl({ url, maxLen = 60 }: { url: string; maxLen?: number }) {
  const isLink = url.startsWith("http://") || url.startsWith("https://");
  const display = url.length > maxLen ? url.slice(0, maxLen - 1) + "…" : url;
  const inner = isLink ? (
    <a href={url} target="_blank" rel="noopener noreferrer" className="break-all text-blue-600 hover:underline" title={url}>
      {display}
    </a>
  ) : (
    <span className="break-all" title={url.length > maxLen ? url : undefined}>
      {display}
    </span>
  );
  return inner;
}

function FindingDetail({ finding }: { finding: DetailedReportFinding }) {
  const fields = [
    [
      "Confidence",
      `${finding.confidence.classification}${
        finding.confidence.percent === null ? "" : ` (${finding.confidence.percent}%)`
      }`,
    ],
    ["Detecting agent", friendlyAgentName(finding.detecting_agent)],
    ["Validating agent", friendlyAgentName(finding.validating_agent)],
    ["Likely cause", finding.likely_cause],
    ["Technical explanation", finding.technical_explanation],
    ["Technical impact", finding.technical_impact],
    ["Business impact", finding.business_impact],
    ["Recommended remediation", finding.recommended_remediation],
    ["Responsible role", finding.responsible_role],
    ["Estimated effort", finding.estimated_effort_band],
    ["Verification", finding.verification_procedure],
    ["Evidence limitations", finding.evidence_limitations],
  ];
  return (
    <article
      aria-labelledby={`finding-${finding.finding_id}-heading`}
      className="min-w-0 scroll-mt-6 overflow-hidden rounded-xl border-l-4 border-orange-600 bg-slate-50 p-4"
      id={`finding-${finding.finding_id}`}
    >
      <div className="flex flex-wrap gap-2 text-xs font-bold uppercase">
        {[finding.severity, finding.category, finding.scope, finding.evidence_state].map(
          (label) => (
            <span className="rounded-full border border-slate-500 px-2 py-1" key={label}>
              {statusLabel(label)}
            </span>
          ),
        )}
      </div>
      <h5 className="mt-3 text-lg font-bold" id={`finding-${finding.finding_id}-heading`}>
        {finding.issue_title}
      </h5>
      <p className="mt-2">{finding.plain_language_explanation}</p>
      <p className="mt-2 text-sm font-semibold">
        Affected pages: {finding.affected_page_count} · Occurrences:{" "}
        {finding.occurrence_count}
        <ConceptInfoButton conceptId="occurrences" title="Occurrences" />
      </p>
      <dl className="mt-4 grid gap-x-4 gap-y-2 text-sm sm:grid-cols-[12rem_1fr]">
        {fields.map(([label, value]) => (
          <div className="contents" key={label}>
            <dt className="font-semibold">{label}</dt>
            <dd className="min-w-0 break-words">{value}</dd>
          </div>
        ))}
      </dl>
      <details className="mt-4 rounded border bg-white p-3">
        <summary className="cursor-pointer font-semibold">
          Technical evidence references ({Array.isArray(finding.evidence_references) ? finding.evidence_references.length : 0})
        </summary>
        {Array.isArray(finding.evidence_references) && finding.evidence_references.length > 0 ? (
          <ul className="mt-2 grid gap-2 text-xs">
            {finding.evidence_references.map((reference, index) => (
              <li
                className="rounded bg-slate-100 p-2 break-all"
                key={`${finding.finding_id}-reference-${index}`}
              >
                {JSON.stringify(reference)}
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-2 text-sm">No separate evidence reference was retained.</p>
        )}
      </details>
      <div className="mt-4 max-w-full overflow-x-auto overscroll-x-contain">
        <table className="w-full border-collapse text-left text-xs">
          <caption className="mb-2 text-left font-semibold">
            Exact affected locations ({finding.exact_occurrences.length})
          </caption>
          <thead>
            <tr>
              {[
                "Page",
                "Status",
                "Page type/section",
                "Affected browser",
                "Selector/resource/location",
                "Observed",
                "Expected",
                "Timestamp",
              ].map((label) => (
                <th className="border bg-slate-200 p-2" key={label} scope="col">
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {finding.exact_occurrences.map((occurrence, index) => (
              <tr key={`${finding.finding_id}-${occurrence.normalized_url}-${index}`}>
                <td className="border p-2">
                  <TruncatedUrl url={String(occurrence.normalized_url)} />
                  {occurrence.final_url !== occurrence.normalized_url && (
                    <span className="mt-1 block text-xs text-slate-500">
                      → <TruncatedUrl url={String(occurrence.final_url)} maxLen={50} />
                    </span>
                  )}
                </td>
                <td className="border p-2 break-words">
                  {occurrence.status_code !== null
                    ? `HTTP ${occurrence.status_code}`
                    : occurrence.collection_status}
                </td>
                <td className="border p-2 break-all">
                  {occurrence.page_type} / {occurrence.section}
                </td>
                <td className="border p-2 break-words">
                  {occurrence.browser_engines_affected?.length
                    ? occurrence.browser_engines_affected.join(", ")
                    : "Not applicable"}
                </td>
                <td className="border p-2">
                  {occurrence.selector ??
                    occurrence.resource_url ??
                    occurrence.location ??
                    "Not collected"}
                </td>
                <td className="border p-2 break-words">
                  {occurrence.observed_value ?? "Not collected"}
                </td>
                <td className="border p-2 break-words">
                  {occurrence.expected_value ?? "Not collected"}
                </td>
                <td className="border p-2">
                  {formatHumanTimestamp(occurrence.evidence_timestamp)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </article>
  );
}

function FilterSelect({
  label,
  onChange,
  options,
  value,
}: {
  label: string;
  onChange: (value: string) => void;
  options: string[];
  value: string;
}) {
  return (
    <label className="text-sm font-semibold">
      {label}
      <select
        className="mt-1 w-full rounded border border-slate-400 px-3 py-2 font-normal focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-600"
        onChange={(event) => onChange(event.target.value)}
        value={value}
      >
        <option value="">All</option>
        {options.map((option) => (
          <option key={option} value={option}>
            {statusLabel(option)}
          </option>
        ))}
      </select>
    </label>
  );
}

function ReportViewer({ report }: { report: DeliveredReport }) {
  const safeSections = Array.isArray(report.sections) ? report.sections : [];
  const findings = useMemo(() => findingsFromReport(report), [report]);
  const sections = useMemo(
    () => new Map(safeSections.map((section) => [section.section_key, section])),
    [safeSections],
  );
  const executive = sections.get("executive_summary")?.content ?? {};
  const scores = sections.get("scores")?.content ?? {};
  const pageFindings = sections.get("page_level_findings")?.content ?? {};
  const pageCoverage = isRecord(executive.page_coverage)
    ? executive.page_coverage
    : {};
  const browserCoverage = recordList(executive.browser_coverage);
  const inventory = recordList(pageFindings.page_inventory);
  const pageInventory = inventory.filter(
    (item) => String(item.resource_classification) === "eligible_html_page",
  );
  const assetInventory = inventory.filter((item) =>
    ["document_asset", "media_static_asset", "unsupported_resource"].includes(
      String(item.resource_classification),
    ),
  );
  const categoryScores = recordList(scores.categories);
  const actions = recordList(sections.get("priority_action_plan")?.content.actions);
  const reportAgents = recordList(
    sections.get("multi_agent_execution")?.content.agents,
  );
  const unavailableCapabilities = [
    ...new Set(
      safeSections.flatMap((section) => {
        const attribution = isRecord(section.content.agent_attribution)
          ? section.content.agent_attribution
          : {};
        return [
          ...(Array.isArray(attribution.unavailable_tools)
            ? attribution.unavailable_tools
            : []),
          ...(Array.isArray(attribution.unavailable_providers)
            ? attribution.unavailable_providers
            : []),
        ].filter((value): value is string => typeof value === "string");
      }),
    ),
  ].sort();
  const limitations = Array.isArray(executive.important_limitations)
    ? executive.important_limitations.filter(
        (value): value is string => typeof value === "string",
      )
    : [];
  const topFindings = findings
    .filter((finding) => ["critical", "high"].includes(finding.severity))
    .slice(0, 5);
  const totalOccurrences = findings.reduce(
    (total, finding) => total + finding.occurrence_count,
    0,
  );
  const affectedPageCount = numberValue(pageFindings.affected_page_count) || new Set(
    findings.flatMap((finding) =>
      finding.exact_occurrences.map((occurrence) => occurrence.normalized_url),
    ),
  ).size;
  const [viewMode, setViewMode] = useState<"executive" | "technical">("executive");
  const [search, setSearch] = useState("");
  const [severity, setSeverity] = useState("");
  const [category, setCategory] = useState("");
  const [agent, setAgent] = useState("");
  const [pageUrl, setPageUrl] = useState("");
  const [scope, setScope] = useState("");
  const [evidenceState, setEvidenceState] = useState("");
  const [inventoryFilter, setInventoryFilter] = useState("");
  const [findingsPage, setFindingsPage] = useState(0);
  const [inventoryPage, setInventoryPage] = useState(0);
  const options = useMemo(
    () => ({
      severities: [...new Set(findings.map((item) => item.severity))].sort(),
      categories: [...new Set(findings.map((item) => item.category))].sort(),
      agents: [...new Set(findings.map((item) => item.detecting_agent))].sort(),
      scopes: [...new Set(findings.map((item) => item.scope))].sort(),
    }),
    [findings],
  );
  const filteredFindings = useMemo(() => {
    const query = search.trim().toLocaleLowerCase();
    const urlQuery = pageUrl.trim().toLocaleLowerCase();
    return findings.filter((finding) => {
      const searchable = [
        finding.issue_title,
        finding.plain_language_explanation,
        finding.technical_explanation,
        finding.finding_code,
        finding.responsible_role,
      ]
        .join(" ")
        .toLocaleLowerCase();
      return (
        (!query || searchable.includes(query)) &&
        (!severity || finding.severity === severity) &&
        (!category || finding.category === category) &&
        (!agent ||
          finding.detecting_agent === agent ||
          finding.validating_agent === agent) &&
        (!scope || finding.scope === scope) &&
        (!evidenceState || finding.evidence_state === evidenceState) &&
        (!urlQuery ||
          finding.exact_occurrences.some((occurrence) =>
            occurrence.normalized_url.toLocaleLowerCase().includes(urlQuery),
          ))
      );
    });
  }, [agent, category, evidenceState, findings, pageUrl, scope, search, severity]);
  const filteredInventory = (() => {
    if (!inventoryFilter) return pageInventory;
    return pageInventory.filter((page) => {
      const result = String(page.result ?? page.analysis_status ?? "");
      const analysed = page.analysed === true;
      const scheduled = page.scheduled === true;
      const browserCount = Array.isArray(page.browser_engines_tested)
        ? page.browser_engines_tested.length
        : 0;
      if (inventoryFilter === "Analysed") return analysed;
      if (inventoryFilter === "Not analysed") return !analysed;
      if (inventoryFilter === "Failed") return result === "failed";
      if (inventoryFilter === "Not scheduled") return !scheduled;
      if (inventoryFilter === "Browser incomplete") {
        return analysed && browserCount < browserCoverage.length;
      }
      return true;
    });
  })();
  const findingPageCount = Math.max(
    1,
    Math.ceil(filteredFindings.length / FINDINGS_PAGE_SIZE),
  );
  const safeFindingsPage = Math.min(findingsPage, findingPageCount - 1);
  const visibleFindings = filteredFindings.slice(
    safeFindingsPage * FINDINGS_PAGE_SIZE,
    (safeFindingsPage + 1) * FINDINGS_PAGE_SIZE,
  );
  const inventoryPageCount = Math.max(
    1,
    Math.ceil(filteredInventory.length / INVENTORY_PAGE_SIZE),
  );
  const safeInventoryPage = Math.min(inventoryPage, inventoryPageCount - 1);
  const visibleInventory = filteredInventory.slice(
    safeInventoryPage * INVENTORY_PAGE_SIZE,
    (safeInventoryPage + 1) * INVENTORY_PAGE_SIZE,
  );
  const pagePercentage =
    typeof pageCoverage.coverage_percentage === "number"
      ? pageCoverage.coverage_percentage
      : null;
  const rawDiscoveryCompleteness = pageCoverage.discovery_completeness;
  const discoveryStageStatus = String(pageCoverage.discovery_stage_status ?? "");
  const reportTerminal = TERMINAL_STATUSES.includes(report.status ?? "");
  const discoveryPending = rawDiscoveryCompleteness === null || rawDiscoveryCompleteness === undefined;
  const discoveryRunning = discoveryStageStatus === "running";
  const discoveryCompleteness = discoveryPending
    ? reportTerminal
      ? "not_recorded"
      : discoveryRunning ? "running" : "pending"
    : String(rawDiscoveryCompleteness);
  const discoveryComplete = discoveryCompleteness === "complete";
  const discoveryCompletenessMessage = String(
    pageCoverage.discovery_completeness_message ?? "",
  );
  const browserAttemptDenominator = browserCoverage.reduce(
    (total, engine) => total + numberValue(engine.eligible_pages),
    0,
  );
  const browserTestedNumerator = browserCoverage.reduce(
    (total, engine) => total + numberValue(engine.tested_pages),
    0,
  );
  const safeUnavailableSections = Array.isArray(report.unavailable_sections) ? report.unavailable_sections : [];
  const reportStatus = displayStatus(report.status, "historical");
  const reportQuality = (() => {
    const n = report.evidence_coverage_numerator;
    const d = report.evidence_coverage_denominator;
    const hasScore = typeof scores.overall_score === "number";
    const confidence = report.confidence_percent;
    if (d === 0 || n === 0 || discoveryCompleteness === "failed") return "FAILED";
    const ratio = n / d;
    if (ratio >= 0.9 && hasScore && confidence !== null && confidence >= 50) return "COMPLETE";
    if (ratio >= 0.4 || hasScore) return "PARTIAL";
    return "INCONCLUSIVE";
  })();
  const qualityColor: Record<string, string> = {
    COMPLETE: "bg-green-100 text-green-800 border-green-300",
    PARTIAL: "bg-yellow-100 text-yellow-800 border-yellow-300",
    INCONCLUSIVE: "bg-orange-100 text-orange-800 border-orange-300",
    FAILED: "bg-red-100 text-red-800 border-red-300",
  };

  return (
    <article
      aria-labelledby={`delivered-report-${report.report_id}`}
      className="mt-6 min-w-0 max-w-full overflow-hidden rounded-2xl border border-slate-200 bg-white"
    >
      {/* ======== REPORT HEADER ======== */}
      <header className="bg-slate-950 px-6 py-5 text-white">
        <p className="text-xs font-semibold uppercase tracking-widest text-orange-400">
          ZuiGO Website Intelligence
        </p>
        <h3 className="mt-2 text-2xl font-bold" id={`delivered-report-${report.report_id}`}>
          {String(executive.website_analysed ?? "Website Analysis")}
        </h3>
        <p className="mt-2 flex flex-wrap items-center gap-2 text-sm text-slate-300">
          <span>Immutable evidence snapshot</span>
          <span className="text-slate-500">·</span>
          <span>{reportStatus}</span>
          <span className={`inline-block rounded-full border px-2.5 py-0.5 text-xs font-bold ${qualityColor[reportQuality] ?? "bg-slate-100 text-slate-700 border-slate-300"}`}>
            {reportQuality}
          </span>
        </p>
        <div className="mt-4 grid gap-x-8 gap-y-2 text-sm sm:grid-cols-2">
          <div>
            <span className="text-slate-400">Website</span>
            <p className="mt-0.5 break-all">{String(executive.website_analysed ?? "Unavailable")}</p>
          </div>
          <div>
            <span className="text-slate-400">Analysis date</span>
            <p className="mt-0.5">{formatHumanTimestamp(executive.analysis_date)}</p>
          </div>
        </div>

        {/* Score strip */}
        <div className="mt-4 flex flex-wrap items-center gap-6 rounded-lg bg-white/10 px-4 py-3">
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-bold">
              {typeof scores.overall_score === "number"
                ? `${scores.overall_score}`
                : "—"}
            </span>
            <span className="text-sm text-slate-300">/100</span>
          </div>
          <div className="text-sm text-slate-300">
            <span>Confidence {report.confidence_percent === null ? "N/A" : `${report.confidence_percent}%`}</span>
            <ConceptInfoButton conceptId="report_confidence" title="Report confidence" />
          </div>
          <div className="ml-auto">
            <div className="inline-flex rounded-lg border border-white/20 bg-white/10 p-0.5" role="tablist" aria-label="Report view mode">
              <button
                aria-selected={viewMode === "executive"}
                className={`rounded-md px-4 py-2 text-sm font-medium transition-colors ${viewMode === "executive" ? "bg-white text-slate-900 shadow-sm" : "text-white/80 hover:text-white"}`}
                onClick={() => setViewMode("executive")}
                role="tab"
                type="button"
              >
                Executive
              </button>
              <button
                aria-selected={viewMode === "technical"}
                className={`rounded-md px-4 py-2 text-sm font-medium transition-colors ${viewMode === "technical" ? "bg-white text-slate-900 shadow-sm" : "text-white/80 hover:text-white"}`}
                onClick={() => setViewMode("technical")}
                role="tab"
                type="button"
              >
                Technical
              </button>
            </div>
          </div>
        </div>
      </header>

      <div className="space-y-5 p-5">
        {safeUnavailableSections.length > 0 && (
          <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3" role="note">
            <p className="text-sm font-medium text-amber-800">
              Partial evidence — unavailable sections: {safeUnavailableSections.join(", ")}.
              Not represented as successful or issue-free.
            </p>
          </div>
        )}

        {/* ======== EXECUTIVE VIEW ======== */}
        {viewMode === "executive" && (
          <>
            {/* 1. Executive Summary */}
            <section className="rounded-xl border border-slate-200 p-5" id="executive-summary">
              <h4 className="text-lg font-bold text-slate-900">Executive Summary</h4>
              <div className="mt-3 grid gap-4 sm:grid-cols-3">
                <MetricStat label="Overall Score" value={typeof scores.overall_score === "number" ? `${scores.overall_score}/100` : "Unavailable"} />
                <MetricStat label="Confidence" value={report.confidence_percent === null ? "Unavailable" : `${report.confidence_percent}%`} />
                <MetricStat label="Findings" value={`${findings.length} unique`} detail={`${totalOccurrences} occurrences · ${affectedPageCount} pages`} />
              </div>
              {limitations.length > 0 && (
                <p className="mt-4 text-xs text-slate-500">
                  {limitations.length} limitation{limitations.length > 1 ? "s" : ""} noted — see{" "}
                  <a className="underline" href="#evidence-limitations">Key Limitations</a>.
                </p>
              )}
            </section>

            {/* 2. Coverage */}
            <section className="rounded-xl border border-slate-200 p-5" id="website-coverage">
              <h4 className="text-lg font-bold text-slate-900">Website Coverage</h4>
              <div className="mt-3 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                <MetricStat
                  label="Analysed-page coverage"
                  value={`${numberValue(pageCoverage.coverage_numerator)}/${numberValue(pageCoverage.coverage_denominator)}`}
                  detail={pagePercentage === null ? "Unavailable" : `${pagePercentage.toFixed(1)}% of eligible pages`}
                />
                <MetricStat
                  label="Discovery completeness"
                  value={discoveryPending ? (reportTerminal ? "Not Recorded" : discoveryRunning ? "In Progress" : "Pending") : statusLabel(discoveryCompleteness)}
                />
                <MetricStat
                  label="Browser coverage"
                  value={`${browserTestedNumerator}/${browserAttemptDenominator}`}
                  detail="Engine-page tests completed"
                />
                <MetricStat
                  label="Evidence completeness"
                  value={`${report.evidence_coverage_numerator}/${report.evidence_coverage_denominator}`}
                  detail="Required evidence groups"
                />
              </div>
              {!discoveryComplete && !discoveryPending && (
                <p className="mt-3 text-sm text-amber-700">
                  {discoveryCompletenessMessage || "Website discovery was incomplete, so full-site coverage is unknown."}
                </p>
              )}
            </section>

            {/* 3. Category Scores */}
            <section className="rounded-xl border border-slate-200 p-5" id="scores-summary">
              <h4 className="text-lg font-bold text-slate-900">Category Scores</h4>
              <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
                {categoryScores.map((categoryScore) => {
                  const scoreValue = categoryScore.evidence_available === false
                    ? null
                    : typeof categoryScore.score === "number"
                      ? categoryScore.score
                      : null;
                  return (
                    <div key={String(categoryScore.category_id)}>
                      <ScoreBar
                        score={scoreValue}
                        label={statusLabel(String(categoryScore.category_id))}
                      />
                      {categoryScore.included === false && categoryScore.exclusion_reason ? (
                        <p className="mt-1 text-xs text-slate-500">
                          {String(categoryScore.exclusion_reason)}
                        </p>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            </section>

            {/* 4. Top Findings */}
            <section className="rounded-xl border border-slate-200 p-5" id="top-findings">
              <div className="flex items-baseline justify-between">
                <h4 className="text-lg font-bold text-slate-900">Top Findings</h4>
                <span className="text-sm text-slate-500">
                  {findings.length} unique · {totalOccurrences} occurrences
                </span>
              </div>
              {topFindings.length > 0 ? (
                <div className="mt-4 space-y-3">
                  {topFindings.map((finding) => (
                    <div
                      className="flex items-start gap-3 rounded-lg border border-slate-200 p-4"
                      key={finding.finding_id}
                    >
                      <StatusBadge status={finding.severity} />
                      <div className="min-w-0 flex-1">
                        <p className="font-medium text-slate-900">{finding.issue_title}</p>
                        <p className="mt-1 text-sm text-slate-500 line-clamp-2">
                          {finding.plain_language_explanation}
                        </p>
                        <div className="mt-2 flex flex-wrap gap-3 text-xs text-slate-500">
                          <span>{finding.affected_page_count} pages affected</span>
                          <span>{finding.occurrence_count} occurrences</span>
                          <span>{statusLabel(finding.category)}</span>
                        </div>
                      </div>
                      <button
                        type="button"
                        className="shrink-0 text-sm font-medium text-blue-600 hover:text-blue-800"
                        onClick={() => { setViewMode("technical"); setTimeout(() => document.getElementById(`finding-${finding.finding_id}`)?.scrollIntoView({ behavior: "smooth" }), 100); }}
                      >
                        Details
                      </button>
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyState
                  title="No critical or high-severity findings detected"
                  description="Review all findings in Technical View for the complete picture."
                />
              )}
            </section>

            {/* 5. Priority Action Plan */}
            <section className="rounded-xl border border-slate-200 p-5" id="action-plan-summary">
              <h4 className="text-lg font-bold text-slate-900">Priority Action Plan</h4>
              {String(sections.get("priority_action_plan")?.content.generation_status ?? "") ===
                "deterministic_from_findings" && (
                <p className="mt-2 text-xs text-blue-700">
                  Generated from evidence findings. AI-prioritized plan unavailable.
                </p>
              )}
              {actions.length > 0 ? (
                <div className="mt-4 space-y-3">
                  {actions.slice(0, 5).map((action, index) => (
                    <div className="rounded-lg border border-slate-200 p-4" key={`${index}-${String(action.title)}`}>
                      <div className="flex items-start gap-3">
                        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-slate-900 text-xs font-bold text-white">
                          {index + 1}
                        </span>
                        <div className="min-w-0 flex-1">
                          <p className="font-medium text-slate-900">
                            {String(action.title ?? "Recommended action")}
                          </p>
                          <p className="mt-1 text-sm text-slate-600">
                            {String(action.impact ?? "Impact not quantified.")}
                          </p>
                          <div className="mt-2 flex flex-wrap gap-3 text-xs text-slate-500">
                            <span><span className="font-medium text-slate-600">Owner:</span> {String(action.responsible_role ?? "Unassigned")}</span>
                            <span><span className="font-medium text-slate-600">Effort:</span> {String(action.effort ?? "Unestimated")}</span>
                          </div>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyState
                  title="No evidence-grounded actions available"
                  description="This may indicate that no actionable findings were retained."
                />
              )}
            </section>

            {/* 6. Browser Compatibility */}
            <section className="rounded-xl border border-slate-200 p-5" id="browser-coverage">
              <h4 className="text-lg font-bold text-slate-900">Browser Compatibility</h4>
              <p className="mt-1 text-xs text-slate-500">
                Unavailable engines are not represented as passed or failed.
              </p>
              {browserCoverage.length > 0 ? (
                <div className="mt-4 grid gap-3 sm:grid-cols-3">
                  {browserCoverage.map((engine) => {
                    const tested = numberValue(engine.tested_pages);
                    const eligible = numberValue(engine.eligible_pages);
                    const isUnavailable = String(engine.availability_status) === "unavailable";
                    return (
                      <div
                        className={`rounded-lg border p-4 ${isUnavailable ? "border-slate-200 bg-slate-50" : "border-slate-200 bg-white"}`}
                        key={String(engine.engine)}
                      >
                        <p className="text-sm font-semibold text-slate-700">
                          {ENGINE_LABELS[String(engine.engine)] ?? statusLabel(String(engine.engine))}
                        </p>
                        {isUnavailable ? (
                          <>
                            <p className="mt-1 text-sm text-slate-500">Unavailable in this environment</p>
                            <p className="mt-0.5 text-xs text-slate-400">Not represented as passed or failed</p>
                          </>
                        ) : (
                          <>
                            <p className="mt-1 text-xl font-bold text-slate-900">{tested}/{eligible} tested</p>
                            <StatusBadge status={tested === eligible && eligible > 0 ? "compatible" : tested > 0 ? "partial" : "unavailable"} />
                          </>
                        )}
                      </div>
                    );
                  })}
                </div>
              ) : (
                <EmptyState title="Browser compatibility testing was not available for this analysis." />
              )}
            </section>

            {/* 7. Key Limitations */}
            <section className="rounded-xl border border-slate-200 p-5" id="evidence-limitations">
              <h4 className="text-lg font-bold text-slate-900">Key Limitations</h4>
              <p className="mt-2 text-sm text-slate-500">
                {report.evidence_coverage_numerator}/{report.evidence_coverage_denominator} report sections have available evidence.
              </p>
              {limitations.length > 0 ? (
                <ul className="mt-3 space-y-2">
                  {limitations.map((limitation) => (
                    <li key={limitation} className="flex gap-2 text-sm text-slate-600">
                      <span className="mt-0.5 text-slate-400">•</span>
                      {limitation}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-3 text-sm text-slate-500">No specific limitations recorded.</p>
              )}
            </section>

            {/* 8. Export / reference controls */}
            <section aria-labelledby={`exports-${report.report_id}`}>
              <h4 className="text-lg font-bold text-slate-900" id={`exports-${report.report_id}`}>
                Export Report
              </h4>
              <div className="mt-3 flex flex-wrap gap-2">
                {report.artifacts.map((artifact) => (
                  <a
                    className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
                    href={reportDeliveryApi.downloadUrl(report.report_id, artifact.format)}
                    key={artifact.artifact_id}
                  >
                    {artifact.format.toUpperCase()}
                  </a>
                ))}
                {[
                  ["presentation_pdf", "Presentation PDF"],
                  ["technical_appendix", "Technical Appendix"],
                  ["page_inventory", "Page Inventory JSON"],
                ].map(([format, label]) => (
                  <a
                    className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
                    href={reportDeliveryApi.downloadUrl(report.report_id, format)}
                    key={format}
                  >
                    {label}
                  </a>
                ))}
              </div>
            </section>
          </>
        )}

        {/* ======== TECHNICAL VIEW ======== */}
        {viewMode === "technical" && (
          <>
            {/* 1. All Findings */}
            <section className="rounded-xl border border-slate-200 p-5" id="all-findings">
              <h4 className="text-lg font-bold text-slate-900">Findings Explorer</h4>
              <p className="mt-1 text-xs text-slate-500">
                Every retained finding. Search, filter, and review exact occurrences.
              </p>
              <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <label className="text-sm font-medium text-slate-700">
                  Search
                  <input
                    className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                    onChange={(event) => setSearch(event.target.value)}
                    type="search"
                    value={search}
                    placeholder="Search findings…"
                  />
                </label>
                <label className="text-sm font-medium text-slate-700">
                  Page / URL
                  <input
                    className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                    onChange={(event) => setPageUrl(event.target.value)}
                    type="search"
                    value={pageUrl}
                    placeholder="Filter by URL…"
                  />
                </label>
                <FilterSelect label="Severity" onChange={setSeverity} options={options.severities} value={severity} />
                <FilterSelect label="Category" onChange={setCategory} options={options.categories} value={category} />
                <FilterSelect label="Agent" onChange={setAgent} options={options.agents} value={agent} />
                <FilterSelect label="Scope" onChange={setScope} options={options.scopes} value={scope} />
                <FilterSelect label="Evidence state" onChange={setEvidenceState} options={["available", "incomplete", "unavailable"]} value={evidenceState} />
              </div>
              <p aria-live="polite" className="mt-3 text-sm text-slate-500">
                {filteredFindings.length ? `${safeFindingsPage * FINDINGS_PAGE_SIZE + 1}–${Math.min(filteredFindings.length, (safeFindingsPage + 1) * FINDINGS_PAGE_SIZE)}` : "0"} of {filteredFindings.length} findings ({findings.length} total)
              </p>
              <div className="mt-4 grid gap-4">
                {filteredFindings.length > 0 ? (
                  visibleFindings.map((finding) => (
                    <FindingDetail finding={finding} key={finding.finding_id} />
                  ))
                ) : (
                  <EmptyState
                    title="No findings match these filters"
                    description="This filtered state does not prove the site has no issues."
                  />
                )}
              </div>
              {filteredFindings.length > FINDINGS_PAGE_SIZE && (
                <nav aria-label="Finding pages" className="mt-4 flex items-center justify-between gap-3">
                  <button className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium disabled:opacity-40" disabled={safeFindingsPage === 0} onClick={() => setFindingsPage(Math.max(0, safeFindingsPage - 1))} type="button">Previous</button>
                  <span className="text-sm text-slate-500">Page {safeFindingsPage + 1} of {findingPageCount}</span>
                  <button className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium disabled:opacity-40" disabled={safeFindingsPage >= findingPageCount - 1} onClick={() => setFindingsPage(Math.min(findingPageCount - 1, safeFindingsPage + 1))} type="button">Next</button>
                </nav>
              )}
            </section>

            {/* 2. Page Inventory */}
            <section className="rounded-xl border border-slate-200 p-5" id="page-results">
              <h4 className="text-lg font-bold text-slate-900">Page Inventory</h4>
              <div className="mt-3 flex flex-wrap gap-2" aria-label="Page Inventory filters">
                {["", "Analysed", "Not analysed", "Failed", "Not scheduled", "Browser incomplete"].map((filter) => (
                  <button
                    className={`rounded-md border px-3 py-1.5 text-sm font-medium ${inventoryFilter === filter ? "border-blue-500 bg-blue-50 text-blue-700" : "border-slate-300 text-slate-600 hover:bg-slate-50"}`}
                    key={filter || "All"}
                    onClick={() => setInventoryFilter(filter)}
                    type="button"
                  >
                    {filter || "All pages"}
                  </button>
                ))}
              </div>
              <p aria-live="polite" className="mt-2 text-sm text-slate-500">
                {filteredInventory.length > INVENTORY_PAGE_SIZE
                  ? `${safeInventoryPage * INVENTORY_PAGE_SIZE + 1}–${Math.min((safeInventoryPage + 1) * INVENTORY_PAGE_SIZE, filteredInventory.length)} of `
                  : ""}
                {filteredInventory.length} of {pageInventory.length} eligible pages.
                {assetInventory.length > 0 && ` ${assetInventory.length} assets listed separately.`}
              </p>
              <div className="mt-3 overflow-x-auto">
                <table className="w-full min-w-[800px] border-collapse text-left text-sm">
                  <thead>
                    <tr className="border-b border-slate-200">
                      {["URL", "Eligibility", "Scheduled", "Visited", "Analysed", "Browser engines", "Result", "Reason"].map((label) => (
                        <th className="bg-slate-50 px-3 py-2 text-xs font-semibold text-slate-500" key={label} scope="col">{label}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {visibleInventory.map((page) => (
                      <tr key={String(page.url)}>
                        <td className="px-3 py-2"><UrlCell url={String(page.url)} /></td>
                        <td className="px-3 py-2"><StatusBadge status={String(page.eligibility ?? "unknown")} size="xs" /></td>
                        <td className="px-3 py-2">{page.scheduled === true ? "Yes" : "No"}</td>
                        <td className="px-3 py-2">{page.visited === true ? "Yes" : "No"}</td>
                        <td className="px-3 py-2">{page.analysed === true ? "Yes" : "No"}</td>
                        <td className="px-3 py-2 text-xs">{Array.isArray(page.browser_engines_tested) && page.browser_engines_tested.length ? page.browser_engines_tested.map(String).map((e) => ENGINE_LABELS[e] ?? statusLabel(e)).join(", ") : "Not tested"}</td>
                        <td className="px-3 py-2"><StatusBadge status={String(page.result ?? "unknown")} size="xs" /></td>
                        <td className="max-w-48 px-3 py-2 text-xs text-slate-500">{String(page.failure_reason ?? page.exclusion_reason ?? "None")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {filteredInventory.length > INVENTORY_PAGE_SIZE && (
                <div className="mt-3 flex items-center gap-3 text-sm">
                  <button className="rounded-md border border-slate-300 px-3 py-1 text-sm disabled:opacity-40" disabled={safeInventoryPage === 0} onClick={() => setInventoryPage(Math.max(0, safeInventoryPage - 1))} type="button">Previous</button>
                  <span className="text-sm text-slate-500">Page {safeInventoryPage + 1} of {inventoryPageCount}</span>
                  <button className="rounded-md border border-slate-300 px-3 py-1 text-sm disabled:opacity-40" disabled={safeInventoryPage >= inventoryPageCount - 1} onClick={() => setInventoryPage(Math.min(inventoryPageCount - 1, safeInventoryPage + 1))} type="button">Next</button>
                </div>
              )}
              {assetInventory.length > 0 && (
                <details className="mt-4 rounded-lg border border-slate-200 p-3">
                  <summary className="cursor-pointer text-sm font-semibold text-slate-700">
                    Document and Asset Inventory ({assetInventory.length})
                  </summary>
                  <div className="mt-3 overflow-x-auto">
                    <table className="w-full min-w-[700px] border-collapse text-left text-sm">
                      <thead>
                        <tr className="border-b border-slate-200">
                          {["URL", "Final URL", "HTTP status", "Type", "Classification", "Detection", "Reason", "Browser handling"].map((label) => (
                            <th className="bg-slate-50 px-3 py-2 text-xs font-semibold text-slate-500" key={label} scope="col">{label}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100">
                        {assetInventory.map((item) => (
                          <tr key={String(item.url)}>
                            <td className="px-3 py-2"><UrlCell url={String(item.url)} /></td>
                            <td className="px-3 py-2"><UrlCell url={String(item.final_url ?? "Not collected")} /></td>
                            <td className="px-3 py-2">{typeof item.http_status === "number" ? `HTTP ${item.http_status}` : "N/A"}</td>
                            <td className="max-w-32 break-words px-3 py-2 text-xs">{String(item.response_content_type ?? "N/A")}</td>
                            <td className="px-3 py-2 text-xs">{statusLabel(String(item.resource_classification))}</td>
                            <td className="max-w-32 break-words px-3 py-2 text-xs">{String(item.content_type_detection)}</td>
                            <td className="max-w-32 break-words px-3 py-2 text-xs">{String(item.failure_reason ?? item.exclusion_reason)}</td>
                            <td className="px-3 py-2 text-xs">{String(item.browser_navigation)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </details>
              )}
            </section>

            {/* 3. Browser Matrix */}
            <section className="rounded-xl border border-slate-200 p-5" id="browser-coverage">
              <h4 className="text-lg font-bold text-slate-900">Browser Compatibility</h4>
              {browserCoverage.length > 0 ? (
                <div className="mt-4 grid gap-3 sm:grid-cols-3">
                  {browserCoverage.map((engine) => {
                    const tested = numberValue(engine.tested_pages);
                    const eligible = numberValue(engine.eligible_pages);
                    const isUnavailable = String(engine.availability_status) === "unavailable";
                    const passed = numberValue(engine.passed_pages);
                    const partial = numberValue(engine.partial_pages);
                    const failed = numberValue(engine.failed_pages);
                    return (
                      <div className={`rounded-lg border p-4 ${isUnavailable ? "border-slate-200 bg-slate-50" : "border-slate-200"}`} key={String(engine.engine)}>
                        <p className="text-sm font-semibold text-slate-700">
                          {ENGINE_LABELS[String(engine.engine)] ?? statusLabel(String(engine.engine))}
                        </p>
                        {isUnavailable ? (
                          <p className="mt-1 text-sm text-slate-500">Unavailable in this environment</p>
                        ) : (
                          <>
                            <p className="mt-1 text-xl font-bold">{tested}/{eligible} tested</p>
                            <div className="mt-2 grid grid-cols-3 gap-1 text-xs text-slate-500">
                              <span>Passed: {passed}</span>
                              <span>Partial: {partial}</span>
                              <span>Failed: {failed}</span>
                            </div>
                          </>
                        )}
                      </div>
                    );
                  })}
                </div>
              ) : (
                <EmptyState title="No browser compatibility data available." />
              )}
            </section>

            {/* 4. Agent Execution */}
            <section className="rounded-xl border border-slate-200 p-5" id="technical-details">
              <h4 className="text-lg font-bold text-slate-900">Agent Execution</h4>
              <p className="mt-1 text-xs text-slate-500">
                Multi-agent orchestration details. Results above are derived from evidence produced by these agents.
              </p>
              <div className="mt-4 grid gap-2 sm:grid-cols-2">
                {reportAgents.map((reportAgent) => (
                  <div className="rounded-lg border border-slate-200 p-3" key={String(reportAgent.agent_id)}>
                    <p className="font-medium text-slate-900">{friendlyAgentName(reportAgent.agent_id)}</p>
                    <div className="mt-1 flex items-center gap-2">
                      <StatusBadge status={String(reportAgent.status ?? "not_recorded")} size="xs" />
                      {typeof reportAgent.status_explanation === "string" && (
                        <span className="text-xs text-slate-500">{reportAgent.status_explanation}</span>
                      )}
                    </div>
                    <p className="mt-1 text-xs text-slate-500">
                      Evidence: {Array.isArray(reportAgent.evidence_produced) ? reportAgent.evidence_produced.length : 0} references
                    </p>
                  </div>
                ))}
              </div>
              {unavailableCapabilities.length > 0 && (
                <p className="mt-3 text-xs text-slate-500">
                  Unavailable tools/providers: {unavailableCapabilities.map(statusLabel).join(", ")}
                </p>
              )}
            </section>

            {/* 5. Report Sections */}
            <section className="rounded-xl border border-slate-200 p-5">
              <h4 className="text-lg font-bold text-slate-900">Report Sections</h4>
              <div className="mt-4 grid gap-2 sm:grid-cols-2">
                {report.sections.map((section) => (
                  <div className="rounded-lg border border-slate-200 p-3" key={section.section_id}>
                    <div className="flex items-start justify-between gap-2">
                      <p className="font-medium text-slate-900">{section.title}</p>
                      <StatusBadge status={section.status ?? "unknown"} size="xs" />
                    </div>
                    <p className="mt-1 text-xs text-slate-500">
                      {section.evidence_references.length} evidence references
                    </p>
                    {section.unavailable_reason && (
                      <p className="mt-1 text-xs text-amber-700">{section.unavailable_reason}</p>
                    )}
                    {isRecord(section.content.agent_attribution) &&
                      recordList(section.content.agent_attribution.agents_involved).length > 0 && (
                        <details className="mt-2 text-xs">
                          <summary className="cursor-pointer font-medium text-slate-600">Agent attribution</summary>
                          <ul className="mt-1 space-y-1 pl-3">
                            {recordList(section.content.agent_attribution.agents_involved).map((sectionAgent) => (
                              <li key={`${section.section_id}-${String(sectionAgent.agent_id)}`} className="text-slate-500">
                                {friendlyAgentName(sectionAgent.agent_id)}: {displayStatus(String(sectionAgent.execution_status ?? "not recorded"), "historical")}
                              </li>
                            ))}
                          </ul>
                        </details>
                      )}
                  </div>
                ))}
              </div>
            </section>

            {/* 6. Methodology / Versions */}
            <section className="rounded-xl border border-slate-200 p-5" id="methodology">
              <h4 className="text-lg font-bold text-slate-900">Methodology</h4>
              <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-2">
                <div>
                  <dt className="text-slate-500">Report ID</dt>
                  <dd className="mt-0.5 break-all font-mono text-xs">{report.report_id}</dd>
                </div>
                <div>
                  <dt className="text-slate-500">Report status</dt>
                  <dd className="mt-0.5">{reportStatus}</dd>
                </div>
                <div>
                  <dt className="text-slate-500">Evidence coverage</dt>
                  <dd className="mt-0.5">{report.evidence_coverage_numerator}/{report.evidence_coverage_denominator}</dd>
                </div>
                <div>
                  <dt className="text-slate-500">Confidence</dt>
                  <dd className="mt-0.5">{report.confidence_percent === null ? "Not available" : `${report.confidence_percent}%`}</dd>
                </div>
              </dl>
            </section>

            {/* 7. All Limitations */}
            {limitations.length > 0 && (
              <section className="rounded-xl border border-slate-200 p-5" id="all-limitations">
                <h4 className="text-lg font-bold text-slate-900">All Limitations</h4>
                <ul className="mt-3 space-y-2">
                  {limitations.map((limitation) => (
                    <li key={limitation} className="flex gap-2 text-sm text-slate-600">
                      <span className="mt-0.5 text-slate-400">•</span>
                      {limitation}
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {/* Export (also in technical view) */}
            <section aria-labelledby={`exports-tech-${report.report_id}`}>
              <h4 className="text-lg font-bold text-slate-900" id={`exports-tech-${report.report_id}`}>
                Export Report
              </h4>
              <div className="mt-3 flex flex-wrap gap-2">
                {report.artifacts.map((artifact) => (
                  <a
                    className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
                    href={reportDeliveryApi.downloadUrl(report.report_id, artifact.format)}
                    key={artifact.artifact_id}
                  >
                    {artifact.format.toUpperCase()}
                  </a>
                ))}
                {[
                  ["presentation_pdf", "Presentation PDF"],
                  ["technical_appendix", "Technical Appendix"],
                  ["page_inventory", "Page Inventory JSON"],
                ].map(([format, label]) => (
                  <a
                    className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
                    href={reportDeliveryApi.downloadUrl(report.report_id, format)}
                    key={format}
                  >
                    {label}
                  </a>
                ))}
              </div>
            </section>
          </>
        )}
      </div>
    </article>
  );
}

export function ReportDeliveryPanel({
  projectId,
  websiteId,
  analysisRunId,
  workflowExecutionId,
  compact = false,
  showStartAction = true,
  onProgressChange,
  onReportAvailabilityChange,
}: ReportDeliveryPanelProps) {
  const [reports, setReports] = useState<PaginatedReports>({
    items: [],
    total: 0,
    limit: PAGE_SIZE,
    offset: 0,
  });
  const [selected, setSelected] = useState<DeliveredReport | null>(null);
  const [progress, setProgress] = useState<WorkflowProgress | null>(null);
  const [executionId, setExecutionId] = useState(() => {
    if (workflowExecutionId) return workflowExecutionId;
    if (typeof window === "undefined" || !projectId) return "";
    return window.localStorage.getItem(executionKey(projectId, websiteId)) ?? "";
  });
  const [analysisId, setAnalysisId] = useState(analysisRunId ?? "");
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [acting, setActing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [progressInterrupted, setProgressInterrupted] = useState(false);
  const [historyInterrupted, setHistoryInterrupted] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const resolvedAnalysisId = analysisRunId ?? analysisId;
  const resolvedExecutionId = workflowExecutionId ?? executionId;

  const loadReports = useCallback(async (): Promise<boolean> => {
    try {
      const result = resolvedAnalysisId
        ? await reportDeliveryApi.forRun(resolvedAnalysisId, PAGE_SIZE, offset)
        : await reportDeliveryApi.history(websiteId, PAGE_SIZE, offset);
      setReports(result);
      setSelected((current) => current ?? result.items[0] ?? null);
      setHistoryError(null);
      setHistoryInterrupted(false);
      onReportAvailabilityChange?.(
        result.items.some((item) =>
          ["completed", "partial"].includes(item.status),
        ),
      );
      return true;
    } catch (requestError) {
      if (isTransientConnectionError(requestError)) {
        setHistoryInterrupted(true);
      } else {
        setHistoryError(
          requestError instanceof Error
            ? requestError.message
            : "Unable to load report history.",
        );
      }
      return false;
    } finally {
      setLoading(false);
    }
  }, [
    offset,
    onReportAvailabilityChange,
    resolvedAnalysisId,
    websiteId,
  ]);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    let failureCount = 0;

    async function loadWithRecovery() {
      const succeeded = await loadReports();
      if (cancelled || succeeded) return;
      failureCount += 1;
      const delay = Math.min(15_000, 2_000 * 2 ** Math.min(failureCount - 1, 3));
      timer = window.setTimeout(() => void loadWithRecovery(), delay);
    }

    timer = window.setTimeout(() => void loadWithRecovery(), 0);
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [loadReports]);

  const loadProgress = useCallback(async (): Promise<boolean> => {
    if (!resolvedExecutionId) return true;
    try {
      const current = await reportDeliveryApi.progress(resolvedExecutionId);
      setProgress(current);
      if (current.analysis_run_id) setAnalysisId(current.analysis_run_id);
      setProgressInterrupted(false);
      onProgressChange?.(current);
      return true;
    } catch (requestError) {
      if (isTransientConnectionError(requestError)) {
        setProgressInterrupted(true);
      } else {
        setError(
          requestError instanceof Error
            ? requestError.message
            : "Unable to load workflow progress.",
        );
      }
      return false;
    }
  }, [onProgressChange, resolvedExecutionId]);

  useEffect(() => {
    if (!resolvedExecutionId) return;
    let cancelled = false;
    let timer: number | undefined;
    let failureCount = 0;

    async function poll() {
      const succeeded = await loadProgress();
      if (cancelled) return;
      failureCount = succeeded ? 0 : failureCount + 1;
      const delay = succeeded
        ? 2_000
        : Math.min(15_000, 2_000 * 2 ** Math.min(failureCount - 1, 3));
      timer = window.setTimeout(() => void poll(), delay);
    }

    timer = window.setTimeout(() => void poll(), 0);
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [loadProgress, resolvedExecutionId]);

  useEffect(() => {
    if (!progress || !TERMINAL_STATUSES.includes(progress.status)) return;
    const timer = window.setTimeout(() => void loadReports(), 0);
    return () => window.clearTimeout(timer);
  }, [loadReports, progress]);

  async function startAnalysis() {
    if (!projectId) return;
    setActing(true);
    setError(null);
    setNotice(null);
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 30_000);
    try {
      const started = await reportDeliveryApi.startAnalysis(
        projectId,
        websiteId,
        createKey("full-analysis"),
      );
      setExecutionId(started.workflow_execution_id);
      setAnalysisId(started.analysis_run_id);
      window.localStorage.setItem(
        executionKey(projectId, websiteId),
        started.workflow_execution_id,
      );
      setNotice(
        started.reused
          ? "The existing idempotent analysis journey was reopened."
          : "Full analysis accepted. Evidence collection will run before the agent workflow.",
      );
      await loadProgress();
    } catch (requestError) {
      if (requestError instanceof DOMException && requestError.name === "AbortError") {
        setError("Starting the analysis timed out. The server may be busy — try again.");
      } else {
        setError(
          requestError instanceof Error
            ? requestError.message
            : "Unable to start the full analysis.",
        );
      }
    } finally {
      window.clearTimeout(timeout);
      setActing(false);
    }
  }

  async function generateReport() {
    if (!resolvedAnalysisId) return;
    setActing(true);
    setError(null);
    setNotice(null);
    try {
      const report = await reportDeliveryApi.generate(
        resolvedAnalysisId,
        createKey("report"),
        resolvedExecutionId || undefined,
      );
      setSelected(report);
      setNotice(
        report.status === "completed"
          ? "Immutable report and all three exports were generated."
          : "A partial immutable report was generated with unavailable evidence identified.",
      );
      await loadReports();
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Unable to generate the report.",
      );
    } finally {
      setActing(false);
    }
  }

  async function performWorkflowAction(action: "cancel" | "resume") {
    if (!resolvedExecutionId) return;
    setActing(true);
    setError(null);
    setNotice(null);
    try {
      const result =
        action === "cancel"
          ? await reportDeliveryApi.cancel(resolvedExecutionId)
          : await reportDeliveryApi.resume(resolvedExecutionId);
      setNotice(
        action === "cancel"
          ? "The workflow cancellation was recorded without deleting evidence."
          : `The workflow was queued for a safe retry from retained state (${statusLabel(result.status)}).`,
      );
      await loadProgress();
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : `Unable to ${action} the workflow.`,
      );
    } finally {
      setActing(false);
    }
  }

  const canGenerate =
    Boolean(resolvedAnalysisId) &&
    Boolean(progress && ["completed", "partial"].includes(progress.status)) &&
    Boolean(progress?.report_generation_available);

  return (
    <section
      aria-labelledby={`report-delivery-${websiteId}`}
      className={`${compact ? "mt-6" : "mt-8"} rounded-2xl border border-slate-200 bg-white p-5`}
    >
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-bold uppercase tracking-wide text-slate-500">
            End-to-end delivery
          </p>
          <h2 className="mt-1 text-xl font-bold" id={`report-delivery-${websiteId}`}>
            Analysis progress and final reports
          </h2>
          <p className="mt-1 text-sm text-slate-600">
            Persisted evidence remains the source of truth for every report section.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {projectId && showStartAction && (
            <button
              className="rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-600"
              disabled={acting || Boolean(progress && !TERMINAL_STATUSES.includes(progress.status))}
              onClick={() => void startAnalysis()}
              type="button"
            >
              {acting ? "Starting…" : "Start full analysis"}
            </button>
          )}
          <button
            className="rounded-lg border border-slate-400 px-4 py-2 text-sm font-semibold disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-600"
            disabled={acting || !canGenerate}
            onClick={() => void generateReport()}
            type="button"
          >
            Generate immutable report
          </button>
        </div>
      </header>

      {(progressInterrupted || historyInterrupted) && (
        <p className="mt-3 text-sm text-amber-800" role="status">
          Connection interrupted — retrying
        </p>
      )}

      <div className="mt-4">
        {progress ? (
          <AnalysisProgressTimeline
            progress={progress}
            acting={acting}
            onPerformAction={performWorkflowAction}
          />
        ) : (
          <p className="text-sm text-slate-600">
            No active workflow is retained in this browser. Report history remains available
            below.
          </p>
        )}
      </div>

      {notice && <p className="mt-3 text-sm text-emerald-700" role="status">{notice}</p>}
      {error && <p className="mt-3 text-sm text-red-700" role="alert">{error}</p>}
      {historyError && (
        <p className="mt-3 text-sm text-red-700" role="alert">
          {historyError}
        </p>
      )}

      <section aria-labelledby={`report-history-${websiteId}`} className="mt-6">
        <h3 className="font-bold" id={`report-history-${websiteId}`}>
          Report history
        </h3>
        {loading ? (
          <p className="mt-2 text-sm text-slate-600" role="status">
            Loading immutable report history…
          </p>
        ) : reports.items.length === 0 ? (
          <p className="mt-2 text-sm text-slate-600">
            No report has been generated. This does not mean that no issues exist.
          </p>
        ) : (
          <ul className="mt-3 grid gap-2">
            {reports.items.map((report) => (
              <li className="rounded-lg border border-slate-200 p-3 text-sm" key={report.report_id}>
                <button
                  className="w-full text-left focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-600"
                  onClick={() => setSelected(report)}
                  type="button"
                >
                  <span className="font-semibold capitalize">{statusLabel(report.status)}</span>
                  {" · "}
                  {new Date(report.created_at).toLocaleString()}
                  {" · "}
                  report sections {report.evidence_coverage_numerator}/
                  {report.evidence_coverage_denominator}
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="mt-3 flex gap-2">
          <button
            className="rounded border px-3 py-1 text-sm disabled:opacity-50"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            type="button"
          >
            Previous
          </button>
          <button
            className="rounded border px-3 py-1 text-sm disabled:opacity-50"
            disabled={offset + PAGE_SIZE >= reports.total}
            onClick={() => setOffset(offset + PAGE_SIZE)}
            type="button"
          >
            Next
          </button>
        </div>
      </section>

      {selected && <ReportViewer report={selected} />}
    </section>
  );
}
