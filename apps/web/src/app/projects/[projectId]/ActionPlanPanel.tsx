"use client";

import { useCallback, useEffect, useState } from "react";

import { apiRequest } from "@/lib/api";
import type {
  ActionGroup,
  ActionGroupDetail,
  ActionItemDetail,
  ActionPlanSummary,
  PaginatedResponse,
} from "@/lib/types";

interface ActionPlanPanelProps {
  websiteId: string;
}

function SeverityBadge({ severity }: { severity: string }) {
  const colors: Record<string, string> = {
    critical: "bg-red-100 text-red-800",
    high: "bg-orange-100 text-orange-800",
    medium: "bg-amber-100 text-amber-800",
    low: "bg-slate-100 text-slate-600",
    informational: "bg-blue-100 text-blue-800",
  };
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-bold ${colors[severity] ?? "bg-slate-100 text-slate-600"}`}>
      {severity}
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    open: "bg-blue-100 text-blue-800",
    acknowledged: "bg-slate-100 text-slate-700",
    in_progress: "bg-amber-100 text-amber-800",
    resolved: "bg-emerald-100 text-emerald-800",
    ignored: "bg-slate-100 text-slate-400",
    reopened: "bg-purple-100 text-purple-800",
    mixed: "bg-striped text-slate-700",
  };
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-bold ${colors[status] ?? "bg-slate-100 text-slate-600"}`}>
      {status.replace("_", " ")}
    </span>
  );
}

function InfoButton({ label, explanation }: { label: string; explanation: string }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="relative inline-flex items-center">
      <button
        aria-label={`Info about ${label}`}
        className="ml-1 inline-flex size-5 cursor-help items-center justify-center rounded-full border text-xs hover:bg-slate-100 focus:outline-none focus:ring-2 focus:ring-blue-400"
        onClick={() => setOpen(!open)}
        onKeyDown={(e) => { if (e.key === "Escape") setOpen(false); }}
        type="button"
      >
        i
      </button>
      {open && (
        <div
          className="absolute bottom-full left-1/2 z-10 mb-2 w-72 -translate-x-1/2 rounded-lg border bg-white p-3 text-xs shadow-lg"
          role="tooltip"
        >
          <p>{explanation}</p>
          <button
            className="mt-2 text-blue-600 underline"
            onClick={() => setOpen(false)}
            type="button"
          >
            Close
          </button>
        </div>
      )}
    </span>
  );
}

function SummaryCard({ label, value, explanation }: { label: string; value: string | number; explanation?: string }) {
  return (
    <div className="rounded-xl border bg-white p-4">
      <p className="text-xs text-slate-500">
        {label}
        {explanation && <InfoButton label={label} explanation={explanation} />}
      </p>
      <p className="mt-1 text-2xl font-bold">{value}</p>
    </div>
  );
}

function PriorityBar({ score }: { score: number }) {
  const barColor = score >= 70 ? "bg-red-500" : score >= 40 ? "bg-amber-500" : "bg-emerald-500";
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-16 overflow-hidden rounded-full bg-slate-200">
        <div className={`h-full ${barColor}`} style={{ width: `${score}%` }} />
      </div>
      <span className="text-sm font-bold">{score}/100</span>
    </div>
  );
}

export function ActionPlanPanel({ websiteId }: ActionPlanPanelProps) {
  const [summary, setSummary] = useState<ActionPlanSummary | null>(null);
  const [pageAnalysisExecutionId, setPageAnalysisExecutionId] = useState<string | null>(null);
  const [groups, setGroups] = useState<ActionGroup[]>([]);
  const [groupsTotal, setGroupsTotal] = useState(0);
  const [groupsPage, setGroupsPage] = useState(1);
  const [groupsLoading, setGroupsLoading] = useState(false);

  const [selectedGroup, setSelectedGroup] = useState<ActionGroupDetail | null>(null);
  const [selectedAction, setSelectedAction] = useState<ActionItemDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const [filterStatus, setFilterStatus] = useState("");
  const [filterSeverity, setFilterSeverity] = useState("");
  const filterCategory = "";
  const [searchQuery, setSearchQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);

  const groupPageSize = 20;

  const loadSummary = useCallback(async () => {
    try {
      const result = await apiRequest<ActionPlanSummary>(
        `/api/v1/websites/${websiteId}/action-plan/summary`
      );
      setSummary(result);
    } catch {
      // Not available yet
    }
  }, [websiteId]);

  const loadGroups = useCallback(async () => {
    setGroupsLoading(true);
    try {
      const params = new URLSearchParams();
      params.set("page", String(groupsPage));
      params.set("page_size", String(groupPageSize));
      if (filterStatus) params.set("status", filterStatus);
      if (filterSeverity) params.set("severity", filterSeverity);
      if (filterCategory) params.set("category", filterCategory);

      const result = await apiRequest<PaginatedResponse<ActionGroup>>(
        `/api/v1/websites/${websiteId}/action-plan/groups?${params.toString()}`
      );
      setGroups(result.items);
      setGroupsTotal(result.total);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to load action groups.");
    } finally {
      setGroupsLoading(false);
    }
  }, [websiteId, groupsPage, filterStatus, filterSeverity, filterCategory]);

  const loadExecutionId = useCallback(async () => {
    try {
      const result = await apiRequest<{ items: Array<{ page_analysis_execution_id: string }> }>(
        `/api/v1/websites/${websiteId}/page-analysis/runs?page_size=1`
      );
      if (result.items.length > 0) {
        setPageAnalysisExecutionId(result.items[0].page_analysis_execution_id);
      }
    } catch {
      // No runs yet
    }
  }, [websiteId]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadSummary().catch(() => {});
      void loadExecutionId().catch(() => {});
      void loadGroups().catch(() => {});
    }, 0);
    return () => window.clearTimeout(timer);
  }, [loadSummary, loadExecutionId, loadGroups]);

  async function generateActions() {
    if (!pageAnalysisExecutionId) return;
    setGenerating(true);
    setError(null);
    try {
      await apiRequest(
        `/api/v1/websites/${websiteId}/action-plan/generate`,
        {
          method: "POST",
          body: JSON.stringify({ page_analysis_execution_id: pageAnalysisExecutionId }),
        },
      );
      setGenerating(false);
      await loadSummary();
      await loadGroups();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to generate actions.");
      setGenerating(false);
    }
  }

  async function openGroupDetail(groupId: string) {
    setDetailLoading(true);
    setSelectedAction(null);
    try {
      const result = await apiRequest<ActionGroupDetail>(
        `/api/v1/websites/${websiteId}/action-plan/groups/${groupId}`
      );
      setSelectedGroup(result);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to load group detail.");
    } finally {
      setDetailLoading(false);
    }
  }

  async function openActionDetail(actionId: string) {
    setDetailLoading(true);
    try {
      const result = await apiRequest<ActionItemDetail>(
        `/api/v1/websites/${websiteId}/action-plan/actions/${actionId}`
      );
      setSelectedAction(result);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to load action detail.");
    } finally {
      setDetailLoading(false);
    }
  }

  async function updateStatus(actionId: string, newStatus: string) {
    try {
      await apiRequest(
        `/api/v1/websites/${websiteId}/action-plan/actions/${actionId}/status`,
        {
          method: "PATCH",
          body: JSON.stringify({ status: newStatus, source: "manual" }),
        },
      );
      await loadSummary();
      await loadGroups();
      if (selectedAction?.id === actionId) {
        await openActionDetail(actionId);
      }
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to update status.");
    }
  }

  const totalPages = Math.ceil(groupsTotal / groupPageSize) || 1;

  const statusOptions = [
    { value: "", label: "All statuses" },
    { value: "open", label: "Open" },
    { value: "acknowledged", label: "Acknowledged" },
    { value: "in_progress", label: "In progress" },
    { value: "resolved", label: "Resolved" },
    { value: "ignored", label: "Ignored" },
    { value: "reopened", label: "Reopened" },
  ];

  const severityOptions = [
    { value: "", label: "All severities" },
    { value: "critical", label: "Critical" },
    { value: "high", label: "High" },
    { value: "medium", label: "Medium" },
    { value: "low", label: "Low" },
  ];

  return (
    <section className="mt-5 border-t pt-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="font-semibold">Action Plan</h3>
        <div className="flex gap-2">
          {pageAnalysisExecutionId && (
            <button
              className="rounded-lg border bg-slate-950 px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50"
              disabled={generating || !pageAnalysisExecutionId}
              onClick={() => void generateActions()}
              type="button"
            >
              {generating ? "Generating…" : "Generate actions"}
            </button>
          )}
        </div>
      </div>

      {error && <p className="mt-2 text-sm text-red-700" role="alert">{error}</p>}

      {summary && summary.generation_execution_id && (
        <div className="mt-4">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <SummaryCard
              label="Open actions"
              value={summary.total_open}
              explanation="Actions that have not yet been addressed."
            />
            <SummaryCard
              label="Critical"
              value={summary.critical_actions}
              explanation="Actions with critical severity requiring immediate attention."
            />
            <SummaryCard
              label="High priority"
              value={summary.high_priority_actions}
              explanation={`Actions with priority score >= 70. Average priority: ${summary.average_priority ?? "—"}/100`}
            />
            <SummaryCard
              label="Pages to fix"
              value={summary.pages_requiring_correction}
              explanation="Unique pages with open or in-progress actions."
            />
            <SummaryCard
              label="Resolved"
              value={summary.total_resolved}
              explanation="Actions that have been completed and verified."
            />
          </div>

          {summary.generation_coverage !== null && (
            <p className="mt-2 text-xs text-slate-500">
              Generation coverage: {summary.generation_coverage}% ({summary.generation_status})
            </p>
          )}
        </div>
      )}

      {!summary?.generation_execution_id && !generating && (
        <p className="mt-4 text-sm text-slate-500">
          {pageAnalysisExecutionId
            ? "No action plan generated yet. Click 'Generate actions' to create an action plan from page analysis findings."
            : "Run page analysis first, then return here to generate an action plan."}
        </p>
      )}

      {(summary?.generation_execution_id || groups.length > 0) && (
        <div className="mt-4">
          <div className="flex flex-wrap gap-2 border-b pb-2">
            <input
              aria-label="Search actions"
              className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm"
              placeholder="Search groups…"
              type="search"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
            <select
              aria-label="Filter by status"
              className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm"
              value={filterStatus}
              onChange={(e) => { setFilterStatus(e.target.value); setGroupsPage(1); }}
            >
              {statusOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
            <select
              aria-label="Filter by severity"
              className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm"
              value={filterSeverity}
              onChange={(e) => { setFilterSeverity(e.target.value); setGroupsPage(1); }}
            >
              {severityOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </div>

          {groupsLoading ? (
            <p className="mt-4 text-sm text-slate-500" role="status">Loading action groups…</p>
          ) : groups.length === 0 ? (
            <p className="mt-4 text-sm text-slate-500">No action groups found.</p>
          ) : (
            <div className="mt-4 overflow-x-auto">
              <table className="w-full min-w-[700px] text-left text-xs">
                <thead>
                  <tr className="border-b">
                    <th className="p-2">Issue</th>
                    <th>Category</th>
                    <th>Severity</th>
                    <th>Priority</th>
                    <th>Pages</th>
                    <th>Area</th>
                    <th>Role</th>
                    <th>Status</th>
                    <th>Updated</th>
                  </tr>
                </thead>
                <tbody>
                  {groups.map((g) => (
                    <tr
                      className="cursor-pointer border-b align-top transition-colors hover:bg-slate-50"
                      key={g.id}
                      onClick={() => void openGroupDetail(g.id)}
                      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") openGroupDetail(g.id); }}
                      tabIndex={0}
                      role="button"
                      aria-label={`View details for ${g.issue_title}`}
                    >
                      <td className="max-w-56 p-2 font-semibold">{g.issue_title}</td>
                      <td className="p-2 capitalize">{g.category}</td>
                      <td className="p-2"><SeverityBadge severity={g.severity} /></td>
                      <td className="p-2"><PriorityBar score={g.priority_score} /></td>
                      <td className="p-2">{g.affected_page_count}</td>
                      <td className="p-2">{g.responsible_area}</td>
                      <td className="p-2">{g.responsible_role}</td>
                      <td className="p-2"><StatusBadge status={g.status} /></td>
                      <td className="p-2 text-slate-500">{new Date(g.updated_at).toLocaleDateString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <div className="mt-4 flex items-center justify-between">
                <p className="text-xs text-slate-500">
                  Page {groupsPage} of {totalPages} ({groupsTotal} groups)
                </p>
                <div className="flex gap-2">
                  <button
                    className="rounded-lg border px-3 py-1 text-sm disabled:opacity-50"
                    disabled={groupsPage <= 1}
                    onClick={() => setGroupsPage((p) => Math.max(1, p - 1))}
                    type="button"
                  >
                    Previous
                  </button>
                  <button
                    className="rounded-lg border px-3 py-1 text-sm disabled:opacity-50"
                    disabled={groupsPage >= totalPages}
                    onClick={() => setGroupsPage((p) => p + 1)}
                    type="button"
                  >
                    Next
                  </button>
                </div>
              </div>
            </div>
          )}

          {selectedGroup && !detailLoading && (
            <div className="mt-6 rounded-xl border bg-white p-4">
              <div className="flex items-start justify-between">
                <h4 className="text-lg font-semibold">{selectedGroup.issue_title}</h4>
                <button
                  className="text-sm text-slate-500 underline"
                  onClick={() => setSelectedGroup(null)}
                  type="button"
                >
                  Close
                </button>
              </div>

              <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
                <div>
                  <dt className="text-slate-500">Category</dt>
                  <dd className="font-medium capitalize">{selectedGroup.category}</dd>
                </div>
                <div>
                  <dt className="text-slate-500">Severity</dt>
                  <dd><SeverityBadge severity={selectedGroup.severity} /></dd>
                </div>
                <div>
                  <dt className="text-slate-500">Priority</dt>
                  <dd><PriorityBar score={selectedGroup.priority_score} /></dd>
                </div>
                <div>
                  <dt className="text-slate-500">Confidence</dt>
                  <dd className="font-medium capitalize">{selectedGroup.confidence}</dd>
                </div>
                <div>
                  <dt className="text-slate-500">Estimated effort</dt>
                  <dd className="font-medium capitalize">{selectedGroup.estimated_effort}</dd>
                </div>
                <div>
                  <dt className="text-slate-500">Status</dt>
                  <dd><StatusBadge status={selectedGroup.status} /></dd>
                </div>
                <div>
                  <dt className="text-slate-500">Responsible area</dt>
                  <dd className="font-medium">{selectedGroup.responsible_area}</dd>
                </div>
                <div>
                  <dt className="text-slate-500">Responsible role</dt>
                  <dd className="font-medium">{selectedGroup.responsible_role}</dd>
                </div>
                <div className="sm:col-span-2">
                  <dt className="text-slate-500">Action location</dt>
                  <dd className="font-medium">{selectedGroup.action_location}</dd>
                </div>
                <div className="sm:col-span-2">
                  <dt className="text-slate-500">Business impact</dt>
                  <dd>{selectedGroup.business_impact}</dd>
                </div>
              </dl>

              <div className="mt-4 space-y-4 text-sm">
                <div>
                  <h5 className="font-semibold text-slate-700">Why this matters</h5>
                  <p className="mt-1 text-slate-600">{selectedGroup.why_this_matters}</p>
                </div>
                <div>
                  <h5 className="font-semibold text-slate-700">Exact correction</h5>
                  <p className="mt-1 text-slate-600">{selectedGroup.exact_correction}</p>
                </div>
                <div>
                  <h5 className="font-semibold text-slate-700">Implementation steps</h5>
                  <pre className="mt-1 whitespace-pre-wrap text-slate-600">{selectedGroup.implementation_steps}</pre>
                </div>
                <div>
                  <h5 className="font-semibold text-slate-700">Verification steps</h5>
                  <pre className="mt-1 whitespace-pre-wrap text-slate-600">{selectedGroup.verification_steps}</pre>
                </div>
                <div>
                  <h5 className="font-semibold text-slate-700">Expected result</h5>
                  <p className="mt-1 text-slate-600">{selectedGroup.expected_result}</p>
                </div>
                <div>
                  <h5 className="font-semibold text-slate-700">Limitations</h5>
                  <p className="mt-1 text-slate-600">{selectedGroup.limitations}</p>
                </div>
                <div>
                  <h5 className="font-semibold text-slate-700">Source</h5>
                  <p className="mt-1 text-slate-600">{selectedGroup.source_audit}</p>
                </div>
                <div>
                  <h5 className="font-semibold text-slate-700">Priority components</h5>
                  <pre className="mt-1 whitespace-pre-wrap text-xs text-slate-500">
                    {JSON.stringify(selectedGroup.priority_components, null, 2)}
                  </pre>
                </div>
              </div>

              {selectedGroup.actions.length > 0 && (
                <div className="mt-6">
                  <h5 className="font-semibold">
                    Affected pages ({selectedGroup.affected_page_count})
                  </h5>
                  <table className="mt-2 w-full text-left text-xs">
                    <thead>
                      <tr className="border-b">
                        <th className="p-2">URL</th>
                        <th>Title</th>
                        <th>Status</th>
                        <th>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {selectedGroup.actions.map((a) => (
                        <tr className="border-b align-top" key={a.id}>
                          <td className="max-w-48 break-all p-2">{a.final_url || a.requested_url || "—"}</td>
                          <td className="p-2">{a.page_title || "—"}</td>
                          <td className="p-2"><StatusBadge status={a.status} /></td>
                          <td className="p-2">
                            <button
                              className="text-blue-600 underline"
                              onClick={() => void openActionDetail(a.id)}
                              type="button"
                            >
                              View
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {selectedAction && !detailLoading && (
            <div className="mt-6 rounded-xl border bg-white p-4">
              <div className="flex items-start justify-between">
                <h4 className="text-lg font-semibold">Action detail</h4>
                <button
                  className="text-sm text-slate-500 underline"
                  onClick={() => setSelectedAction(null)}
                  type="button"
                >
                  Close
                </button>
              </div>

              <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
                <div className="sm:col-span-2">
                  <dt className="text-slate-500">Issue</dt>
                  <dd className="font-semibold">{selectedAction.issue_title}</dd>
                </div>
                <div>
                  <dt className="text-slate-500">Severity</dt>
                  <dd><SeverityBadge severity={selectedAction.severity} /></dd>
                </div>
                <div>
                  <dt className="text-slate-500">Priority</dt>
                  <dd><PriorityBar score={selectedAction.priority_score} /></dd>
                </div>
                <div>
                  <dt className="text-slate-500">Confidence</dt>
                  <dd className="font-medium capitalize">{selectedAction.confidence} ({selectedAction.confidence_percent}%)</dd>
                </div>
                <div>
                  <dt className="text-slate-500">Estimated effort</dt>
                  <dd className="font-medium capitalize">{selectedAction.estimated_effort}</dd>
                </div>
                <div>
                  <dt className="text-slate-500">Status</dt>
                  <dd><StatusBadge status={selectedAction.status} /></dd>
                </div>
                <div>
                  <dt className="text-slate-500">Responsible area</dt>
                  <dd>{selectedAction.responsible_area}</dd>
                </div>
                <div>
                  <dt className="text-slate-500">Responsible role</dt>
                  <dd>{selectedAction.responsible_role}</dd>
                </div>
                <div className="sm:col-span-2">
                  <dt className="text-slate-500">Action location</dt>
                  <dd className="font-medium">{selectedAction.action_location}</dd>
                </div>
                <div className="sm:col-span-2">
                  <dt className="text-slate-500">Page URL</dt>
                  <dd className="break-all">{selectedAction.final_url || selectedAction.requested_url || "—"}</dd>
                </div>
                <div className="sm:col-span-2">
                  <dt className="text-slate-500">Business impact</dt>
                  <dd>{selectedAction.business_impact}</dd>
                </div>
              </dl>

              <div className="mt-4 space-y-4 text-sm">
                <div>
                  <h5 className="font-semibold text-slate-700">Why this matters</h5>
                  <p className="mt-1 text-slate-600">{selectedAction.why_this_matters}</p>
                </div>
                <div>
                  <h5 className="font-semibold text-slate-700">Exact correction</h5>
                  <p className="mt-1 text-slate-600">{selectedAction.exact_correction}</p>
                </div>
                <div>
                  <h5 className="font-semibold text-slate-700">Implementation steps</h5>
                  <pre className="mt-1 whitespace-pre-wrap text-slate-600">{selectedAction.implementation_steps}</pre>
                </div>
                <div>
                  <h5 className="font-semibold text-slate-700">Verification steps</h5>
                  <pre className="mt-1 whitespace-pre-wrap text-slate-600">{selectedAction.verification_steps}</pre>
                </div>
                <div>
                  <h5 className="font-semibold text-slate-700">Expected result</h5>
                  <p className="mt-1 text-slate-600">{selectedAction.expected_result}</p>
                </div>
                <div>
                  <h5 className="font-semibold text-slate-700">Limitations</h5>
                  <p className="mt-1 text-slate-600">{selectedAction.limitations}</p>
                </div>
                <div>
                  <h5 className="font-semibold text-slate-700">Source</h5>
                  <p className="mt-1 text-slate-600">{selectedAction.source_audit}</p>
                </div>
              </div>

              <div className="mt-4 flex flex-wrap gap-2">
                <span className="text-sm font-semibold text-slate-700">Update status:</span>
                {["open", "acknowledged", "in_progress", "resolved", "ignored", "reopened"]
                  .filter((s) => s !== selectedAction.status)
                  .map((s) => (
                    <button
                      className="rounded-lg border px-2 py-1 text-xs hover:bg-slate-100"
                      key={s}
                      onClick={() => void updateStatus(selectedAction.id, s)}
                      type="button"
                    >
                      {s.replace("_", " ")}
                    </button>
                  ))}
              </div>

              {selectedAction.status_history.length > 0 && (
                <div className="mt-4">
                  <h5 className="font-semibold text-slate-700">Status history</h5>
                  <table className="mt-2 w-full text-left text-xs">
                    <thead>
                      <tr className="border-b">
                        <th className="p-2">From</th>
                        <th>To</th>
                        <th>Source</th>
                        <th>Date</th>
                      </tr>
                    </thead>
                    <tbody>
                      {selectedAction.status_history.map((h) => (
                        <tr className="border-b" key={h.id}>
                          <td className="p-2"><StatusBadge status={h.previous_status || "created"} /></td>
                          <td className="p-2"><StatusBadge status={h.new_status} /></td>
                          <td className="p-2">{h.source}</td>
                          <td className="p-2 text-slate-500">{new Date(h.changed_at).toLocaleString()}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
