"use client";

import { useCallback, useEffect, useId, useMemo, useState } from "react";

import { MetricInfoButton } from "@/components/metrics/MetricInfoButton";
import { PercentageValue } from "@/components/metrics/PercentageValue";
import { apiRequest } from "@/lib/api";

import type {
  SiteDiagnosticExecution,
  SiteDiagnosticFinding,
  SiteDiagnosticFindingDetail,
  SiteDiagnosticLinkGraph,
  SiteDiagnosticRule,
} from "./types";

interface SiteDiagnosticsPanelProps {
  websiteId: string;
  analysisRunId?: string;
  restrictToAnalysisRun?: boolean;
}

const PAGE_SIZE = 20;
const OCCURRENCE_PAGE_SIZE = 20;

const categoryLabels: Record<string, string> = {
  repeated_pattern: "Repeated Patterns",
  internal_link_graph: "Internal Link Graph",
  canonical_indexability: "Indexability and Canonical",
  metadata_content: "Metadata and Content Patterns",
  near_duplicate: "Metadata and Content Patterns",
  technical_consistency: "Technical Consistency",
  evidence_availability: "Evidence Availability",
};

const sectionCategories = [
  {
    id: "repeated-patterns",
    title: "Repeated Patterns",
    categories: ["repeated_pattern"],
    description: "Repeated, section-level, and template-supported patterns across pages.",
  },
  {
    id: "canonical-indexability",
    title: "Indexability and Canonical",
    categories: ["canonical_indexability"],
    description: "Canonical and indexability consistency based only on persisted evidence.",
  },
  {
    id: "metadata-content",
    title: "Metadata and Content Patterns",
    categories: ["metadata_content", "near_duplicate"],
    description: "Metadata gaps plus deterministic exact and near-duplicate content groups.",
  },
  {
    id: "technical-consistency",
    title: "Technical Consistency",
    categories: ["technical_consistency"],
    description: "Cross-page consistency aggregated from original technical evidence.",
  },
] as const;

function label(value: string | null | undefined): string {
  if (!value) return "Unknown";
  return value.replaceAll("_", " ").replace(/\b\w/g, (character) => character.toUpperCase());
}

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "Not completed";
}

function safeEvidence(value: unknown): string {
  if (value === null || value === undefined) return "Unavailable";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return "Evidence could not be displayed.";
  }
}

function StatusBadge({ value }: { value: string }) {
  const colors: Record<string, string> = {
    completed: "bg-emerald-100 text-emerald-900",
    partial: "bg-amber-100 text-amber-900",
    unavailable: "bg-slate-200 text-slate-900",
    failed: "bg-red-100 text-red-900",
    critical: "bg-red-100 text-red-900",
    high: "bg-orange-100 text-orange-900",
    medium: "bg-amber-100 text-amber-900",
    low: "bg-blue-100 text-blue-900",
    info: "bg-slate-100 text-slate-800",
  };
  return (
    <span className={`rounded-full px-2 py-1 text-xs font-semibold ${colors[value] ?? "bg-slate-100 text-slate-800"}`}>
      {label(value)}
    </span>
  );
}

function EvidenceBlock({ value }: { value: unknown }) {
  return (
    <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-slate-950 p-3 text-xs text-slate-100">
      {safeEvidence(value)}
    </pre>
  );
}

function FindingCards({
  findings,
  onSelect,
}: {
  findings: SiteDiagnosticFinding[];
  onSelect: (id: string) => void;
}) {
  if (!findings.length) {
    return <p className="mt-3 text-sm text-slate-600">No findings in this section for the selected execution and filters.</p>;
  }
  return (
    <ul className="mt-4 grid gap-3">
      {findings.map((finding) => (
        <li className="rounded-xl border border-slate-200 bg-white p-4" key={finding.id}>
          <div className="flex flex-wrap gap-2">
            <StatusBadge value={finding.severity} />
            <StatusBadge value={finding.scope} />
            <StatusBadge value={finding.confidence} />
          </div>
          <h4 className="mt-3 font-semibold text-slate-950">{finding.title}</h4>
          <p className="mt-1 text-sm text-slate-700">{finding.description}</p>
          <p className="mt-2 text-xs text-slate-600">
            {finding.affected_page_count} of {finding.total_eligible_page_count} eligible pages ·{" "}
            {finding.occurrence_count} occurrences · Rule {finding.rule_id} v{finding.rule_version}
          </p>
          <button
            className="mt-3 rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-semibold text-slate-900 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-700"
            onClick={() => onSelect(finding.id)}
            type="button"
          >
            View finding detail
          </button>
        </li>
      ))}
    </ul>
  );
}

function FindingDetail({
  finding,
  loading,
  occurrencePage,
  onOccurrencePage,
  onClose,
}: {
  finding: SiteDiagnosticFindingDetail | null;
  loading: boolean;
  occurrencePage: number;
  onOccurrencePage: (page: number) => void;
  onClose: () => void;
}) {
  if (loading) {
    return <p className="mt-4 text-sm text-slate-600" role="status">Loading finding detail…</p>;
  }
  if (!finding) return null;
  const start = occurrencePage * OCCURRENCE_PAGE_SIZE;
  const occurrences = finding.occurrences.slice(start, start + OCCURRENCE_PAGE_SIZE);
  const totalPages = Math.max(1, Math.ceil(finding.occurrences.length / OCCURRENCE_PAGE_SIZE));
  return (
    <section
      aria-labelledby={`finding-${finding.id}`}
      className="mt-6 rounded-2xl border-2 border-slate-300 bg-slate-50 p-5"
      tabIndex={-1}
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase text-slate-500">Finding Detail</p>
          <h3 className="mt-1 text-xl font-bold" id={`finding-${finding.id}`}>{finding.title}</h3>
        </div>
        <button
          className="rounded border px-2 py-1 text-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-700"
          onClick={onClose}
          type="button"
        >
          Close
        </button>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <StatusBadge value={finding.severity} />
        <StatusBadge value={finding.scope} />
        <StatusBadge value={finding.confidence} />
      </div>
      <dl className="mt-5 grid gap-4 text-sm md:grid-cols-2">
        <div className="md:col-span-2"><dt className="font-semibold">What was found</dt><dd className="mt-1">{finding.description}</dd></div>
        <div className="md:col-span-2"><dt className="font-semibold">Why it matters</dt><dd className="mt-1">{finding.why_it_matters}</dd></div>
        <div><dt className="font-semibold">Responsible role</dt><dd className="mt-1">{finding.responsible_role}</dd></div>
        <div><dt className="font-semibold">Rule and category</dt><dd className="mt-1">{finding.rule_id} · {label(finding.category)}</dd></div>
        <div className="md:col-span-2"><dt className="font-semibold">Remediation</dt><dd className="mt-1">{finding.remediation_guidance}</dd></div>
        <div className="md:col-span-2"><dt className="font-semibold">Verification</dt><dd className="mt-1">{finding.verification_guidance}</dd></div>
        <div className="md:col-span-2"><dt className="font-semibold">Evidence summary</dt><dd className="mt-1">{finding.evidence_summary}</dd></div>
        <div className="md:col-span-2"><dt className="font-semibold">Original evidence references</dt><dd className="mt-2"><EvidenceBlock value={finding.evidence_references} /></dd></div>
      </dl>
      <h4 className="mt-6 font-semibold">Occurrences ({finding.occurrences.length})</h4>
      {!occurrences.length ? (
        <p className="mt-2 text-sm text-slate-600">No occurrence records were persisted for this finding.</p>
      ) : (
        <ul className="mt-3 grid gap-3">
          {occurrences.map((occurrence) => (
            <li className="rounded-lg border bg-white p-3 text-sm" key={occurrence.id}>
              <p className="break-all font-semibold">{occurrence.normalized_url ?? "Page URL unavailable"}</p>
              <p className="mt-1 break-all text-xs text-slate-600">Evidence: {occurrence.evidence_reference}</p>
              {occurrence.location && <p className="mt-1 text-xs">Location: {occurrence.location}</p>}
              {occurrence.element_selector && <p className="mt-1 break-all text-xs">Selector: {occurrence.element_selector}</p>}
              <details className="mt-2">
                <summary className="cursor-pointer text-xs font-semibold">Supporting evidence</summary>
                <div className="mt-2"><EvidenceBlock value={occurrence.supporting_evidence} /></div>
              </details>
            </li>
          ))}
        </ul>
      )}
      {totalPages > 1 && (
        <div className="mt-4 flex items-center justify-between text-sm">
          <button className="rounded border px-3 py-1 disabled:opacity-50" disabled={occurrencePage === 0} onClick={() => onOccurrencePage(occurrencePage - 1)} type="button">Previous occurrences</button>
          <span>Page {occurrencePage + 1} of {totalPages}</span>
          <button className="rounded border px-3 py-1 disabled:opacity-50" disabled={occurrencePage + 1 >= totalPages} onClick={() => onOccurrencePage(occurrencePage + 1)} type="button">Next occurrences</button>
        </div>
      )}
    </section>
  );
}

function History({
  executions,
  activeExecution,
  onSelect,
}: {
  executions: SiteDiagnosticExecution[];
  activeExecution: SiteDiagnosticExecution;
  onSelect: (execution: SiteDiagnosticExecution) => void;
}) {
  const prior = executions.find((item) => item.id !== activeExecution.id);
  return (
    <section aria-labelledby="site-diagnostics-history" className="mt-8">
      <h3 className="text-lg font-bold" id="site-diagnostics-history">History</h3>
      <p className="mt-1 text-sm text-slate-600">Executions are immutable. Select a historical execution to inspect its retained findings.</p>
      {prior && (
        <p className="mt-3 rounded-lg bg-blue-50 p-3 text-sm">
          Compared with the next most recent execution: processed pages{" "}
          {activeExecution.processed_page_count - prior.processed_page_count >= 0 ? "+" : ""}
          {activeExecution.processed_page_count - prior.processed_page_count}; evidence coverage{" "}
          {Math.round((activeExecution.evidence_coverage_ratio - prior.evidence_coverage_ratio) * 1000) / 10} percentage points.
        </p>
      )}
      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[680px] text-left text-sm">
          <thead><tr className="border-b"><th className="p-2">Execution</th><th>Status</th><th>Coverage</th><th>Pages</th><th>Completed</th><th>Action</th></tr></thead>
          <tbody>
            {executions.map((execution) => (
              <tr className={execution.id === activeExecution.id ? "border-b bg-blue-50" : "border-b"} key={execution.id}>
                <td className="max-w-48 break-all p-2 font-mono text-xs">{execution.execution_id}</td>
                <td><StatusBadge value={execution.status} /></td>
                <td>{execution.evidence_coverage_numerator}/{execution.evidence_coverage_denominator} ({Math.round(execution.evidence_coverage_ratio * 100)}%)</td>
                <td>{execution.processed_page_count}/{execution.total_page_count}</td>
                <td>{formatDate(execution.completed_at)}</td>
                <td><button className="rounded border px-2 py-1 font-semibold disabled:opacity-50" disabled={execution.id === activeExecution.id} onClick={() => onSelect(execution)} type="button">{execution.id === activeExecution.id ? "Selected" : "Inspect"}</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function SiteDiagnosticsPanel({
  websiteId,
  analysisRunId,
  restrictToAnalysisRun = false,
}: SiteDiagnosticsPanelProps) {
  const filterId = useId();
  const [execution, setExecution] = useState<SiteDiagnosticExecution | null>(null);
  const [history, setHistory] = useState<SiteDiagnosticExecution[]>([]);
  const [rules, setRules] = useState<SiteDiagnosticRule[]>([]);
  const [findings, setFindings] = useState<SiteDiagnosticFinding[]>([]);
  const [graph, setGraph] = useState<SiteDiagnosticLinkGraph | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [graphMessage, setGraphMessage] = useState<string | null>(null);
  const [selectedFinding, setSelectedFinding] = useState<SiteDiagnosticFindingDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [occurrencePage, setOccurrencePage] = useState(0);
  const [category, setCategory] = useState("");
  const [severity, setSeverity] = useState("");
  const [scope, setScope] = useState("");
  const [confidence, setConfidence] = useState("");
  const [ruleId, setRuleId] = useState("");
  const [offset, setOffset] = useState(0);

  const loadHistoryAndRules = useCallback(async () => {
    const params = new URLSearchParams({ limit: "50" });
    if (analysisRunId && restrictToAnalysisRun) params.set("analysis_run_id", analysisRunId);
    const [nextHistory, nextRules] = await Promise.all([
      apiRequest<SiteDiagnosticExecution[]>(`/api/v1/websites/${websiteId}/site-diagnostics/history?${params.toString()}`),
      apiRequest<SiteDiagnosticRule[]>("/api/v1/metadata/site-diagnostic-rules"),
    ]);
    setHistory(nextHistory);
    setRules(nextRules);
    return nextHistory;
  }, [analysisRunId, restrictToAnalysisRun, websiteId]);

  const loadInitial = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const nextHistory = await loadHistoryAndRules();
      if (!nextHistory.length) {
        setExecution(null);
        setFindings([]);
        setGraph(null);
        return;
      }
      setExecution(nextHistory[0]);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to load site diagnostics.");
    } finally {
      setLoading(false);
    }
  }, [loadHistoryAndRules]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadInitial(), 0);
    return () => window.clearTimeout(timer);
  }, [loadInitial]);

  useEffect(() => {
    if (!execution) return;
    let cancelled = false;
    const params = new URLSearchParams({
      execution_id: execution.id,
      limit: String(PAGE_SIZE),
      offset: String(offset),
    });
    if (category) params.set("category", category);
    if (severity) params.set("severity", severity);
    if (scope) params.set("scope", scope);
    if (confidence) params.set("confidence", confidence);
    if (ruleId) params.set("rule_id", ruleId);
    void apiRequest<SiteDiagnosticFinding[]>(`/api/v1/websites/${websiteId}/site-diagnostics/findings?${params.toString()}`)
      .then((items) => { if (!cancelled) setFindings(items); })
      .catch((requestError: unknown) => {
        if (!cancelled) setError(requestError instanceof Error ? requestError.message : "Unable to load diagnostic findings.");
      });
    return () => { cancelled = true; };
  }, [category, confidence, execution, offset, ruleId, scope, severity, websiteId]);

  useEffect(() => {
    if (!execution) return;
    let cancelled = false;
    void apiRequest<SiteDiagnosticLinkGraph>(`/api/v1/websites/${websiteId}/site-diagnostics/link-graph?execution_id=${execution.id}&node_limit=100&edge_limit=200`)
      .then((nextGraph) => {
        if (!cancelled) {
          setGraph(nextGraph);
          setGraphMessage(null);
        }
      })
      .catch((requestError: unknown) => {
        if (!cancelled) {
          setGraph(null);
          setGraphMessage(requestError instanceof Error ? requestError.message : "Link-graph evidence is unavailable.");
        }
      });
    return () => { cancelled = true; };
  }, [execution, websiteId]);

  async function generate() {
    if (!analysisRunId) {
      setError("Start or open a completed analysis run before generating site diagnostics.");
      return;
    }
    setGenerating(true);
    setError(null);
    try {
      const generated = await apiRequest<SiteDiagnosticExecution>(
        `/api/v1/analysis-runs/${analysisRunId}/site-diagnostics/generate`,
        {
          method: "POST",
          body: JSON.stringify({ idempotency_key: crypto.randomUUID() }),
        },
      );
      await loadHistoryAndRules();
      setExecution(generated);
      setOffset(0);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to generate site diagnostics.");
    } finally {
      setGenerating(false);
    }
  }

  async function openFinding(id: string) {
    setDetailLoading(true);
    setOccurrencePage(0);
    try {
      setSelectedFinding(await apiRequest<SiteDiagnosticFindingDetail>(`/api/v1/site-diagnostics/findings/${id}`));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to load finding detail.");
    } finally {
      setDetailLoading(false);
    }
  }

  function chooseExecution(nextExecution: SiteDiagnosticExecution) {
    setExecution(nextExecution);
    setGraph(null);
    setGraphMessage(null);
    setOffset(0);
    setSelectedFinding(null);
  }

  function updateFilter(setter: (value: string) => void, value: string) {
    setter(value);
    setOffset(0);
    setSelectedFinding(null);
  }

  const findingCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const finding of findings) counts[finding.category] = (counts[finding.category] ?? 0) + 1;
    return counts;
  }, [findings]);

  return (
    <section
      aria-labelledby={`site-diagnostics-title-${websiteId}`}
      className="scroll-mt-6 rounded-2xl border border-slate-200 bg-white p-5"
      id={`site-diagnostics-${websiteId}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Deterministic persisted evidence</p>
          <h2 className="mt-1 text-2xl font-bold text-slate-950" id={`site-diagnostics-title-${websiteId}`}>Site-Wide Diagnostics</h2>
          <p className="mt-1 text-sm text-slate-600">Cross-page patterns, link structure, indexability, metadata, content, and technical consistency.</p>
        </div>
        <button
          className="rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-700"
          disabled={generating || !analysisRunId}
          onClick={() => void generate()}
          type="button"
        >
          {generating ? "Generating…" : execution ? "Generate new execution" : "Generate diagnostics"}
        </button>
      </div>
      {!analysisRunId && <p className="mt-2 text-xs text-slate-500">Generation is available from a completed analysis run report.</p>}
      {loading && <p className="mt-5 text-sm text-slate-600" role="status">Loading site diagnostics…</p>}
      {error && <p className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-800" role="alert">{error}</p>}
      {!loading && !execution && !error && (
        <div className="mt-5 rounded-xl border border-dashed border-slate-300 p-5">
          <h3 className="font-semibold">Diagnostics have not been generated</h3>
          <p className="mt-1 text-sm text-slate-600">No execution exists for this context. This is not evidence that the site has no issues.</p>
        </div>
      )}
      {execution && (
        <>
          <section aria-labelledby="site-health-overview" className="mt-7">
            <div className="flex flex-wrap items-center gap-3">
              <h3 className="text-lg font-bold" id="site-health-overview">Site Health Overview</h3>
              <StatusBadge value={execution.status} />
            </div>
            <p className="mt-1 text-sm text-slate-600">
              Profile {execution.selected_profile_id} v{execution.selected_profile_version} · Engine {execution.diagnostic_engine_version} · Rules {execution.rule_registry_version}
            </p>
            <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <div className="rounded-xl bg-slate-50 p-4">
                <div className="flex items-center justify-between text-xs text-slate-600">Evidence coverage <MetricInfoButton metricId="site_diagnostic_coverage_percentage" /></div>
                <p className="mt-1 text-2xl font-bold"><PercentageValue metricId="site_diagnostic_coverage_percentage" value={execution.evidence_coverage_ratio * 100} /></p>
                <p className="text-xs text-slate-600">{execution.evidence_coverage_numerator} of {execution.evidence_coverage_denominator} pages</p>
              </div>
              <div className="rounded-xl bg-slate-50 p-4"><p className="text-xs text-slate-600">Processed pages</p><p className="mt-1 text-2xl font-bold">{execution.processed_page_count}/{execution.total_page_count}</p></div>
              <div className="rounded-xl bg-slate-50 p-4"><p className="text-xs text-slate-600">Failed pages</p><p className="mt-1 text-2xl font-bold">{execution.failed_page_count}</p></div>
              <div className="rounded-xl bg-slate-50 p-4"><p className="text-xs text-slate-600">Visible filtered findings</p><p className="mt-1 text-2xl font-bold">{findings.length}</p></div>
            </div>
            {(execution.status === "partial" || execution.failed_page_count > 0) && (
              <div className="mt-4 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950" role="status">
                This execution is partial. Missing or failed evidence is preserved and must not be read as a clean result.
              </div>
            )}
            {Object.keys(execution.error_metadata).length > 0 && (
              <details className="mt-3"><summary className="cursor-pointer text-sm font-semibold">Unavailable/error metadata</summary><div className="mt-2"><EvidenceBlock value={execution.error_metadata} /></div></details>
            )}
            {Object.keys(execution.partial_completion_metadata).length > 0 && (
              <details className="mt-3"><summary className="cursor-pointer text-sm font-semibold">Partial evidence metadata</summary><div className="mt-2"><EvidenceBlock value={execution.partial_completion_metadata} /></div></details>
            )}
          </section>

          <section aria-labelledby={`${filterId}-filters`} className="mt-8 rounded-xl border bg-slate-50 p-4">
            <h3 className="font-semibold" id={`${filterId}-filters`}>Finding filters</h3>
            <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
              <label className="grid gap-1 text-sm">Category<select className="rounded border bg-white px-2 py-2" value={category} onChange={(event) => updateFilter(setCategory, event.target.value)}><option value="">All categories</option>{Object.entries(categoryLabels).map(([value, name]) => <option key={value} value={value}>{name}</option>)}</select></label>
              <label className="grid gap-1 text-sm">Severity<select className="rounded border bg-white px-2 py-2" value={severity} onChange={(event) => updateFilter(setSeverity, event.target.value)}><option value="">All severities</option>{["critical", "high", "medium", "low", "info"].map((value) => <option key={value} value={value}>{label(value)}</option>)}</select></label>
              <label className="grid gap-1 text-sm">Scope<select className="rounded border bg-white px-2 py-2" value={scope} onChange={(event) => updateFilter(setScope, event.target.value)}><option value="">All scopes</option>{["page", "section", "template", "site"].map((value) => <option key={value} value={value}>{label(value)}</option>)}</select></label>
              <label className="grid gap-1 text-sm">Confidence<select className="rounded border bg-white px-2 py-2" value={confidence} onChange={(event) => updateFilter(setConfidence, event.target.value)}><option value="">All confidence</option>{["high", "medium", "low", "unavailable"].map((value) => <option key={value} value={value}>{label(value)}</option>)}</select></label>
              <label className="grid gap-1 text-sm">Rule<select className="rounded border bg-white px-2 py-2" value={ruleId} onChange={(event) => updateFilter(setRuleId, event.target.value)}><option value="">All {rules.length} rules</option>{rules.map((rule) => <option key={rule.id} value={rule.id}>{rule.id}</option>)}</select></label>
            </div>
          </section>

          {sectionCategories.map((section) => {
            const sectionFindings = findings.filter((finding) => section.categories.includes(finding.category as never));
            return (
              <section aria-labelledby={`${filterId}-${section.id}`} className="mt-8" key={section.id}>
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="text-lg font-bold" id={`${filterId}-${section.id}`}>{section.title}</h3>
                  <span className="rounded-full bg-slate-100 px-2 py-1 text-xs">{sectionFindings.length}</span>
                </div>
                <p className="mt-1 text-sm text-slate-600">{section.description}</p>
                <FindingCards findings={sectionFindings} onSelect={(id) => void openFinding(id)} />
              </section>
            );
          })}

          <section aria-labelledby={`${filterId}-link-graph`} className="mt-8">
            <h3 className="text-lg font-bold" id={`${filterId}-link-graph`}>Internal Link Graph</h3>
            <p className="mt-1 text-sm text-slate-600">Persisted internal nodes and edges; external, mailto, tel, and JavaScript links are excluded by the backend.</p>
            {graphMessage && <p className="mt-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-950" role="status">{graphMessage} This does not mean the graph has no issues.</p>}
            {graph && (
              <>
                <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-4">
                  <div className="rounded-lg bg-slate-50 p-3"><dt>Evidence</dt><dd className="font-semibold">{graph.evidence_complete ? "Complete for persisted inputs" : "Partial/unavailable inputs"}</dd></div>
                  <div className="rounded-lg bg-slate-50 p-3"><dt>Nodes</dt><dd className="text-xl font-bold">{graph.total_nodes}</dd></div>
                  <div className="rounded-lg bg-slate-50 p-3"><dt>Edges</dt><dd className="text-xl font-bold">{graph.total_edges}</dd></div>
                  <div className="rounded-lg bg-slate-50 p-3"><dt>Malformed links</dt><dd className="text-xl font-bold">{graph.total_malformed_edges}</dd></div>
                </dl>
                <details className="mt-4">
                  <summary className="cursor-pointer font-semibold">Link nodes ({graph.nodes.length} shown)</summary>
                  <div className="mt-2 overflow-x-auto"><table className="w-full min-w-[640px] text-left text-xs"><thead><tr className="border-b"><th className="p-2">URL</th><th>Depth</th><th>Inbound</th><th>Outbound</th><th>Status</th></tr></thead><tbody>{graph.nodes.map((node) => <tr className="border-b" key={node.page_id}><td className="max-w-80 break-all p-2">{node.normalized_url}</td><td>{node.crawl_depth}</td><td>{node.inbound_link_count}</td><td>{node.outbound_evidence_available ? node.outbound_link_count : "Unavailable"}</td><td>{node.http_status_code ?? "Unavailable"}</td></tr>)}</tbody></table></div>
                </details>
                <details className="mt-4">
                  <summary className="cursor-pointer font-semibold">Link edges ({graph.edges.length} shown)</summary>
                  <ul className="mt-2 grid gap-2">{graph.edges.map((edge, index) => <li className="rounded-lg border p-3 text-xs" key={`${edge.source_page_id}-${edge.raw_target}-${index}`}><p className="break-all"><strong>From:</strong> {edge.source_url}</p><p className="break-all"><strong>To:</strong> {edge.target_url}</p><p className="break-all text-slate-600"><strong>Evidence:</strong> {edge.evidence_reference}</p></li>)}</ul>
                </details>
              </>
            )}
            <FindingCards findings={findings.filter((finding) => finding.category === "internal_link_graph")} onSelect={(id) => void openFinding(id)} />
          </section>

          <FindingDetail finding={selectedFinding} loading={detailLoading} occurrencePage={occurrencePage} onOccurrencePage={setOccurrencePage} onClose={() => setSelectedFinding(null)} />

          <div className="mt-6 flex items-center justify-between text-sm">
            <button className="rounded border px-3 py-1.5 disabled:opacity-50" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))} type="button">Previous findings</button>
            <span>Showing {findings.length ? offset + 1 : 0}–{offset + findings.length}</span>
            <button className="rounded border px-3 py-1.5 disabled:opacity-50" disabled={findings.length < PAGE_SIZE} onClick={() => setOffset(offset + PAGE_SIZE)} type="button">Next findings</button>
          </div>
          <p className="mt-2 text-xs text-slate-500">Category counts on this page: {Object.entries(findingCounts).map(([name, count]) => `${label(name)} ${count}`).join(" · ") || "none"}</p>

          <History executions={history} activeExecution={execution} onSelect={chooseExecution} />
        </>
      )}
    </section>
  );
}

export function SiteDiagnosticsReference({
  websiteId,
  context,
}: {
  websiteId: string;
  context: "page-analysis" | "action-plan";
}) {
  return (
    <aside className="mt-4 rounded-lg border border-blue-200 bg-blue-50 p-4" aria-label="Site diagnostic evidence">
      <h4 className="font-semibold">Site-wide diagnostic evidence</h4>
      <p className="mt-1 text-sm text-slate-700">
        {context === "action-plan"
          ? "Use persisted site-diagnostic evidence references and page occurrences when translating repeated findings into actions. The Action Plan remains a separate, evidence-linked workflow."
          : "Cross-page diagnostics complement page-level analysis by retaining repeated patterns and original evidence for every affected page."}
      </p>
      <a
        className="mt-2 inline-block font-semibold text-blue-800 underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-700"
        href={`#site-diagnostics-${websiteId}`}
      >
        Review site-wide diagnostics
      </a>
    </aside>
  );
}
