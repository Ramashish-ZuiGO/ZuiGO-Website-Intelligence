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
  webkit: "WebKit engine",
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

function statusLabel(status: string): string {
  return status
    .replaceAll("_", " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function displayStatus(status: string): string {
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
    execution_status_not_recorded: "Execution status was not recorded for this run",
  };
  return labels[status] ?? statusLabel(status);
}

function Coverage({
  numerator,
  denominator,
  percentage,
}: {
  numerator: number;
  denominator: number;
  percentage: number | null;
}) {
  return (
    <p className="text-sm">
      <span className="inline-flex items-center gap-1">
        Evidence completeness
        <ConceptInfoButton
          conceptId="evidence_completeness"
          title="Evidence completeness"
        />
      </span>
      : {numerator}/{denominator} required groups
      {" · "}
      {percentage === null ? "Unavailable" : `${percentage.toFixed(1)}%`}
    </p>
  );
}

function ReportSectionHeading({
  conceptId,
  number,
  title,
}: {
  conceptId: string;
  number: number;
  title: string;
}) {
  return (
    <h4 className="flex items-center gap-1 text-xl font-black">
      {number}. {title}
      <ConceptInfoButton conceptId={conceptId} title={title} />
    </h4>
  );
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
  if (url.length <= maxLen) return <span className="break-all">{url}</span>;
  const display = url.slice(0, maxLen - 1) + "…";
  return (
    <span className="break-all" title={url}>
      {display}
    </span>
  );
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
          Technical evidence references ({finding.evidence_references.length})
        </summary>
        {finding.evidence_references.length > 0 ? (
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
  const findings = useMemo(() => findingsFromReport(report), [report]);
  const sections = useMemo(
    () => new Map(report.sections.map((section) => [section.section_key, section])),
    [report.sections],
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
      report.sections.flatMap((section) => {
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
  const discoveryPending = rawDiscoveryCompleteness === null || rawDiscoveryCompleteness === undefined;
  const discoveryRunning = discoveryStageStatus === "running";
  const discoveryCompleteness = discoveryPending
    ? discoveryRunning ? "running" : "pending"
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
  const reportStatus =
    report.status === "partial" ||
    (report.status === "completed" && report.unavailable_sections.length > 0)
      ? "Completed with limitations"
      : displayStatus(report.status);

  return (
    <article
      aria-labelledby={`delivered-report-${report.report_id}`}
      className="mt-6 min-w-0 max-w-full overflow-hidden rounded-2xl border border-slate-300 bg-white"
    >
      <header className="bg-slate-950 p-6 text-white">
        <p className="text-sm font-black uppercase tracking-[0.2em] text-orange-300">
          ZuiGO Website Intelligence
        </p>
        <h3 className="mt-4 text-3xl font-black" id={`delivered-report-${report.report_id}`}>
          Evidence-grounded website analysis
        </h3>
        <p className="mt-2 text-sm text-slate-200">
          Immutable evidence snapshot · {reportStatus}
        </p>
        <p className="mt-2 break-all text-sm text-slate-200">
          {String(executive.website_analysed ?? "Website not recorded")} ·{" "}
          {formatHumanTimestamp(executive.analysis_date)}
        </p>
        <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-xl bg-white/10 p-4">
            <p className="flex items-center gap-1 text-xs font-bold uppercase">
              Analysed-page coverage
              <ConceptInfoButton
                conceptId="website_coverage"
                title="Analysed-page coverage"
              />
            </p>
            <p className="mt-1 text-2xl font-black">
              {numberValue(pageCoverage.coverage_numerator)}/
              {numberValue(pageCoverage.coverage_denominator)}
            </p>
            <p className="text-sm">
              {pagePercentage === null
                ? "Unavailable"
                : `${pagePercentage.toFixed(1)}% of discovered eligible pages analysed`}
            </p>
            {!discoveryComplete && !discoveryPending && (
              <p className="mt-1 text-sm font-semibold text-amber-200">
                Full-site coverage is not established.
              </p>
            )}
            {discoveryPending && (
              <p className="mt-1 text-sm text-slate-300">
                Full-site coverage will be evaluated after discovery completes.
              </p>
            )}
          </div>
          <div className="rounded-xl bg-white/10 p-4">
            <p className="text-xs font-bold uppercase">Discovery completeness</p>
            <p className="mt-1 text-2xl font-black">
              {discoveryPending
                ? discoveryRunning ? "In Progress" : "Pending"
                : statusLabel(discoveryCompleteness)}
            </p>
            <p className="text-sm">
              {discoveryCompletenessMessage || (
                discoveryComplete
                  ? "The bounded discovery completed."
                  : discoveryPending
                    ? "Website discovery is in progress."
                    : "The retained page set may not represent the full website."
              )}
            </p>
          </div>
          <div className="rounded-xl bg-white/10 p-4">
            <p className="flex items-center gap-1 text-xs font-bold uppercase">
              Browser coverage
              <ConceptInfoButton
                conceptId="browser_coverage"
                title="Browser coverage"
              />
            </p>
            <p className="mt-1 text-2xl font-black">
              {browserTestedNumerator}/{browserAttemptDenominator}
            </p>
            <p className="text-sm">Requested engine-page tests completed</p>
          </div>
          <div className="rounded-xl bg-white/10 p-4">
            <p className="flex items-center gap-1 text-xs font-bold uppercase">
              Evidence completeness
              <ConceptInfoButton
                conceptId="evidence_completeness"
                title="Evidence completeness"
              />
            </p>
            <p className="mt-1 text-2xl font-black">
              {report.evidence_coverage_numerator}/{report.evidence_coverage_denominator}
            </p>
            <p className="text-sm">Required evidence groups available</p>
          </div>
          <div className="rounded-xl bg-white/10 p-4">
            <p className="flex items-center gap-1 text-xs font-bold uppercase">
              Unique findings
              <ConceptInfoButton conceptId="unique_findings" title="Unique findings" />
            </p>
            <p className="mt-1 text-2xl font-black">{findings.length}</p>
            <p className="text-sm">
              {totalOccurrences} occurrences
              <ConceptInfoButton conceptId="occurrences" title="Occurrences" /> across{" "}
              {affectedPageCount} pages
            </p>
          </div>
          <div className="rounded-xl bg-white/10 p-4">
            <p className="text-xs font-bold uppercase">Overall score</p>
            <p className="mt-1 text-2xl font-black">
              {typeof scores.overall_score === "number"
                ? `${scores.overall_score}/100`
                : "Not available"}
            </p>
            <p className="text-sm">
              Report confidence
              <ConceptInfoButton
                conceptId="report_confidence"
                title="Report confidence"
              />{" "}
              {report.confidence_percent === null
                ? "not available"
                : `${report.confidence_percent}%`}
            </p>
          </div>
        </div>
        <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-2 lg:grid-cols-4">
          {[
            ["Discovered URLs", pageCoverage.total_urls_discovered],
            ["Eligible HTML pages", pageCoverage.eligible_pages],
            ["Analysed pages", pageCoverage.successfully_analysed_pages],
            ["Failed HTML pages", pageCoverage.failed_pages],
          ].map(([label, value]) => (
            <div className="rounded-lg bg-white/10 p-3" key={String(label)}>
              <dt className="flex items-center gap-1 font-semibold">
                {String(label)}
                {label === "Eligible HTML pages" && (
                  <ConceptInfoButton
                    conceptId="eligible_html_pages"
                    title="Eligible HTML pages"
                  />
                )}
              </dt>
              <dd>{numberValue(value)}</dd>
            </div>
          ))}
        </dl>
        <div className="mt-3 grid gap-3 lg:grid-cols-2">
          <div className="min-w-0 rounded-lg bg-white/10 p-3">
            <p className="font-semibold">Top problems</p>
            <ul className="mt-1 list-disc pl-5 text-sm">
              {topFindings.slice(0, 5).map((finding) => (
                <li className="break-words" key={finding.finding_id}>
                  {finding.issue_title}
                </li>
              ))}
            </ul>
          </div>
          <div className="min-w-0 rounded-lg bg-white/10 p-3">
            <p className="font-semibold">Top actions</p>
            <ul className="mt-1 list-disc pl-5 text-sm">
              {actions.slice(0, 5).map((action, index) => (
                <li className="break-words" key={`${index}-${String(action.title)}`}>
                  {String(action.title ?? "Recommended action")}
                </li>
              ))}
            </ul>
          </div>
        </div>
        <div className="mt-3 grid gap-2 text-sm sm:grid-cols-2 lg:grid-cols-5">
          {categoryScores.slice(0, 5).map((categoryScore) => (
            <p className="rounded bg-white/10 p-2" key={String(categoryScore.category_id)}>
              {statusLabel(String(categoryScore.category_id))}:{" "}
              {categoryScore.evidence_available === false
                ? "Unavailable"
                : typeof categoryScore.score === "number"
                  ? `${categoryScore.score}/100`
                  : "Not available"}
              {categoryScore.included === false && categoryScore.exclusion_reason ? (
                <span className="ml-1 text-xs opacity-70">
                  ({String(categoryScore.exclusion_reason)})
                </span>
              ) : null}
              {categoryScore.score_limitation ? (
                <span className="ml-1 text-xs text-amber-200" title={String(categoryScore.score_limitation)}>⚠</span>
              ) : null}
            </p>
          ))}
        </div>
      </header>

      <div className="p-5">
        {report.unavailable_sections.length > 0 && (
          <div className="rounded-lg border border-amber-300 bg-amber-50 p-3" role="note">
            <p className="font-semibold">Partial evidence</p>
            <p className="mt-1 text-sm">
              Unavailable sections: {report.unavailable_sections.join(", ")}. These are
              not represented as successful or issue-free.
            </p>
          </div>
        )}

        <div className="mt-5 flex gap-2" role="tablist" aria-label="Report view mode">
          <button
            aria-selected={viewMode === "executive"}
            className={`rounded-lg px-5 py-2.5 text-sm font-bold transition-colors ${viewMode === "executive" ? "bg-orange-600 text-white" : "bg-slate-100 text-slate-700 hover:bg-slate-200"}`}
            onClick={() => setViewMode("executive")}
            role="tab"
            type="button"
          >
            Executive View
          </button>
          <button
            aria-selected={viewMode === "technical"}
            className={`rounded-lg px-5 py-2.5 text-sm font-bold transition-colors ${viewMode === "technical" ? "bg-orange-600 text-white" : "bg-slate-100 text-slate-700 hover:bg-slate-200"}`}
            onClick={() => setViewMode("technical")}
            role="tab"
            type="button"
          >
            Technical View
          </button>
        </div>

        <nav aria-label="Report sections" className="mt-3 rounded-lg bg-slate-50 p-3">
          <h4 className="font-semibold">{viewMode === "executive" ? "Executive" : "Technical"} sections</h4>
          <ol className="mt-2 grid gap-1 text-sm sm:grid-cols-2">
            {(viewMode === "executive"
              ? [
                  ["executive-summary", "Executive Summary"],
                  ["website-coverage", "Coverage and Confidence"],
                  ["scores-summary", "Category Scores"],
                  ["top-findings", "Top Five Findings"],
                  ["action-plan-summary", "Top Five Actions"],
                  ["browser-coverage", "Browser Compatibility"],
                  ["evidence-limitations", "Evidence Limitations"],
                ]
              : [
                  ["all-findings", "All Findings"],
                  ["page-results", "Page Inventory"],
                  ["browser-coverage", "Browser Matrix"],
                  ["technical-details", "Agent Execution"],
                  ["evidence-limitations", "Methodology"],
                ]
            ).map(([anchor, title], index) => (
              <li key={anchor}>
                <a
                  className="underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-600"
                  href={`#${anchor}`}
                >
                  {index + 1}. {title}
                </a>
              </li>
            ))}
          </ol>
        </nav>

        {viewMode === "executive" && (<section className="mt-5 rounded-xl border p-5" id="executive-summary">
          <ReportSectionHeading
            conceptId="report_executive_summary"
            number={1}
            title="Executive Summary"
          />
          <p className="mt-2 break-all">
            <strong>Website analysed:</strong>{" "}
            {String(executive.website_analysed ?? "Unavailable")}
          </p>
          <p>
            <strong>Analysis date:</strong>{" "}
            {String(executive.analysis_date ?? "Unavailable")}
          </p>
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            {[
              ["URLs discovered", pageCoverage.total_urls_discovered],
              ["Eligible pages", pageCoverage.eligible_pages],
              ["Pages analysed", pageCoverage.successfully_analysed_pages],
              ["Pages not analysed", numberValue(pageCoverage.eligible_pages) - numberValue(pageCoverage.successfully_analysed_pages)],
              ["Overall score", executive.overall_health],
              [
                "Score confidence",
                report.confidence_percent === null
                  ? "Unavailable"
                  : `${report.confidence_percent}%`,
              ],
            ].map(([label, value]) => (
              <div className="rounded-lg bg-slate-50 p-3" key={String(label)}>
                <p className="flex items-center gap-1 text-xs font-bold uppercase">
                  {String(label)}
                  {label === "Eligible pages" && (
                    <ConceptInfoButton
                      conceptId="eligible_html_pages"
                      title="Eligible HTML pages"
                    />
                  )}
                  {label === "Score confidence" && (
                    <ConceptInfoButton
                      conceptId="report_confidence"
                      title="Report confidence"
                    />
                  )}
                </p>
                <p className="mt-1 text-xl font-black">{String(value ?? "Unavailable")}</p>
              </div>
            ))}
          </div>
          {limitations.length > 0 && (
            <p className="mt-4 text-sm text-amber-800">
              {limitations.length} evidence limitation{limitations.length > 1 ? "s" : ""} noted —{" "}
              <a className="underline" href="#evidence-limitations">see Evidence Limitations</a>.
            </p>
          )}
        </section>)}

        {viewMode === "executive" && (<section className="mt-5 rounded-xl border p-5" id="website-coverage">
          <ReportSectionHeading
            conceptId="report_website_coverage"
            number={2}
            title="Website Coverage"
          />
          <p className="mt-2 text-lg font-semibold">
            {numberValue(pageCoverage.coverage_numerator)} of{" "}
            {numberValue(pageCoverage.coverage_denominator)} discovered eligible pages
            analysed
            {pagePercentage === null ? "" : ` — ${pagePercentage.toFixed(1)}%`}
          </p>
          {!discoveryComplete && !discoveryPending && (
            <div className="mt-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-amber-950">
              <p className="font-semibold">
                {discoveryCompletenessMessage || "Website discovery was incomplete, so full-site coverage is unknown."}
              </p>
              {pageCoverage.discovery_failure_message ? (
                <p className="mt-1 text-sm">
                  {String(pageCoverage.discovery_failure_message)}
                </p>
              ) : null}
            </div>
          )}
          {discoveryPending && (
            <div className="mt-3 rounded-lg border border-blue-200 bg-blue-50 p-3 text-blue-900">
              <p className="font-semibold">
                {discoveryCompletenessMessage || "Website discovery is in progress."}
              </p>
            </div>
          )}
          {numberValue(pageCoverage.coverage_denominator) >
            numberValue(pageCoverage.coverage_numerator) && (
            <p className="mt-1 text-amber-800">
              {numberValue(pageCoverage.coverage_denominator) -
                numberValue(pageCoverage.coverage_numerator)}{" "}
              eligible pages were not successfully analysed.
            </p>
          )}
          <dl className="mt-4 grid gap-3 sm:grid-cols-3 lg:grid-cols-5">
            {[
              ["Raw URLs discovered", pageCoverage.total_urls_discovered],
              ["Normalized pages", pageCoverage.normalized_pages],
              ["Eligible", pageCoverage.eligible_pages],
              ["Scheduled", pageCoverage.total_pages_scheduled],
              ["Visited", pageCoverage.total_pages_visited],
              ["Successful", pageCoverage.successfully_analysed_pages],
              ["Failed", pageCoverage.failed_pages],
              ["Skipped", pageCoverage.skipped_pages],
              ["Not scheduled", pageCoverage.not_scheduled_pages],
              ["Incomplete", pageCoverage.pages_with_incomplete_evidence],
            ].map(([label, value]) => (
              <div className="rounded-lg bg-slate-50 p-3" key={String(label)}>
                <dt className="text-xs font-bold uppercase">{String(label)}</dt>
                <dd className="mt-1 text-xl font-black">{numberValue(value)}</dd>
              </div>
            ))}
          </dl>
        </section>)}

        {viewMode === "executive" && (<section className="mt-5 rounded-xl border p-5" id="scores-summary">
          <ReportSectionHeading
            conceptId="report_scores"
            number={3}
            title="Overall and Category Scores"
          />
          <p className="mt-2 text-3xl font-black">
            {typeof scores.overall_score === "number"
              ? `${scores.overall_score}/100`
              : "Overall score unavailable"}
          </p>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            {categoryScores.map((categoryScore) => (
              <div
                className="rounded-lg bg-slate-50 p-3"
                key={String(categoryScore.category_id)}
              >
                <p className="font-semibold">
                  {statusLabel(String(categoryScore.category_id))}
                </p>
                <p className="text-2xl font-black">
                  {categoryScore.evidence_available === false
                    ? "N/A"
                    : typeof categoryScore.score === "number"
                      ? `${categoryScore.score}/100`
                      : "Unavailable"}
                </p>
                {categoryScore.included === false && categoryScore.exclusion_reason ? (
                  <p className="mt-1 text-xs text-slate-500">
                    {String(categoryScore.exclusion_reason)}
                  </p>
                ) : null}
              </div>
            ))}
          </div>
        </section>)}

        {viewMode === "executive" && (<section className="mt-5 rounded-xl border p-5" id="top-findings">
          <ReportSectionHeading
            conceptId="report_top_findings"
            number={4}
            title="Top Findings"
          />
          <p className="mt-1 text-sm text-slate-600">
            {findings.length} unique findings
            <ConceptInfoButton conceptId="unique_findings" title="Unique findings" /> ·{" "}
            {totalOccurrences} total occurrences
            <ConceptInfoButton conceptId="occurrences" title="Occurrences" /> ·{" "}
            {affectedPageCount} affected pages
          </p>
          <div className="mt-4 grid gap-3">
            {topFindings.length > 0 ? (
              topFindings.map((finding) => (
                <article
                  className="rounded-lg border-l-4 border-orange-600 bg-slate-50 p-4"
                  key={finding.finding_id}
                >
                  <p className="text-xs font-bold uppercase">
                    {displayStatus(finding.severity)}
                  </p>
                  <h5 className="font-bold">{finding.issue_title}</h5>
                  <p className="mt-1">{finding.plain_language_explanation}</p>
                  <p className="mt-2 text-sm font-semibold">
                    Affected pages: {finding.affected_page_count} · Occurrences:{" "}
                    {finding.occurrence_count}
                    <ConceptInfoButton conceptId="occurrences" title="Occurrences" />
                  </p>
                  <button
                    className="mt-2 inline-block font-semibold underline text-orange-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-600"
                    onClick={() => { setViewMode("technical"); setTimeout(() => document.getElementById(`finding-${finding.finding_id}`)?.scrollIntoView({ behavior: "smooth" }), 100); }}
                    type="button"
                  >
                    View in Technical View
                  </button>
                </article>
              ))
            ) : (
              <p>
                No critical or high findings were retained. Review all findings and
                evidence limitations.
              </p>
            )}
          </div>
        </section>)}

        <section className="mt-5 rounded-xl border p-5" id="browser-coverage">
          <ReportSectionHeading
            conceptId="report_browser_compatibility"
            number={5}
            title="Browser Compatibility"
          />
          <p className="mt-1 text-sm">
            Every scheduled browser-eligible HTML page is included independently of
            page-analysis success. Unavailable engines are not represented as supported.
          </p>
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            {browserCoverage.map((engine) => {
              const tested = numberValue(engine.tested_pages);
              const eligible = numberValue(engine.eligible_pages);
              const isUnavailable = String(engine.availability_status) === "unavailable";
              return (
                <article
                  className={`rounded-lg p-4 ${isUnavailable ? "border border-slate-300 bg-slate-100" : "bg-slate-50"}`}
                  key={String(engine.engine)}
                >
                  <h5 className="font-bold">
                    {ENGINE_LABELS[String(engine.engine)] ??
                      statusLabel(String(engine.engine))}
                  </h5>
                  {isUnavailable ? (
                    <>
                      <p className="mt-1 text-lg font-semibold text-slate-500">
                        Unavailable in this environment
                      </p>
                      <p className="text-sm text-slate-500">
                        This engine could not be launched. Results are not represented as
                        passed or failed.
                      </p>
                    </>
                  ) : (
                    <>
                      <p className="mt-1 text-2xl font-black">
                        {tested} of {eligible}
                      </p>
                      <p>
                        {eligible
                          ? `${((tested / eligible) * 100).toFixed(1)}% tested`
                          : "No eligible pages"}
                      </p>
                    </>
                  )}
                </article>
              );
            })}
          </div>
        </section>

        {viewMode === "technical" && (<section className="mt-5 rounded-xl border p-5" id="page-results">
          <ReportSectionHeading
            conceptId="report_page_inventory"
            number={6}
            title="Page-by-Page Results"
          />
          <div className="mt-3 flex flex-wrap gap-2" aria-label="Page Inventory filters">
            {[
              "",
              "Analysed",
              "Not analysed",
              "Failed",
              "Not scheduled",
              "Browser incomplete",
            ].map((filter) => (
              <button
                className="rounded-lg border px-3 py-2 text-sm font-semibold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-600"
                key={filter || "All"}
                onClick={() => setInventoryFilter(filter)}
                type="button"
              >
                {filter || "All pages"}
              </button>
            ))}
          </div>
          <p aria-live="polite" className="mt-2 text-sm">
            Showing{" "}
            {filteredInventory.length > INVENTORY_PAGE_SIZE
              ? `${safeInventoryPage * INVENTORY_PAGE_SIZE + 1}–${Math.min(
                  (safeInventoryPage + 1) * INVENTORY_PAGE_SIZE,
                  filteredInventory.length,
                )} of `
              : ""}
            {filteredInventory.length} of {pageInventory.length} eligible HTML
            pages. {assetInventory.length} documents or static assets are listed
            separately.
          </p>
          <div className="mt-3 max-w-full overflow-x-auto overscroll-x-contain">
            <table className="w-full border-collapse text-left text-sm table-fixed">
              <thead>
                <tr>
                  {[
                    "URL",
                    "Eligibility",
                    "Scheduled",
                    "Visited",
                    "Analysed",
                    "Browser engines",
                    "Result",
                    "Exclusion/failure reason",
                  ].map((label) => (
                    <th className="border bg-slate-100 p-2" key={label} scope="col">
                      {label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {visibleInventory.map((page) => (
                  <tr key={String(page.url)}>
                    <td className="border p-2">
                      <TruncatedUrl url={String(page.url)} />
                    </td>
                    <td className="border p-2">
                      {displayStatus(String(page.eligibility ?? "unknown"))}
                    </td>
                    <td className="border p-2">
                      {page.scheduled === true ? "Yes" : "No"}
                    </td>
                    <td className="border p-2">
                      {page.visited === true ? "Yes" : "No"}
                    </td>
                    <td className="border p-2">
                      {page.analysed === true ? "Yes" : "No"}
                    </td>
                    <td className="border p-2">
                      {Array.isArray(page.browser_engines_tested) &&
                      page.browser_engines_tested.length
                        ? page.browser_engines_tested
                            .map(String)
                            .map((engine) => ENGINE_LABELS[engine] ?? statusLabel(engine))
                            .join(", ")
                        : "Not tested"}
                    </td>
                    <td className="border p-2">
                      {displayStatus(String(page.result ?? "unknown"))}
                    </td>
                    <td className="border p-2">
                      {String(
                        page.failure_reason ?? page.exclusion_reason ?? "None",
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {filteredInventory.length > INVENTORY_PAGE_SIZE && (
            <div className="mt-3 flex items-center gap-3 text-sm">
              <button
                className="rounded border px-3 py-1 disabled:opacity-40"
                disabled={safeInventoryPage === 0}
                onClick={() => setInventoryPage(Math.max(0, safeInventoryPage - 1))}
                type="button"
              >
                Previous
              </button>
              <span>
                Page {safeInventoryPage + 1} of {inventoryPageCount}
              </span>
              <button
                className="rounded border px-3 py-1 disabled:opacity-40"
                disabled={safeInventoryPage >= inventoryPageCount - 1}
                onClick={() =>
                  setInventoryPage(
                    Math.min(inventoryPageCount - 1, safeInventoryPage + 1),
                  )
                }
                type="button"
              >
                Next
              </button>
            </div>
          )}
          {assetInventory.length > 0 && (
            <details className="mt-4 rounded-lg border p-3">
              <summary className="cursor-pointer font-bold">
                Document and Asset Inventory ({assetInventory.length})
              </summary>
              <div className="mt-3 max-w-full overflow-x-auto overscroll-x-contain">
                <table className="w-full border-collapse text-left text-sm table-fixed">
                  <thead>
                    <tr>
                      {[
                        "URL",
                        "Final URL",
                        "HTTP status",
                        "Response type",
                        "Classification",
                        "Detection",
                        "Reason",
                        "Browser handling",
                      ].map((label) => (
                        <th className="border bg-slate-100 p-2" key={label} scope="col">
                          {label}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {assetInventory.map((item) => (
                      <tr key={String(item.url)}>
                        <td className="border p-2">
                          <TruncatedUrl url={String(item.url)} />
                        </td>
                        <td className="border p-2">
                          <TruncatedUrl url={String(item.final_url ?? "Not collected")} />
                        </td>
                        <td className="border p-2">
                          {typeof item.http_status === "number"
                            ? `HTTP ${item.http_status}`
                            : "Not collected"}
                        </td>
                        <td className="border p-2 break-words">
                          {String(item.response_content_type ?? "Not collected")}
                        </td>
                        <td className="border p-2">
                          {statusLabel(String(item.resource_classification))}
                        </td>
                        <td className="border p-2 break-words">
                          {String(item.content_type_detection)}
                        </td>
                        <td className="border p-2 break-words">
                          {String(item.failure_reason ?? item.exclusion_reason)}
                        </td>
                        <td className="border p-2 break-words">
                          {String(item.browser_navigation)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          )}
        </section>)}

        {viewMode === "executive" && (<section className="mt-5 rounded-xl border p-5" id="action-plan-summary">
          <ReportSectionHeading
            conceptId="report_action_plan"
            number={7}
            title="Action Plan"
          />
          {String(sections.get("priority_action_plan")?.content.generation_status ?? "") ===
            "deterministic_from_findings" && (
            <p className="mt-2 rounded bg-blue-50 px-3 py-2 text-sm text-blue-800">
              Action plan generated from evidence findings. AI-prioritized plan
              unavailable for this analysis.
            </p>
          )}
          <ol className="mt-3 grid gap-3">
            {actions.slice(0, 5).map((action, index) => (
              <li
                className="rounded-lg bg-slate-50 p-4"
                key={`${index}-${String(action.title)}`}
              >
                <strong>
                  {index + 1}. {String(action.title ?? "Recommended action")}
                </strong>
                <p className="mt-1">
                  {String(action.impact ?? "Impact not quantified.")}
                </p>
                <p className="text-sm">
                  Owner: {String(action.responsible_role ?? "Unassigned")} · Effort:{" "}
                  {String(action.effort ?? "Unestimated")}
                </p>
              </li>
            ))}
          </ol>
        </section>)}

        <section className="mt-5 rounded-xl border p-5" id="evidence-limitations">
          <ReportSectionHeading
            conceptId="report_limitations"
            number={8}
            title="Evidence Limitations"
          />
          <p className="mt-2">
            Report section evidence: {report.evidence_coverage_numerator} of{" "}
            {report.evidence_coverage_denominator} report sections have available evidence.
            This is not website page coverage or scoring category coverage.
          </p>
          <ul className="mt-3 list-disc pl-5">
            {limitations.map((limitation) => (
              <li key={limitation}>{limitation}</li>
            ))}
          </ul>
        </section>

        {viewMode === "technical" && (<details
          className="mt-5 rounded-xl border border-slate-300 p-4"
          id="all-findings"
          open
        >
          <summary className="cursor-pointer text-lg font-bold">
            All Findings
          </summary>
          <section aria-labelledby={`finding-explorer-${report.report_id}`}>
          <h4 className="sr-only" id={`finding-explorer-${report.report_id}`}>
            Finding explorer
          </h4>
          <p className="mt-1 text-sm text-slate-600">
            Search and filter every retained finding without capping page occurrences.
          </p>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <label className="text-sm font-semibold">
              Search findings
              <input
                className="mt-1 w-full rounded border border-slate-400 px-3 py-2 font-normal focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-600"
                onChange={(event) => setSearch(event.target.value)}
                type="search"
                value={search}
              />
            </label>
            <label className="text-sm font-semibold">
              Page or URL
              <input
                className="mt-1 w-full rounded border border-slate-400 px-3 py-2 font-normal focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-600"
                onChange={(event) => setPageUrl(event.target.value)}
                type="search"
                value={pageUrl}
              />
            </label>
            <FilterSelect
              label="Severity"
              onChange={setSeverity}
              options={options.severities}
              value={severity}
            />
            <FilterSelect
              label="Category"
              onChange={setCategory}
              options={options.categories}
              value={category}
            />
            <FilterSelect
              label="Agent"
              onChange={setAgent}
              options={options.agents}
              value={agent}
            />
            <FilterSelect
              label="Scope"
              onChange={setScope}
              options={options.scopes}
              value={scope}
            />
            <FilterSelect
              label="Evidence state"
              onChange={setEvidenceState}
              options={["available", "incomplete", "unavailable"]}
              value={evidenceState}
            />
          </div>
          <p aria-live="polite" className="mt-3 text-sm font-semibold">
            Showing{" "}
            {filteredFindings.length
              ? safeFindingsPage * FINDINGS_PAGE_SIZE + 1
              : 0}
            –
            {Math.min(
              filteredFindings.length,
              (safeFindingsPage + 1) * FINDINGS_PAGE_SIZE,
            )}{" "}
            of {filteredFindings.length} filtered findings ({findings.length} total).
          </p>
          <div className="mt-4 grid gap-4">
            {filteredFindings.length > 0 ? (
              visibleFindings.map((finding) => (
                <FindingDetail finding={finding} key={finding.finding_id} />
              ))
            ) : (
              <p className="text-sm text-slate-600">
                No retained findings match these filters. This filtered state does not
                prove that the site has no issues.
              </p>
            )}
          </div>
          {filteredFindings.length > FINDINGS_PAGE_SIZE && (
            <nav
              aria-label="Finding pages"
              className="mt-4 flex flex-wrap items-center justify-between gap-3"
            >
              <button
                className="rounded border px-3 py-2 font-semibold disabled:opacity-50"
                disabled={safeFindingsPage === 0}
                onClick={() => setFindingsPage(Math.max(0, safeFindingsPage - 1))}
                type="button"
              >
                Previous findings
              </button>
              <span>
                Page {safeFindingsPage + 1} of {findingPageCount}
              </span>
              <button
                className="rounded border px-3 py-2 font-semibold disabled:opacity-50"
                disabled={safeFindingsPage >= findingPageCount - 1}
                onClick={() =>
                  setFindingsPage(
                    Math.min(findingPageCount - 1, safeFindingsPage + 1),
                  )
                }
                type="button"
              >
                Next findings
              </button>
            </nav>
          )}
          </section>
        </details>)}

        <section aria-labelledby={`exports-${report.report_id}`} className="mt-5">
          <h4 className="font-semibold" id={`exports-${report.report_id}`}>
            Export report
          </h4>
          <div className="mt-2 flex flex-wrap gap-2">
            {report.artifacts.map((artifact) => (
              <a
                className="rounded-lg border border-slate-400 px-3 py-2 text-sm font-semibold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-600"
                href={reportDeliveryApi.downloadUrl(report.report_id, artifact.format)}
                key={artifact.artifact_id}
              >
                Download {artifact.format.toUpperCase()}{" "}
                <span className="sr-only">
                  ({artifact.size_bytes} bytes, checksum {artifact.checksum_sha256})
                </span>
              </a>
            ))}
            {[
              ["presentation_pdf", "Presentation PDF"],
              ["technical_appendix", "Technical Appendix"],
              ["page_inventory", "Page Inventory JSON"],
            ].map(([format, label]) => (
              <a
                className="rounded-lg border border-slate-400 px-3 py-2 text-sm font-semibold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-600"
                href={reportDeliveryApi.downloadUrl(report.report_id, format)}
                key={format}
              >
                Download {label}
              </a>
            ))}
          </div>
        </section>

        {viewMode === "technical" && (<details className="mt-5 rounded-xl border p-5" id="technical-details" open>
          <summary className="flex cursor-pointer items-center gap-1 text-xl font-black">
            Technical Details
            <ConceptInfoButton
              conceptId="report_technical_details"
              title="Technical Details"
            />
          </summary>
          <p className="mt-2">
            Detailed evidence is separated from the business summary. Internal
            execution identifiers, provider identifiers, rule identifiers, and raw
            payloads are intentionally not displayed.
          </p>
          <section
            aria-labelledby={`report-agents-${report.report_id}`}
            className="mt-4 rounded-lg bg-slate-50 p-4"
          >
            <h5 className="font-bold" id={`report-agents-${report.report_id}`}>
              Agents and evidence production
            </h5>
            <ul className="mt-2 grid gap-2 sm:grid-cols-2">
              {reportAgents.map((agent) => (
                <li className="rounded border bg-white p-3" key={String(agent.agent_id)}>
                  <strong>{friendlyAgentName(agent.agent_id)}</strong>
                  <br />
                  Status:{" "}
                  {displayStatus(
                    String(agent.status ?? "execution status not recorded"),
                  )}
                  {typeof agent.status_explanation === "string" && (
                    <span className="mt-1 block text-sm">
                      {agent.status_explanation}
                    </span>
                  )}
                  <span className="mt-1 block text-sm">
                    Evidence references:{" "}
                    {Array.isArray(agent.evidence_produced)
                      ? agent.evidence_produced.length
                      : 0}
                  </span>
                </li>
              ))}
            </ul>
            <p className="mt-3 text-sm">
              <strong>Unavailable tools/providers:</strong>{" "}
              {unavailableCapabilities.length
                ? unavailableCapabilities.map(statusLabel).join(", ")
                : "None recorded"}
            </p>
          </section>
          <ul className="mt-3 grid gap-2 sm:grid-cols-2">
            {report.sections.map((section) => (
              <li className="rounded-lg bg-slate-50 p-3" key={section.section_id}>
                <strong>{section.title}</strong> — {displayStatus(section.status)}
                <br />
                <span className="text-sm">
                  {section.evidence_references.length} retained evidence references
                </span>
                {section.unavailable_reason && (
                  <p className="mt-1 text-sm text-amber-800">
                    {section.unavailable_reason}
                  </p>
                )}
                {isRecord(section.content.agent_attribution) &&
                  recordList(
                    section.content.agent_attribution.agents_involved,
                  ).length > 0 && (
                    <details className="mt-2 rounded border bg-white p-2">
                      <summary className="cursor-pointer font-semibold">
                        Section agent attribution
                      </summary>
                      <ul className="mt-2 list-disc pl-5 text-sm">
                        {recordList(
                          section.content.agent_attribution.agents_involved,
                        ).map((agent) => (
                          <li key={`${section.section_id}-${String(agent.agent_id)}`}>
                            {friendlyAgentName(agent.agent_id)}:{" "}
                            {displayStatus(
                              String(
                                agent.execution_status ??
                                  "execution status not recorded",
                              ),
                            )}
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
              </li>
            ))}
          </ul>
        </details>)}
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
  const [lastSuccessfulPollAt, setLastSuccessfulPollAt] = useState<string | null>(
    null,
  );
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
      setLastSuccessfulPollAt(new Date().toISOString());
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
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Unable to start the full analysis.",
      );
    } finally {
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

  const progressDescription = useMemo(() => {
    if (!progress) return "Workflow progress is unavailable.";
    if (
      progress.progress_percentage === 100 &&
      progress.report_generation_available
    ) {
      return progress.status === "partial"
        ? "Analysis completed with limitations. The final report is available."
        : "Analysis completed. The final report is available.";
    }
    const stage = progress.stages.find(
      (item) => item.stage_id === progress.current_stage,
    );
    return `${progress.progress_percentage.toFixed(0)} percent complete. Current stage ${stage?.label ?? statusLabel(progress.current_stage)}.`;
  }, [progress]);
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

      <div aria-live="polite" className="mt-4" role="status">
        {progress ? (
          <>
            {progress.submitted_website && (
              <p className="mb-3 break-all text-sm">
                <strong>Submitted website:</strong> {progress.submitted_website}
              </p>
            )}
            <div
              aria-label={progressDescription}
              aria-valuemax={100}
              aria-valuemin={0}
              aria-valuenow={progress.progress_percentage}
              className="h-3 overflow-hidden rounded-full bg-slate-200"
              role="progressbar"
            >
              <div
                className="h-full bg-blue-700 transition-[width]"
                style={{ width: `${progress.progress_percentage}%` }}
              />
            </div>
            <p className="mt-2 text-sm font-semibold">
              {progress.status === "partial" && progress.report_generation_available
                ? "Completed with limitations"
                : displayStatus(progress.status)}{" "}
              · {progressDescription}
            </p>
            {progress.page_coverage.discovery_completeness !== "complete" && (
              <div className="mt-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950">
                <p className="font-semibold">
                  Website discovery was{" "}
                  {progress.page_coverage.discovery_completeness}. Full-site coverage
                  is not established.
                </p>
                <p className="mt-1">
                  {progress.page_coverage.discovery_failure_message ??
                    "The retained discovered pages remain usable, but they may not represent the full website."}
                </p>
              </div>
            )}
            <p className="mt-1 text-sm">
              Last progress update:{" "}
              {new Date(progress.last_progress_update).toLocaleString()}.
            </p>
            {lastSuccessfulPollAt && (
              <p className="mt-1 text-sm">
                Latest successful status check:{" "}
                {new Date(lastSuccessfulPollAt).toLocaleString()}.
              </p>
            )}
            {progress.business_error_message && (
              <p
                className="mt-3 rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-900"
                role="alert"
              >
                <strong>
                  {progress.failed_stage_id
                    ? `Failed stage: ${
                        progress.stages.find(
                          (item) => item.stage_id === progress.failed_stage_id,
                        )?.label ?? statusLabel(progress.failed_stage_id)
                      }. `
                    : ""}
                </strong>
                {progress.business_error_message}
              </p>
            )}
            <section
              aria-labelledby={`stage-progress-${websiteId}`}
              className="mt-4"
            >
              <h3 className="font-bold" id={`stage-progress-${websiteId}`}>
                Analysis stages
              </h3>
              <ol className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                {progress.stages.map((stage) => (
                  <li className="rounded-lg border p-3 text-sm" key={stage.stage_id}>
                    <strong>{stage.label}</strong>
                    <br />
                    {displayStatus(stage.status)}
                  </li>
                ))}
              </ol>
            </section>
            <dl className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {[
                [
                  "Discovery completeness",
                  displayStatus(progress.page_coverage.discovery_completeness),
                ],
                ["Discovered", progress.page_coverage.discovered_pages],
                ["Normalized", progress.page_coverage.normalized_pages],
                ["Eligible", progress.page_coverage.eligible_pages],
                ["Scheduled", progress.page_coverage.scheduled_pages],
                [
                  "Not scheduled",
                  `${progress.page_coverage.not_scheduled_pages} (non-HTML assets or scope exclusions)`,
                ],
                ["Visited", progress.page_coverage.visited_pages],
                ["Successfully analysed", progress.page_coverage.successfully_analysed_pages],
                ["Failed", progress.page_coverage.failed_pages],
                ["Document assets", progress.page_coverage.document_assets],
                ["Media/static assets", progress.page_coverage.media_static_assets],
                ["Skipped", progress.page_coverage.skipped_pages],
                ["Incomplete", progress.page_coverage.incomplete_pages],
                [
                  "Analysed-page coverage",
                  progress.page_coverage.coverage_percentage === null
                    ? "Unavailable"
                    : `${progress.page_coverage.coverage_numerator}/${progress.page_coverage.coverage_denominator} discovered eligible pages (${progress.page_coverage.coverage_percentage}%)`,
                ],
                [
                  "Full-site coverage",
                  progress.page_coverage.full_site_coverage_percentage === null
                    ? "Not established"
                    : `${progress.page_coverage.full_site_coverage_percentage}%`,
                ],
              ].map(([label, value]) => (
                <div className="rounded-lg border border-slate-200 bg-slate-50 p-3" key={label}>
                  <dt className="text-xs font-bold uppercase text-slate-500">{label}</dt>
                  <dd className="mt-1 text-lg font-black">{value}</dd>
                </div>
              ))}
            </dl>
            {selected ? (
              <a
                className="mt-3 inline-flex text-sm font-semibold underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-600"
                href={reportDeliveryApi.downloadUrl(
                  selected.report_id,
                  "page_inventory",
                )}
              >
                Download Page Inventory
              </a>
            ) : (
              <p className="mt-3 text-sm text-slate-600">
                Page Inventory becomes available with the immutable report.
              </p>
            )}
            {progress.page_coverage.failed_page_details.length > 0 && (
              <details className="mt-3 rounded-lg border border-red-200 bg-red-50 p-3">
                <summary className="cursor-pointer font-semibold text-red-900">
                  Failed page URLs and reasons (
                  {progress.page_coverage.failed_page_details.length})
                </summary>
                <ul className="mt-3 grid gap-2 text-sm">
                  {progress.page_coverage.failed_page_details.map((item) => (
                    <li
                      className="rounded bg-white p-3"
                      key={`${item.url}-${item.reason_code}`}
                    >
                      <p className="break-all font-semibold">{item.url}</p>
                      <p className="mt-1 text-red-900">{item.reason}</p>
                    </li>
                  ))}
                </ul>
              </details>
            )}
            {progress.page_coverage.resource_inventory.length > 0 && (
              <details className="mt-3 rounded-lg border border-slate-300 bg-slate-50 p-3">
                <summary className="cursor-pointer font-semibold">
                  Documents and static assets (
                  {progress.page_coverage.resource_inventory.length})
                </summary>
                <ul className="mt-3 grid gap-2 text-sm">
                  {progress.page_coverage.resource_inventory.map((item) => (
                    <li className="min-w-0 rounded bg-white p-3" key={item.url}>
                      <p className="break-all font-semibold">{item.url}</p>
                      <p className="mt-1 break-all">
                        Final URL: {item.final_url ?? "Not collected"}
                      </p>
                      <p>
                        {item.http_status === null
                          ? "HTTP status not collected"
                          : `HTTP ${item.http_status}`}{" "}
                        · {item.response_content_type ?? "Response type not collected"} ·{" "}
                        {statusLabel(item.classification)}
                      </p>
                      <p className="mt-1">{item.failure_reason ?? "No failure reason"}</p>
                      <p className="mt-1 text-slate-600">
                        {item.content_type_detection} {item.browser_navigation}
                      </p>
                    </li>
                  ))}
                </ul>
              </details>
            )}
            <section className="mt-4" aria-labelledby={`browser-progress-${websiteId}`}>
              <h3 className="font-bold" id={`browser-progress-${websiteId}`}>
                Browser-engine progress
                <ConceptInfoButton
                  conceptId="browser_coverage"
                  title="Browser coverage"
                />
              </h3>
              <p className="mt-1 text-sm capitalize">
                {displayStatus(progress.browser_engine_progress.status)}
              </p>
              <ul className="mt-2 grid gap-2 sm:grid-cols-3">
                {progress.browser_engine_progress.engines.map((engine) => {
                  const engineUnavailable =
                    String(engine.availability_status) === "unavailable";
                  return (
                    <li
                      className={`rounded-lg border p-3 text-sm ${engineUnavailable ? "border-slate-300 bg-slate-100 text-slate-500" : ""}`}
                      key={engine.engine}
                    >
                      <strong>
                        {ENGINE_LABELS[engine.engine] ?? statusLabel(engine.engine)}
                      </strong>
                      {engineUnavailable ? (
                        <p className="mt-1">
                          Unavailable in this environment
                        </p>
                      ) : (
                        <>
                          <br />
                          Browser coverage {engine.tested_pages} of{" "}
                          {engine.eligible_pages}
                          <br />
                          Queued {engine.queued_pages} · attempted{" "}
                          {engine.attempted_pages}
                          <br />
                          Passed {engine.passed_pages} · partial{" "}
                          {engine.partial_pages}
                          <ConceptInfoButton
                            conceptId="partial_browser_result"
                            title="Partial browser result"
                          />{" "}
                          · failed {engine.failed_pages}
                          <br />
                          Inconclusive {engine.inconclusive_pages} ·
                          unavailable {engine.unavailable_pages}
                          {Boolean(engine.timed_out_pages) && (
                            <>
                              <br />
                              Timed out {engine.timed_out_pages}
                            </>
                          )}
                        </>
                      )}
                    </li>
                  );
                })}
              </ul>
            </section>
            <section className="mt-4" aria-labelledby={`agent-progress-${websiteId}`}>
              <h3 className="font-bold" id={`agent-progress-${websiteId}`}>
                Eight-agent execution
              </h3>
              <ul className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                {progress.agent_states.map((agent) => (
                  <li className="rounded-lg border p-3 text-sm" key={agent.agent_id}>
                    <strong>{AGENT_LABELS[agent.agent_id] ?? statusLabel(agent.agent_id)}</strong>
                    <br />
                    <span>{displayStatus(agent.status)}</span>
                  </li>
                ))}
              </ul>
            </section>
            <Coverage
              denominator={progress.evidence_coverage.denominator}
              numerator={progress.evidence_coverage.numerator}
              percentage={progress.evidence_coverage.percentage}
            />
            <p className="text-sm">
              Attempt {progress.attempt} · elapsed {progress.elapsed_seconds.toFixed(1)}s
            </p>
            {(progress.unavailable_tools.length > 0 ||
              progress.unavailable_providers.length > 0) && (
              <p className="mt-1 text-sm text-amber-800">
                Some advanced data sources were unavailable. Core page analysis may
                still be complete.
              </p>
            )}
            {progress.safe_error_summaries.map((item) => (
              <p className="mt-1 text-sm text-red-700" key={`${item.code}-${item.message}`}>
                {item.message}
              </p>
            ))}
            <div className="mt-4 flex flex-wrap gap-2">
              {!TERMINAL_STATUSES.includes(progress.status) && (
                <button
                  className="rounded border border-red-700 px-3 py-2 text-sm font-bold text-red-800 disabled:opacity-50"
                  disabled={acting}
                  onClick={() => void performWorkflowAction("cancel")}
                  type="button"
                >
                  Cancel analysis
                </button>
              )}
              {progress.retry_available && (
                <button
                  className="rounded border border-slate-700 px-3 py-2 text-sm font-bold disabled:opacity-50"
                  disabled={acting || !progress.resume_available}
                  onClick={() => void performWorkflowAction("resume")}
                  type="button"
                >
                  {progress.page_coverage.discovery_retry_available
                    ? "Retry incomplete discovery"
                    : "Retry or resume analysis"}
                </button>
              )}
            </div>
          </>
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
