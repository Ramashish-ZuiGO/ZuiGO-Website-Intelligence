"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { SafeStructuredValue } from "@/components/agents/SafeStructuredValue";
import type {
  DeliveredReport,
  DetailedReportFinding,
  PaginatedReports,
  SectionAgentAttribution,
  WorkflowProgress,
} from "@/components/reports/types";
import { reportDeliveryApi } from "@/lib/report-delivery-api";

const PAGE_SIZE = 5;
const TERMINAL_STATUSES = [
  "completed",
  "partial",
  "failed",
  "cancelled",
  "unavailable",
];

interface ReportDeliveryPanelProps {
  projectId?: string;
  websiteId: string;
  analysisRunId?: string;
  workflowExecutionId?: string;
  compact?: boolean;
  showStartAction?: boolean;
}

function executionKey(projectId: string, websiteId: string): string {
  return `analysis-journey:${projectId}:${websiteId}`;
}

function createKey(prefix: string): string {
  return `${prefix}-${new Date().toISOString()}-${crypto.randomUUID()}`;
}

function statusLabel(status: string): string {
  return status.replaceAll("_", " ");
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
      Evidence coverage: {numerator}/{denominator}
      {" · "}
      {percentage === null ? "Unavailable" : `${percentage.toFixed(1)}%`}
    </p>
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
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
  for (const section of report.sections) {
    const values = section.content.findings;
    if (!Array.isArray(values)) continue;
    for (const value of values) {
      if (isFinding(value)) findings.set(value.finding_id, value);
    }
  }
  return [...findings.values()];
}

function sectionAttribution(
  content: Record<string, unknown>,
): SectionAgentAttribution | null {
  const value = content.agent_attribution;
  if (
    !isRecord(value) ||
    !Array.isArray(value.agents_involved) ||
    typeof value.fallback_behavior !== "string"
  ) {
    return null;
  }
  return value as unknown as SectionAgentAttribution;
}

function collectFindingIds(value: unknown, ids = new Set<string>()): Set<string> {
  if (Array.isArray(value)) {
    value.forEach((item) => collectFindingIds(item, ids));
  } else if (isRecord(value)) {
    Object.entries(value).forEach(([key, item]) => {
      if (key === "finding_id" && typeof item === "string") ids.add(item);
      else if (key === "related_finding_ids" && Array.isArray(item)) {
        item.forEach((findingId) => {
          if (typeof findingId === "string") ids.add(findingId);
        });
      } else collectFindingIds(item, ids);
    });
  }
  return ids;
}

function AgentAttribution({ value }: { value: SectionAgentAttribution }) {
  return (
    <aside
      aria-label="Section agent attribution"
      className="mt-4 rounded-lg border border-blue-200 bg-blue-50 p-3"
    >
      <h5 className="font-semibold text-blue-950">Agents and evidence production</h5>
      <ul className="mt-2 grid gap-2 text-sm sm:grid-cols-2">
        {value.agents_involved.map((agent) => (
          <li className="rounded border border-blue-100 bg-white p-2" key={agent.agent_id}>
            <strong>{agent.agent_id}</strong> · {statusLabel(agent.execution_status)}
            <br />
            Tools: {agent.tools_used.join(", ") || "None retained"} · evidence{" "}
            {agent.evidence_reference_count}
          </li>
        ))}
      </ul>
      {(value.unavailable_tools.length > 0 ||
        value.unavailable_providers.length > 0) && (
        <p className="mt-2 text-sm text-amber-900">
          Unavailable tools/providers:{" "}
          {[...value.unavailable_tools, ...value.unavailable_providers].join(", ")}
        </p>
      )}
      <p className="mt-2 text-sm">
        <strong>Fallback:</strong> {value.fallback_behavior}
      </p>
    </aside>
  );
}

function FindingDetail({ finding }: { finding: DetailedReportFinding }) {
  const fields = [
    ["Technical explanation", finding.technical_explanation],
    [
      "Confidence",
      `${finding.confidence.classification}${
        finding.confidence.percent === null ? "" : ` (${finding.confidence.percent}%)`
      }`,
    ],
    ["Detecting agent", finding.detecting_agent],
    ["Validating agent", finding.validating_agent],
    ["Likely cause", finding.likely_cause],
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
      className="scroll-mt-6 rounded-xl border-l-4 border-orange-600 bg-slate-50 p-4"
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
      <dl className="mt-4 grid gap-x-4 gap-y-2 text-sm sm:grid-cols-[12rem_1fr]">
        {fields.map(([label, value]) => (
          <div className="contents" key={label}>
            <dt className="font-semibold">{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[70rem] border-collapse text-left text-xs">
          <caption className="mb-2 text-left font-semibold">
            Exact affected locations ({finding.exact_occurrences.length})
          </caption>
          <thead>
            <tr>
              {[
                "Page",
                "Status",
                "Page type/section",
                "Selector/resource/location",
                "Observed",
                "Expected",
                "Timestamp",
                "Provider/version",
                "Artifact",
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
                <td className="border p-2 break-all">{occurrence.normalized_url}</td>
                <td className="border p-2">{occurrence.status_code ?? "Unavailable"}</td>
                <td className="border p-2">
                  {occurrence.page_type} / {occurrence.section}
                </td>
                <td className="border p-2">
                  {occurrence.selector ??
                    occurrence.resource_url ??
                    occurrence.location ??
                    "Unavailable"}
                </td>
                <td className="border p-2">{occurrence.observed_value ?? "Unavailable"}</td>
                <td className="border p-2">{occurrence.expected_value ?? "Unavailable"}</td>
                <td className="border p-2">{occurrence.evidence_timestamp}</td>
                <td className="border p-2">
                  {occurrence.analysis_provider} /{" "}
                  {occurrence.analysis_provider_version ?? "Unavailable"}
                </td>
                <td className="border p-2">
                  {occurrence.artifact_reference == null
                    ? "Unavailable"
                    : String(occurrence.artifact_reference)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <details className="mt-3">
        <summary className="cursor-pointer font-semibold">
          Evidence references ({finding.evidence_references.length})
        </summary>
        <SafeStructuredValue value={finding.evidence_references} />
      </details>
      {finding.related_finding_ids.length > 0 && (
        <p className="mt-3 text-sm">
          Related findings:{" "}
          {finding.related_finding_ids.map((findingId, index) => (
            <span key={findingId}>
              {index > 0 && ", "}
              <a
                className="underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-600"
                href={`#finding-${findingId}`}
              >
                {findingId}
              </a>
            </span>
          ))}
        </p>
      )}
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
  const [search, setSearch] = useState("");
  const [severity, setSeverity] = useState("");
  const [category, setCategory] = useState("");
  const [agent, setAgent] = useState("");
  const [pageUrl, setPageUrl] = useState("");
  const [scope, setScope] = useState("");
  const [evidenceState, setEvidenceState] = useState("");
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

  return (
    <article
      aria-labelledby={`delivered-report-${report.report_id}`}
      className="mt-6 overflow-hidden rounded-2xl border border-slate-300 bg-white"
    >
      <header className="bg-slate-950 p-6 text-white">
        <p className="text-sm font-black uppercase tracking-[0.2em] text-orange-300">
          ZuiGO Website Intelligence
        </p>
        <h3 className="mt-4 text-3xl font-black" id={`delivered-report-${report.report_id}`}>
          Evidence-grounded website analysis
        </h3>
        <p className="mt-2 text-sm text-slate-200">
          Immutable snapshot · {statusLabel(report.status)} · report version{" "}
          {report.report_version}
        </p>
        <p className="mt-1 break-all font-mono text-xs text-slate-300">
          Report ID: {report.report_id}
        </p>
        <div className="mt-5 grid gap-3 sm:grid-cols-3">
          <div className="rounded-xl bg-white/10 p-4">
            <p className="text-xs font-bold uppercase">Evidence coverage</p>
            <p className="mt-1 text-2xl font-black">
              {report.evidence_coverage_numerator}/{report.evidence_coverage_denominator}
            </p>
            <p className="text-sm">
              {report.evidence_coverage_percentage === null
                ? "Unavailable"
                : `${report.evidence_coverage_percentage.toFixed(1)}%`}
            </p>
          </div>
          <div className="rounded-xl bg-white/10 p-4">
            <p className="text-xs font-bold uppercase">Score confidence</p>
            <p className="mt-1 text-2xl font-black">
              {report.confidence_percent === null
                ? "Unavailable"
                : `${report.confidence_percent}%`}
            </p>
          </div>
          <div className="rounded-xl bg-white/10 p-4">
            <p className="text-xs font-bold uppercase">Detailed findings</p>
            <p className="mt-1 text-2xl font-black">{findings.length}</p>
            <p className="text-sm">All retained occurrences</p>
          </div>
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

        <nav aria-label="Final report sections" className="mt-5 rounded-lg bg-slate-50 p-3">
          <h4 className="font-semibold">Report sections</h4>
          <ol className="mt-2 grid gap-1 text-sm sm:grid-cols-2">
            {report.sections.map((section) => (
              <li key={section.section_id}>
                <a
                  className="underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-600"
                  href={`#report-${report.report_id}-${section.section_key}`}
                >
                  {section.position}. {section.title}
                </a>
              </li>
            ))}
          </ol>
        </nav>

        <section
          aria-labelledby={`finding-explorer-${report.report_id}`}
          className="mt-5 rounded-xl border border-slate-300 p-4"
        >
          <h4 className="text-lg font-bold" id={`finding-explorer-${report.report_id}`}>
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
            Showing {filteredFindings.length} of {findings.length} findings.
          </p>
          <div className="mt-4 grid gap-4">
            {filteredFindings.length > 0 ? (
              filteredFindings.map((finding) => (
                <FindingDetail finding={finding} key={finding.finding_id} />
              ))
            ) : (
              <p className="text-sm text-slate-600">
                No retained findings match these filters. This filtered state does not
                prove that the site has no issues.
              </p>
            )}
          </div>
        </section>

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
          </div>
        </section>

        <div className="mt-5 grid gap-4">
          {report.sections.map((section) => {
            const attribution = sectionAttribution(section.content);
            const findingIds = [...collectFindingIds(section.content)];
            return (
              <section
                aria-labelledby={`report-${report.report_id}-${section.section_key}-heading`}
                className="scroll-mt-6 rounded-xl border border-slate-200 p-4"
                id={`report-${report.report_id}-${section.section_key}`}
                key={section.section_id}
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <h4
                    className="font-bold"
                    id={`report-${report.report_id}-${section.section_key}-heading`}
                  >
                    {section.position}. {section.title}
                  </h4>
                  <span className="rounded-full border px-2 py-1 text-xs font-bold uppercase">
                    {statusLabel(section.status)}
                  </span>
                </div>
                {section.unavailable_reason && (
                  <p className="mt-2 text-sm text-amber-800" role="note">
                    {section.unavailable_reason}
                  </p>
                )}
                <div className="mt-3">
                  <SafeStructuredValue value={section.content} />
                </div>
                {findingIds.length > 0 && (
                  <p className="mt-3 text-sm">
                    <strong>Linked findings:</strong>{" "}
                    {findingIds.map((findingId, index) => (
                      <span key={findingId}>
                        {index > 0 && ", "}
                        <a
                          className="underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-600"
                          href={`#finding-${findingId}`}
                        >
                          {findingId}
                        </a>
                      </span>
                    ))}
                  </p>
                )}
                {attribution && <AgentAttribution value={attribution} />}
                <details className="mt-3">
                  <summary className="cursor-pointer text-sm font-semibold">
                    Evidence references ({section.evidence_references.length})
                  </summary>
                  {section.evidence_references.length > 0 ? (
                    <div className="mt-2">
                      <SafeStructuredValue value={section.evidence_references} />
                    </div>
                  ) : (
                    <p className="mt-2 text-sm text-slate-500">
                      No evidence reference was available for this section.
                    </p>
                  )}
                </details>
              </section>
            );
          })}
        </div>
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
  const [notice, setNotice] = useState<string | null>(null);

  const resolvedAnalysisId = analysisRunId ?? analysisId;
  const resolvedExecutionId = workflowExecutionId ?? executionId;

  const loadReports = useCallback(async () => {
    setLoading(true);
    try {
      const result = resolvedAnalysisId
        ? await reportDeliveryApi.forRun(resolvedAnalysisId, PAGE_SIZE, offset)
        : await reportDeliveryApi.history(websiteId, PAGE_SIZE, offset);
      setReports(result);
      setSelected((current) => current ?? result.items[0] ?? null);
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Unable to load report history.",
      );
    } finally {
      setLoading(false);
    }
  }, [offset, resolvedAnalysisId, websiteId]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadReports(), 0);
    return () => window.clearTimeout(timer);
  }, [loadReports]);

  const loadProgress = useCallback(async () => {
    if (!resolvedExecutionId) return;
    try {
      const current = await reportDeliveryApi.progress(resolvedExecutionId);
      setProgress(current);
      if (current.analysis_run_id) setAnalysisId(current.analysis_run_id);
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Unable to load workflow progress.",
      );
    }
  }, [resolvedExecutionId]);

  useEffect(() => {
    if (!resolvedExecutionId) return;
    const initialTimer = window.setTimeout(() => void loadProgress(), 0);
    const timer = window.setInterval(() => void loadProgress(), 2000);
    return () => {
      window.clearTimeout(initialTimer);
      window.clearInterval(timer);
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

  const progressDescription = useMemo(() => {
    if (!progress) return "Workflow progress is unavailable.";
    return `${progress.progress_percentage.toFixed(0)} percent complete. Current stage ${statusLabel(progress.current_stage)}.`;
  }, [progress]);
  const canGenerate =
    Boolean(resolvedAnalysisId) &&
    (!progress || TERMINAL_STATUSES.includes(progress.status));

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

      <div aria-live="polite" className="mt-4" role="status">
        {progress ? (
          <>
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
              {statusLabel(progress.status)} · {progressDescription}
            </p>
            <p className="mt-1 text-sm">
              Completed agents: {progress.completed_agent_ids.join(", ") || "None yet"}.
              Partial: {progress.partial_agent_ids.join(", ") || "None"}.
              Pending: {progress.pending_agent_ids.join(", ") || "None"}.
            </p>
            <Coverage
              denominator={progress.evidence_coverage.denominator}
              numerator={progress.evidence_coverage.numerator}
              percentage={progress.evidence_coverage.percentage}
            />
            <p className="text-sm">
              Attempt {progress.attempt} · elapsed {progress.elapsed_seconds.toFixed(1)}s ·
              resume {progress.resume_available ? "available" : "unavailable"} · retry{" "}
              {progress.retry_available ? "available" : "unavailable"}
            </p>
            {(progress.unavailable_tools.length > 0 ||
              progress.unavailable_providers.length > 0) && (
              <p className="mt-1 text-sm text-amber-800">
                Unavailable tools/providers:{" "}
                {[...progress.unavailable_tools, ...progress.unavailable_providers].join(", ")}
              </p>
            )}
            {progress.safe_error_summaries.map((item) => (
              <p className="mt-1 text-sm text-red-700" key={`${item.code}-${item.message}`}>
                {item.code}: {item.message}
              </p>
            ))}
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
                  coverage {report.evidence_coverage_numerator}/
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
