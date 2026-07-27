"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import { ApiError, apiRequest } from "@/lib/api";
import { agentPlatformApi } from "@/lib/agent-platform-api";
import type {
  AnalysisRun,
  RepositoryConnection,
  Website,
} from "@/lib/types";
import { DependencyGraph } from "@/components/agents/DependencyGraph";
import { SafeStructuredValue } from "@/components/agents/SafeStructuredValue";
import type {
  AgentDefinition,
  AgentEvent,
  AgentRun,
  EvidenceReference,
  ExecutionStatus,
  ToolActivity,
  ToolDefinition,
  WorkflowDefinition,
  WorkflowExecution,
} from "@/components/agents/types";

const RUN_PAGE_SIZE = 10;
const EVENT_PAGE_SIZE = 20;
const TERMINAL_STATUSES: ExecutionStatus[] = [
  "completed",
  "partial",
  "failed",
  "cancelled",
  "unavailable",
];
const STATUS_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "", label: "All statuses" },
  { value: "pending", label: "Pending" },
  { value: "running", label: "Running" },
  { value: "completed", label: "Completed" },
  { value: "partial", label: "Partial" },
  { value: "failed", label: "Failed" },
  { value: "cancelled", label: "Cancelled" },
  { value: "unavailable", label: "Unavailable" },
];

interface AgentExecutionPanelProps {
  projectId?: string;
  websiteId?: string;
  analysisRunId?: string;
  compact?: boolean;
}

function createExecutionKey(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `execution-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    const suffix = error.requestId ? ` Request ID: ${error.requestId}` : "";
    if (error.status === 404) return `Not found: ${error.message}${suffix}`;
    if (error.status === 409) return `Conflict: ${error.message}${suffix}`;
    if (error.status === 422) return `Validation error: ${error.message}${suffix}`;
    return `${error.message}${suffix}`;
  }
  return error instanceof Error ? error.message : "The request could not be completed.";
}

function StatusBadge({ status }: { status: ExecutionStatus | "not_started" }) {
  const style: Record<string, string> = {
    pending: "border-blue-300 bg-blue-50 text-blue-900",
    running: "border-amber-300 bg-amber-50 text-amber-900",
    completed: "border-emerald-300 bg-emerald-50 text-emerald-900",
    partial: "border-orange-300 bg-orange-50 text-orange-900",
    failed: "border-red-300 bg-red-50 text-red-900",
    cancelled: "border-slate-400 bg-slate-100 text-slate-800",
    unavailable: "border-violet-300 bg-violet-50 text-violet-900",
    not_started: "border-slate-300 bg-white text-slate-600",
  };
  const symbol: Record<string, string> = {
    pending: "○",
    running: "◌",
    completed: "✓",
    partial: "◐",
    failed: "!",
    cancelled: "×",
    unavailable: "?",
    not_started: "–",
  };
  return (
    <span
      aria-label={`Status: ${status.replaceAll("_", " ")}`}
      className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-semibold ${style[status]}`}
    >
      <span aria-hidden="true">{symbol[status]}</span>
      {status.replaceAll("_", " ")}
    </span>
  );
}

function newestRuns(runs: AgentRun[]): Map<string, AgentRun> {
  const result = new Map<string, AgentRun>();
  for (const run of runs) {
    const current = result.get(run.agent_id);
    if (!current || run.attempt > current.attempt) result.set(run.agent_id, run);
  }
  return result;
}

function artifactReferences(value: unknown): string[] {
  const references = new Set<string>();
  function visit(item: unknown, depth: number) {
    if (depth > 6 || item === null || item === undefined) return;
    if (Array.isArray(item)) {
      item.slice(0, 100).forEach((child) => visit(child, depth + 1));
      return;
    }
    if (typeof item !== "object") return;
    for (const [key, child] of Object.entries(item as Record<string, unknown>)) {
      const normalized = key.toLowerCase();
      if (
        typeof child === "string" &&
        (normalized.includes("artifact") ||
          normalized.includes("report_reference") ||
          normalized.includes("remediation_reference") ||
          normalized.includes("storage_reference"))
      ) {
        references.add(child);
      } else {
        visit(child, depth + 1);
      }
    }
  }
  visit(value, 0);
  return [...references].sort();
}

function ToolActivityTable({
  activities,
  tools,
}: {
  activities: Array<ToolActivity & { agent_id: string; agent_run_id: string }>;
  tools: Map<string, ToolDefinition>;
}) {
  if (activities.length === 0) {
    return (
      <p className="mt-3 text-sm text-slate-600">
        Tool activity is unavailable until an agent run starts.
      </p>
    );
  }
  return (
    <div className="mt-4 overflow-x-auto">
      <table className="min-w-[760px] table-auto text-left text-sm">
        <caption className="sr-only">
          Registered tool activity by agent, including availability and fallback states
        </caption>
        <thead>
          <tr className="border-b text-xs uppercase text-slate-500">
            <th className="p-2">Agent</th>
            <th className="p-2">Tool and version</th>
            <th className="p-2">Status</th>
            <th className="p-2">Attempts</th>
            <th className="p-2">Availability</th>
            <th className="p-2">Execution mode</th>
          </tr>
        </thead>
        <tbody>
          {activities.map((activity, index) => {
            const definition = tools.get(activity.tool_id ?? "");
            const status = activity.status ?? "unavailable";
            return (
              <tr
                className="border-b align-top"
                key={`${activity.agent_run_id}-${activity.tool_id}-${index}`}
              >
                <td className="p-2 font-mono text-xs">{activity.agent_id}</td>
                <td className="p-2">
                  <span className="font-mono">{activity.tool_id ?? "unknown tool"}</span>
                  <span className="block text-xs text-slate-500">
                    v{activity.tool_version ?? definition?.version ?? "unavailable"}
                  </span>
                </td>
                <td className="p-2">
                  <StatusBadge status={status} />
                  {activity.failure_code && (
                    <span className="mt-1 block text-xs text-red-700">
                      {String(activity.failure_code)}
                    </span>
                  )}
                </td>
                <td className="p-2">{activity.attempts ?? "Unavailable"}</td>
                <td className="p-2">
                  {definition?.availability_state ?? "unavailable"}
                </td>
                <td className="p-2">
                  {activity.deterministic_fallback
                    ? "Deterministic fallback"
                    : "Registered adapter"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function AgentExecutionPanel({
  projectId,
  websiteId,
  analysisRunId,
  compact = false,
}: AgentExecutionPanelProps) {
  const [resolvedProjectId, setResolvedProjectId] = useState(projectId ?? "");
  const [workflows, setWorkflows] = useState<WorkflowDefinition[]>([]);
  const [agents, setAgents] = useState<AgentDefinition[]>([]);
  const [tools, setTools] = useState<ToolDefinition[]>([]);
  const [repositoryConnection, setRepositoryConnection] =
    useState<RepositoryConnection | null>(null);
  const [latestCompletedAnalysisRun, setLatestCompletedAnalysisRun] =
    useState<string | null>(analysisRunId ?? null);
  const [selectedWorkflowId, setSelectedWorkflowId] =
    useState("full_website_analysis");
  const [idempotencyKey, setIdempotencyKey] = useState("");
  const [executionIdInput, setExecutionIdInput] = useState("");
  const [maxConcurrency, setMaxConcurrency] = useState(3);
  const [execution, setExecution] = useState<WorkflowExecution | null>(null);
  const [allRuns, setAllRuns] = useState<AgentRun[]>([]);
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [runTotal, setRunTotal] = useState(0);
  const [eventTotal, setEventTotal] = useState(0);
  const [runOffset, setRunOffset] = useState(0);
  const [eventOffset, setEventOffset] = useState(0);
  const [runAgentFilter, setRunAgentFilter] = useState("");
  const [runStatusFilter, setRunStatusFilter] = useState("");
  const [eventTypeFilter, setEventTypeFilter] = useState("");
  const [eventStatusFilter, setEventStatusFilter] = useState("");
  const [loadingMetadata, setLoadingMetadata] = useState(true);
  const [loadingExecution, setLoadingExecution] = useState(false);
  const [acting, setActing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const selectedWorkflow = useMemo(
    () => workflows.find((workflow) => workflow.workflow_id === selectedWorkflowId),
    [selectedWorkflowId, workflows],
  );
  const agentsById = useMemo(
    () => new Map(agents.map((agent) => [agent.agent_id, agent])),
    [agents],
  );
  const toolsById = useMemo(
    () => new Map(tools.map((tool) => [tool.tool_id, tool])),
    [tools],
  );
  const panelScope = websiteId ?? resolvedProjectId ?? "unscoped";
  const headingId = (name: string) => `${name}-${panelScope}`;
  const latestRuns = useMemo(() => newestRuns(allRuns), [allRuns]);

  const loadExecution = useCallback(
    async (executionId: string, includeExecution = true) => {
      if (!executionId) return;
      setLoadingExecution(true);
      try {
        const [loadedExecution, loadedAllRuns, loadedRuns, loadedEvents] =
          await Promise.all([
          includeExecution
            ? agentPlatformApi.getExecution(executionId)
            : Promise.resolve(null),
          agentPlatformApi.listRuns(executionId, {
            limit: 200,
            offset: 0,
          }),
          agentPlatformApi.listRuns(executionId, {
            agentId: runAgentFilter || undefined,
            status: runStatusFilter || undefined,
            limit: RUN_PAGE_SIZE,
            offset: runOffset,
          }),
          agentPlatformApi.listEvents(executionId, {
            eventType: eventTypeFilter || undefined,
            status: eventStatusFilter || undefined,
            limit: EVENT_PAGE_SIZE,
            offset: eventOffset,
          }),
          ]);
        if (loadedExecution) setExecution(loadedExecution);
        setAllRuns(loadedAllRuns.items);
        setRuns(loadedRuns.items);
        setRunTotal(loadedRuns.total);
        setEvents(loadedEvents.items);
        setEventTotal(loadedEvents.total);
        setError(null);
      } catch (requestError) {
        setError(errorMessage(requestError));
      } finally {
        setLoadingExecution(false);
      }
    },
    [
      eventOffset,
      eventStatusFilter,
      eventTypeFilter,
      runAgentFilter,
      runOffset,
      runStatusFilter,
    ],
  );

  useEffect(() => {
    let cancelled = false;
    async function loadMetadata() {
      try {
        const [loadedWorkflows, loadedAgents, loadedTools] = await Promise.all([
          agentPlatformApi.listWorkflows(),
          agentPlatformApi.listAgents(),
          agentPlatformApi.listTools(),
        ]);
        if (cancelled) return;
        setWorkflows(loadedWorkflows);
        setAgents(loadedAgents);
        setTools(loadedTools);
      } catch (requestError) {
        if (!cancelled) setError(errorMessage(requestError));
      } finally {
        if (!cancelled) setLoadingMetadata(false);
      }
    }
    void loadMetadata();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function loadScope() {
      let scopeProjectId = projectId ?? "";
      try {
        if (!scopeProjectId && websiteId) {
          const website = await apiRequest<Website>(`/api/v1/websites/${websiteId}`);
          scopeProjectId = website.project_id;
        }
        if (cancelled || !scopeProjectId) return;
        setResolvedProjectId(scopeProjectId);
        const [connections, analysisRuns] = await Promise.all([
          apiRequest<RepositoryConnection[]>(
            `/api/v1/projects/${scopeProjectId}/repository/connections`,
          ).catch(() => []),
          websiteId
            ? apiRequest<AnalysisRun[]>(
                `/api/v1/websites/${websiteId}/analysis-runs`,
              ).catch(() => [])
            : Promise.resolve([]),
        ]);
        if (cancelled) return;
        setRepositoryConnection(
          connections.find((connection) => connection.status === "active") ?? null,
        );
        if (!analysisRunId) {
          setLatestCompletedAnalysisRun(
            analysisRuns.find((run) => run.status === "completed")?.id ?? null,
          );
        }
        const storageKey = `agent-execution:${scopeProjectId}:${websiteId ?? "project"}`;
        const retainedExecutionId = window.localStorage.getItem(storageKey);
        if (retainedExecutionId) {
          setExecutionIdInput(retainedExecutionId);
          void loadExecution(retainedExecutionId);
        }
      } catch (requestError) {
        if (!cancelled) setError(errorMessage(requestError));
      }
    }
    void loadScope();
    return () => {
      cancelled = true;
    };
  }, [analysisRunId, loadExecution, projectId, websiteId]);

  useEffect(() => {
    if (!execution || !["pending", "running"].includes(execution.status)) return;
    const timer = window.setInterval(() => {
      void loadExecution(execution.execution_id);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [execution, loadExecution]);

  useEffect(() => {
    if (!execution) return;
    const timer = window.setTimeout(() => {
      void loadExecution(execution.execution_id, false);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [
    eventOffset,
    eventStatusFilter,
    eventTypeFilter,
    execution,
    loadExecution,
    runAgentFilter,
    runOffset,
    runStatusFilter,
  ]);

  async function startExecution(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedWorkflow || !resolvedProjectId) {
      setError("Select a registered workflow and a valid project scope.");
      return;
    }
    if (
      selectedWorkflow.workflow_id === "repository_remediation" &&
      !repositoryConnection
    ) {
      setError(
        "Repository remediation is unavailable until an approved repository connection exists.",
      );
      return;
    }
    setActing(true);
    setError(null);
    setNotice(null);
    try {
      const requestedIdempotencyKey =
        idempotencyKey.trim() || createExecutionKey();
      setIdempotencyKey(requestedIdempotencyKey);
      const started = await agentPlatformApi.startExecution({
        workflow_id: selectedWorkflow.workflow_id,
        project_id: resolvedProjectId,
        website_id: websiteId ?? null,
        analysis_run_id: analysisRunId ?? latestCompletedAnalysisRun,
        repository_connection_id: repositoryConnection?.id ?? null,
        idempotency_key: requestedIdempotencyKey,
        max_concurrency: maxConcurrency,
      });
      setExecution(started);
      setExecutionIdInput(started.execution_id);
      const storageKey = `agent-execution:${resolvedProjectId}:${websiteId ?? "project"}`;
      window.localStorage.setItem(storageKey, started.execution_id);
      setNotice(
        `Workflow ${started.workflow_id} accepted with execution ID ${started.execution_id}.`,
      );
      await loadExecution(started.execution_id);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setActing(false);
    }
  }

  async function loadById(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setNotice(null);
    await loadExecution(executionIdInput.trim());
  }

  async function performExecutionAction(
    action: "cancel" | "resume",
  ) {
    if (!execution) return;
    setActing(true);
    setError(null);
    try {
      const updated =
        action === "cancel"
          ? await agentPlatformApi.cancelExecution(execution.execution_id)
          : await agentPlatformApi.resumeExecution(execution.execution_id);
      setExecution(updated);
      setNotice(
        action === "cancel"
          ? "Cancellation was recorded. Successful completed runs remain preserved."
          : "Execution resumed from the latest valid checkpoint.",
      );
      await loadExecution(updated.execution_id);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setActing(false);
    }
  }

  async function retryRun(run: AgentRun) {
    setActing(true);
    setError(null);
    try {
      const updated = await agentPlatformApi.retryRun(run.agent_run_id);
      setExecution(updated);
      setNotice(`Retry requested for ${run.agent_id}, attempt ${run.attempt + 1}.`);
      await loadExecution(updated.execution_id);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setActing(false);
    }
  }

  const activeNodeCount = selectedWorkflow
    ? selectedWorkflow.nodes.filter(
        (node) =>
          node.condition !== "repository_configured" || Boolean(repositoryConnection),
      ).length
    : 0;
  const terminalRunCount = [...latestRuns.values()].filter((run) =>
    TERMINAL_STATUSES.includes(run.status),
  ).length;
  const progress =
    activeNodeCount > 0
      ? Math.min(100, Math.round((terminalRunCount / activeNodeCount) * 100))
      : 0;
  const activities = allRuns.flatMap((run) =>
    run.tool_activity_summary.map((activity) => ({
      ...activity,
      agent_id: run.agent_id,
      agent_run_id: run.agent_run_id,
    })),
  );
  const evidence = new Map<string, EvidenceReference>();
  for (const reference of [
    ...(execution?.evidence_references ?? []),
    ...allRuns.flatMap((run) => run.evidence_references),
    ...events.flatMap((event) => event.evidence_references),
  ]) {
    evidence.set(JSON.stringify(reference), reference);
  }
  const artifacts = artifactReferences([
    execution?.structured_output,
    ...allRuns.map((run) => run.structured_output),
  ]);
  const completedRuns = [...latestRuns.values()].filter(
    (run) => run.status === "completed",
  );
  const latestCheckpointAgent =
    completedRuns.sort((left, right) =>
      (right.completed_at ?? "").localeCompare(left.completed_at ?? ""),
    )[0]?.agent_id ?? null;
  const resumeCheckpoint =
    execution?.provider_version_metadata.resume_checkpoint_id ?? null;

  return (
    <section
      aria-labelledby={headingId("agent-execution-heading")}
      className={`scroll-mt-6 rounded-2xl border border-slate-200 bg-white shadow-sm ${
        compact ? "mt-6 p-5" : "mt-8 p-6"
      }`}
      id={`agent-execution-${panelScope}`}
    >
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-bold uppercase tracking-wide text-indigo-700">
            Deterministic orchestration
          </p>
          <h2
            className="mt-1 text-2xl font-bold"
            id={headingId("agent-execution-heading")}
          >
            Agent Execution
          </h2>
          <p className="mt-2 max-w-3xl text-sm text-slate-600">
            Registered agents coordinate existing deterministic analysis capabilities.
            The interface shows structured decisions and evidence references only.
          </p>
        </div>
        <StatusBadge status={execution?.status ?? "not_started"} />
      </header>

      {loadingMetadata && (
        <p className="mt-5 text-sm text-slate-600" role="status">
          Loading registered workflows, agents, and tools…
        </p>
      )}
      {error && (
        <div
          aria-live="assertive"
          className="mt-4 rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-800"
          role="alert"
        >
          {error}
        </div>
      )}
      {notice && (
        <p
          aria-live="polite"
          className="mt-4 rounded-lg border border-emerald-300 bg-emerald-50 p-3 text-sm text-emerald-900"
          role="status"
        >
          {notice}
        </p>
      )}

      <section
        aria-labelledby={headingId("workflow-overview-heading")}
        className="mt-6"
      >
        <h3
          className="text-lg font-semibold"
          id={headingId("workflow-overview-heading")}
        >
          Workflow Overview
        </h3>
        {workflows.length === 0 && !loadingMetadata ? (
          <p className="mt-3 text-sm text-slate-600">
            No registered workflow metadata is available. This does not mean analysis
            completed without issues.
          </p>
        ) : (
          <form className="mt-4 grid gap-4" onSubmit={startExecution}>
            <div className="grid gap-4 md:grid-cols-3">
              <label className="grid gap-1.5 text-sm font-medium">
                Registered workflow
                <select
                  aria-label="Select registered workflow"
                  className="rounded-lg border border-slate-300 px-3 py-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-700"
                  onChange={(event) => setSelectedWorkflowId(event.target.value)}
                  value={selectedWorkflowId}
                >
                  {workflows.map((workflow) => (
                    <option key={workflow.workflow_id} value={workflow.workflow_id}>
                      {workflow.name} — v{workflow.version}
                    </option>
                  ))}
                </select>
              </label>
              <label className="grid gap-1.5 text-sm font-medium">
                Maximum parallel agents
                <input
                  aria-label="Maximum parallel agents"
                  className="rounded-lg border border-slate-300 px-3 py-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-700"
                  max={8}
                  min={1}
                  onChange={(event) => setMaxConcurrency(Number(event.target.value))}
                  type="number"
                  value={maxConcurrency}
                />
              </label>
              <label className="grid gap-1.5 text-sm font-medium">
                Idempotency key
                <span className="flex gap-2">
                  <input
                    aria-label="Workflow idempotency key"
                    className="min-w-0 flex-1 rounded-lg border border-slate-300 px-3 py-2 font-mono text-xs focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-700"
                    onChange={(event) => setIdempotencyKey(event.target.value)}
                    placeholder="Generated when left blank"
                    value={idempotencyKey}
                  />
                  <button
                    aria-label="Generate a new execution idempotency key"
                    className="rounded-lg border px-3 py-2 text-xs font-semibold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-700"
                    onClick={() => setIdempotencyKey(createExecutionKey())}
                    type="button"
                  >
                    New key
                  </button>
                </span>
              </label>
            </div>
            {selectedWorkflow && (
              <div className="rounded-xl bg-slate-50 p-4 text-sm">
                <p>
                  <strong>{selectedWorkflow.name}</strong> · Workflow version{" "}
                  {selectedWorkflow.version} · Orchestrator{" "}
                  {selectedWorkflow.orchestrator_id} v
                  {selectedWorkflow.orchestrator_version}
                </p>
                <p className="mt-1 text-slate-600">{selectedWorkflow.purpose}</p>
                <p className="mt-2 text-xs text-slate-500">
                  {selectedWorkflow.limitations}
                </p>
              </div>
            )}
            <div className="flex flex-wrap items-center gap-3">
              <button
                aria-label="Start selected deterministic workflow"
                className="rounded-lg bg-indigo-800 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-700"
                disabled={
                  acting ||
                  loadingMetadata ||
                  !resolvedProjectId
                }
                type="submit"
              >
                {acting ? "Submitting…" : "Start workflow"}
              </button>
              <span className="text-xs text-slate-500">
                Analysis evidence:{" "}
                {analysisRunId ?? latestCompletedAnalysisRun ?? "unavailable"}
              </span>
              <span className="text-xs text-slate-500">
                Repository stage:{" "}
                {repositoryConnection ? "configured" : "conditional and unavailable"}
              </span>
            </div>
          </form>
        )}
        <form className="mt-4 flex flex-wrap gap-2" onSubmit={loadById}>
          <label className="sr-only" htmlFor={`execution-id-${panelScope}`}>
            Existing workflow execution ID
          </label>
          <input
            className="min-w-64 flex-1 rounded-lg border border-slate-300 px-3 py-2 font-mono text-xs focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-700"
            id={`execution-id-${panelScope}`}
            onChange={(event) => setExecutionIdInput(event.target.value)}
            placeholder="Load an existing execution UUID"
            value={executionIdInput}
          />
          <button
            className="rounded-lg border px-4 py-2 text-sm font-semibold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-700"
            disabled={!executionIdInput.trim() || loadingExecution}
            type="submit"
          >
            {loadingExecution ? "Loading…" : "Load execution"}
          </button>
        </form>
      </section>

      {selectedWorkflow && (
        <div className="mt-8 border-t border-slate-200 pt-6">
          <DependencyGraph
            repositoryConfigured={Boolean(repositoryConnection)}
            runs={allRuns}
            workflow={selectedWorkflow}
          />
        </div>
      )}

      {!execution && !loadingExecution && (
        <div className="mt-8 rounded-xl border border-dashed border-slate-300 p-6 text-center">
          <p className="font-semibold">No execution selected</p>
          <p className="mt-2 text-sm text-slate-600">
            Start a workflow or load a retained execution ID. An empty state does not
            indicate that all evidence is available or that no issues exist.
          </p>
        </div>
      )}

      {execution && (
        <>
          <section
            aria-labelledby={headingId("execution-progress-heading")}
            className="mt-8 border-t pt-6"
          >
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3
                  className="text-lg font-semibold"
                  id={headingId("execution-progress-heading")}
                >
                  Execution Progress
                </h3>
                <p className="mt-1 break-all font-mono text-xs text-slate-500">
                  {execution.execution_id}
                </p>
              </div>
              <StatusBadge status={execution.status} />
            </div>
            <div
              aria-label={`Workflow progress ${progress}%`}
              aria-valuemax={100}
              aria-valuemin={0}
              aria-valuenow={progress}
              className="mt-4 h-3 overflow-hidden rounded-full bg-slate-200"
              role="progressbar"
            >
              <div
                className="h-full bg-indigo-700 transition-[width]"
                style={{ width: `${progress}%` }}
              />
            </div>
            <p className="mt-2 text-sm">
              {terminalRunCount} of {activeNodeCount} active agents reached a terminal
              state ({progress}%).
            </p>
            <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
              <div>
                <dt className="text-slate-500">Pinned workflow</dt>
                <dd className="font-mono">
                  {execution.workflow_id} v{execution.workflow_version}
                </dd>
              </div>
              <div>
                <dt className="text-slate-500">Execution attempt</dt>
                <dd>{execution.attempt}</dd>
              </div>
              <div>
                <dt className="text-slate-500">Input fingerprint</dt>
                <dd className="truncate font-mono text-xs">{execution.input_fingerprint}</dd>
              </div>
              <div>
                <dt className="text-slate-500">Completed</dt>
                <dd>
                  {execution.completed_at
                    ? new Date(execution.completed_at).toLocaleString()
                    : "Not completed"}
                </dd>
              </div>
            </dl>
            <div className="mt-4 flex flex-wrap gap-2">
              {["pending", "running"].includes(execution.status) && (
                <button
                  aria-label="Cancel workflow execution"
                  className="rounded-lg border border-red-300 px-4 py-2 text-sm font-semibold text-red-800 disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-700"
                  disabled={acting}
                  onClick={() => void performExecutionAction("cancel")}
                  type="button"
                >
                  Cancel execution
                </button>
              )}
              {["failed", "cancelled", "partial", "unavailable"].includes(
                execution.status,
              ) && (
                <button
                  aria-label="Resume workflow from latest valid checkpoint"
                  className="rounded-lg bg-indigo-800 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-700"
                  disabled={acting}
                  onClick={() => void performExecutionAction("resume")}
                  type="button"
                >
                  Resume from checkpoint
                </button>
              )}
              <button
                aria-label="Refresh workflow execution"
                className="rounded-lg border px-4 py-2 text-sm font-semibold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-700"
                onClick={() => void loadExecution(execution.execution_id)}
                type="button"
              >
                Refresh
              </button>
            </div>
          </section>

          <section
            aria-labelledby={headingId("checkpoint-heading")}
            className="mt-8 border-t pt-6"
          >
            <h3
              className="text-lg font-semibold"
              id={headingId("checkpoint-heading")}
            >
              Retry, Resume, and Checkpoint State
            </h3>
            <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-3">
              <div className="rounded-lg bg-slate-50 p-3">
                <dt className="text-slate-500">Completed-agent checkpoints</dt>
                <dd className="mt-1 text-xl font-bold">{completedRuns.length}</dd>
              </div>
              <div className="rounded-lg bg-slate-50 p-3">
                <dt className="text-slate-500">Latest completed agent</dt>
                <dd className="mt-1 font-mono">
                  {latestCheckpointAgent ?? "Unavailable"}
                </dd>
              </div>
              <div className="rounded-lg bg-slate-50 p-3">
                <dt className="text-slate-500">Resume checkpoint reference</dt>
                <dd className="mt-1 break-all font-mono text-xs">
                  {typeof resumeCheckpoint === "string"
                    ? resumeCheckpoint
                    : "No resume has been requested"}
                </dd>
              </div>
            </dl>
            <p className="mt-3 text-sm text-slate-600">
              Completed runs remain immutable. Resume reuses only checkpoints matching
              the execution input fingerprint; failed or partial work is retried within
              registered limits.
            </p>
          </section>

          <section
            aria-labelledby={headingId("agent-runs-heading")}
            className="mt-8 border-t pt-6"
          >
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <h3
                  className="text-lg font-semibold"
                  id={headingId("agent-runs-heading")}
                >
                  Agent Runs
                </h3>
                <p className="mt-1 text-sm text-slate-600">
                  Pinned agent versions, attempts, retry limits, timeouts, and concise
                  structured decisions.
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <label className="grid gap-1 text-xs font-semibold">
                  Agent
                  <select
                    aria-label="Filter agent runs by agent"
                    className="rounded-lg border px-2 py-1.5"
                    onChange={(event) => {
                      setRunAgentFilter(event.target.value);
                      setRunOffset(0);
                    }}
                    value={runAgentFilter}
                  >
                    <option value="">All agents</option>
                    {agents.map((agent) => (
                      <option key={agent.agent_id} value={agent.agent_id}>
                        {agent.agent_id}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="grid gap-1 text-xs font-semibold">
                  Status
                  <select
                    aria-label="Filter agent runs by status"
                    className="rounded-lg border px-2 py-1.5"
                    onChange={(event) => {
                      setRunStatusFilter(event.target.value);
                      setRunOffset(0);
                    }}
                    value={runStatusFilter}
                  >
                    {STATUS_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            </div>
            {runs.length === 0 ? (
              <p className="mt-4 text-sm text-slate-600">
                No agent runs match the current filters.
              </p>
            ) : (
              <ul className="mt-4 grid gap-4">
                {runs.map((run) => {
                  const definition = agentsById.get(run.agent_id);
                  return (
                    <li className="rounded-xl border border-slate-200 p-4" key={run.agent_run_id}>
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <h4 className="font-mono font-semibold">{run.agent_id}</h4>
                          <p className="mt-1 text-xs text-slate-500">
                            Agent v{run.agent_version} · Attempt {run.attempt} of{" "}
                            {definition?.retry_policy.max_attempts ?? "unavailable"} · Timeout{" "}
                            {definition?.timeout_seconds ?? "unavailable"} seconds
                          </p>
                        </div>
                        <StatusBadge status={run.status} />
                      </div>
                      {run.status === "failed" && run.failure_details.transient === true && (
                        <button
                          aria-label={`Retry failed agent ${run.agent_id}`}
                          className="mt-3 rounded-lg border border-amber-400 px-3 py-1.5 text-sm font-semibold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-amber-700"
                          disabled={
                            acting ||
                            run.attempt >= (definition?.retry_policy.max_attempts ?? 0)
                          }
                          onClick={() => void retryRun(run)}
                          type="button"
                        >
                          Retry failed agent
                        </button>
                      )}
                      <details className="mt-3">
                        <summary className="cursor-pointer text-sm font-semibold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-700">
                          Structured decisions and limitations
                        </summary>
                        <div className="mt-3">
                          <SafeStructuredValue value={run.structured_output} />
                        </div>
                        {Object.keys(run.partial_completion_details).length > 0 && (
                          <div className="mt-3">
                            <h5 className="text-sm font-semibold">Partial completion</h5>
                            <SafeStructuredValue value={run.partial_completion_details} />
                          </div>
                        )}
                      </details>
                    </li>
                  );
                })}
              </ul>
            )}
            <div className="mt-4 flex items-center justify-between text-sm">
              <button
                className="rounded-lg border px-3 py-1.5 disabled:opacity-40"
                disabled={runOffset === 0}
                onClick={() => setRunOffset(Math.max(0, runOffset - RUN_PAGE_SIZE))}
                type="button"
              >
                Previous runs
              </button>
              <span>
                {runTotal === 0 ? 0 : runOffset + 1}–
                {Math.min(runOffset + RUN_PAGE_SIZE, runTotal)} of {runTotal}
              </span>
              <button
                className="rounded-lg border px-3 py-1.5 disabled:opacity-40"
                disabled={runOffset + RUN_PAGE_SIZE >= runTotal}
                onClick={() => setRunOffset(runOffset + RUN_PAGE_SIZE)}
                type="button"
              >
                Next runs
              </button>
            </div>
          </section>

          <section
            aria-labelledby={headingId("tool-activity-heading")}
            className="mt-8 border-t pt-6"
          >
            <h3
              className="text-lg font-semibold"
              id={headingId("tool-activity-heading")}
            >
              Tool Activity
            </h3>
            <p className="mt-1 text-sm text-slate-600">
              Only tools allowed by the pinned agent contract may run. Unavailable
              providers and deterministic fallback modes remain explicit.
            </p>
            <ToolActivityTable activities={activities} tools={toolsById} />
          </section>

          <section
            aria-labelledby={headingId("events-heading")}
            className="mt-8 border-t pt-6"
          >
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <h3
                  className="text-lg font-semibold"
                  id={headingId("events-heading")}
                >
                  Events Timeline
                </h3>
                <p className="mt-1 text-sm text-slate-600">
                  Deterministic status events in persisted sequence order.
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <label className="grid gap-1 text-xs font-semibold">
                  Event type
                  <input
                    aria-label="Filter events by event type"
                    className="rounded-lg border px-2 py-1.5"
                    onChange={(event) => {
                      setEventTypeFilter(event.target.value);
                      setEventOffset(0);
                    }}
                    placeholder="agent_completed"
                    value={eventTypeFilter}
                  />
                </label>
                <label className="grid gap-1 text-xs font-semibold">
                  Status
                  <select
                    aria-label="Filter events by status"
                    className="rounded-lg border px-2 py-1.5"
                    onChange={(event) => {
                      setEventStatusFilter(event.target.value);
                      setEventOffset(0);
                    }}
                    value={eventStatusFilter}
                  >
                    {STATUS_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            </div>
            {events.length === 0 ? (
              <p className="mt-4 text-sm text-slate-600">
                No events match the current filters.
              </p>
            ) : (
              <ol className="mt-4 border-l-2 border-slate-300 pl-5">
                {events.map((event) => (
                  <li className="relative pb-5" key={event.event_id}>
                    <span
                      aria-hidden="true"
                      className="absolute -left-[1.7rem] top-1 h-3 w-3 rounded-full border-2 border-white bg-indigo-700"
                    />
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-xs">
                        #{event.sequence_number} {event.event_type}
                      </span>
                      <StatusBadge status={event.status} />
                    </div>
                    <p className="mt-1 text-xs text-slate-500">
                      {new Date(event.created_at).toLocaleString()}
                    </p>
                    <details className="mt-2">
                      <summary className="cursor-pointer text-xs font-semibold">
                        Event details
                      </summary>
                      <div className="mt-2">
                        <SafeStructuredValue value={event.structured_payload} />
                      </div>
                    </details>
                  </li>
                ))}
              </ol>
            )}
            <div className="mt-2 flex items-center justify-between text-sm">
              <button
                className="rounded-lg border px-3 py-1.5 disabled:opacity-40"
                disabled={eventOffset === 0}
                onClick={() =>
                  setEventOffset(Math.max(0, eventOffset - EVENT_PAGE_SIZE))
                }
                type="button"
              >
                Previous events
              </button>
              <span>
                {eventTotal === 0 ? 0 : eventOffset + 1}–
                {Math.min(eventOffset + EVENT_PAGE_SIZE, eventTotal)} of {eventTotal}
              </span>
              <button
                className="rounded-lg border px-3 py-1.5 disabled:opacity-40"
                disabled={eventOffset + EVENT_PAGE_SIZE >= eventTotal}
                onClick={() => setEventOffset(eventOffset + EVENT_PAGE_SIZE)}
                type="button"
              >
                Next events
              </button>
            </div>
          </section>

          <section
            aria-labelledby={headingId("evidence-heading")}
            className="mt-8 border-t pt-6"
          >
            <h3
              className="text-lg font-semibold"
              id={headingId("evidence-heading")}
            >
              Evidence and Artifacts
            </h3>
            <p className="mt-1 text-sm text-slate-600">
              References point to retained evidence; raw reports and secrets are not
              copied into this view.
            </p>
            <div className="mt-4 grid gap-5 lg:grid-cols-2">
              <div>
                <h4 className="font-semibold">Evidence references</h4>
                {evidence.size === 0 ? (
                  <p className="mt-2 text-sm text-slate-600">
                    Evidence references are unavailable for this execution state.
                  </p>
                ) : (
                  <ul className="mt-2 grid gap-2">
                    {[...evidence.values()].map((reference, index) => (
                      <li className="rounded-lg bg-slate-50 p-3" key={index}>
                        <SafeStructuredValue value={reference} />
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <div>
                <h4 className="font-semibold">Artifact references</h4>
                {artifacts.length === 0 ? (
                  <p className="mt-2 text-sm text-slate-600">
                    No artifact storage reference is exposed by the current execution
                    response. Structured outputs remain retained with each agent run.
                  </p>
                ) : (
                  <ul className="mt-2 grid gap-2">
                    {artifacts.map((reference) => (
                      <li
                        className="break-all rounded-lg bg-slate-50 p-3 font-mono text-xs"
                        key={reference}
                      >
                        {reference}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          </section>

          <section
            aria-labelledby={headingId("usage-heading")}
            className="mt-8 border-t pt-6"
          >
            <h3
              className="text-lg font-semibold"
              id={headingId("usage-heading")}
            >
              Cost and Token Usage
            </h3>
            <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
              <div className="rounded-lg bg-slate-50 p-3">
                <dt className="text-slate-500">Tokens</dt>
                <dd className="mt-1 text-xl font-bold">
                  {execution.token_total > 0
                    ? execution.token_total.toLocaleString()
                    : "Not used or unavailable"}
                </dd>
              </div>
              <div className="rounded-lg bg-slate-50 p-3">
                <dt className="text-slate-500">Provider cost</dt>
                <dd className="mt-1 text-xl font-bold">
                  {execution.cost_total_usd > 0
                    ? `$${execution.cost_total_usd.toFixed(4)} USD`
                    : "Not used or unavailable"}
                </dd>
              </div>
            </dl>
            <p className="mt-3 text-xs text-slate-500">
              Deterministic tools do not fabricate token or provider-cost values. A
              disabled approved provider uses the registered deterministic fallback.
            </p>
          </section>
        </>
      )}
    </section>
  );
}
