import { apiRequest } from "@/lib/api";
import type {
  AgentDefinition,
  PaginatedAgentEvents,
  PaginatedAgentRuns,
  StartWorkflowExecution,
  ToolDefinition,
  WorkflowDefinition,
  WorkflowExecution,
} from "@/components/agents/types";

function queryString(values: Record<string, string | number | undefined>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined && value !== "") params.set(key, String(value));
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}

export const agentPlatformApi = {
  listAgents: () => apiRequest<AgentDefinition[]>("/api/v1/agents"),
  getAgent: (agentId: string) =>
    apiRequest<AgentDefinition>(`/api/v1/agents/${encodeURIComponent(agentId)}`),
  listTools: () => apiRequest<ToolDefinition[]>("/api/v1/tools"),
  getTool: (toolId: string) =>
    apiRequest<ToolDefinition>(`/api/v1/tools/${encodeURIComponent(toolId)}`),
  listWorkflows: () => apiRequest<WorkflowDefinition[]>("/api/v1/workflows"),
  getWorkflow: (workflowId: string) =>
    apiRequest<WorkflowDefinition>(
      `/api/v1/workflows/${encodeURIComponent(workflowId)}`,
    ),
  startExecution: (payload: StartWorkflowExecution) =>
    apiRequest<WorkflowExecution>("/api/v1/workflow-executions", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getExecution: (executionId: string) =>
    apiRequest<WorkflowExecution>(
      `/api/v1/workflow-executions/${encodeURIComponent(executionId)}`,
    ),
  listRuns: (
    executionId: string,
    filters: {
      agentId?: string;
      status?: string;
      limit?: number;
      offset?: number;
    } = {},
  ) =>
    apiRequest<PaginatedAgentRuns>(
      `/api/v1/workflow-executions/${encodeURIComponent(executionId)}/runs${queryString({
        agent_id: filters.agentId,
        status: filters.status,
        limit: filters.limit,
        offset: filters.offset,
      })}`,
    ),
  listEvents: (
    executionId: string,
    filters: {
      eventType?: string;
      status?: string;
      limit?: number;
      offset?: number;
    } = {},
  ) =>
    apiRequest<PaginatedAgentEvents>(
      `/api/v1/workflow-executions/${encodeURIComponent(executionId)}/events${queryString({
        event_type: filters.eventType,
        status: filters.status,
        limit: filters.limit,
        offset: filters.offset,
      })}`,
    ),
  cancelExecution: (executionId: string) =>
    apiRequest<WorkflowExecution>(
      `/api/v1/workflow-executions/${encodeURIComponent(executionId)}/cancel`,
      { method: "POST" },
    ),
  resumeExecution: (executionId: string) =>
    apiRequest<WorkflowExecution>(
      `/api/v1/workflow-executions/${encodeURIComponent(executionId)}/resume`,
      { method: "POST" },
    ),
  retryRun: (runId: string) =>
    apiRequest<WorkflowExecution>(
      `/api/v1/agent-runs/${encodeURIComponent(runId)}/retry`,
      { method: "POST" },
    ),
};
