export type ExecutionStatus =
  | "pending"
  | "running"
  | "completed"
  | "partial"
  | "failed"
  | "cancelled"
  | "unavailable";

export interface RetryPolicy {
  max_attempts: number;
  backoff_seconds: number;
  retryable_failures: string[];
}

export interface CostTokenBudget {
  max_tokens: number | null;
  max_cost_usd: number | null;
}

export interface AgentDefinition {
  agent_id: string;
  version: string;
  name: string;
  purpose: string;
  supported_goals: string[];
  input_schema_ref: string;
  output_schema_ref: string;
  allowed_tool_ids: string[];
  dependency_agent_ids: string[];
  timeout_seconds: number;
  retry_policy: RetryPolicy;
  idempotency_requirement: string;
  memory_policy: string;
  llm_policy: string;
  permissions: string[];
  cost_token_budget: CostTokenBudget | null;
  partial_failure_behavior: string;
  limitations: string;
}

export interface ToolDefinition {
  tool_id: string;
  version: string;
  input_schema_ref: string;
  output_schema_ref: string;
  permissions: string[];
  timeout_seconds: number;
  retry_policy: RetryPolicy;
  side_effect_classification: string;
  idempotency_behavior: string;
  evidence_produced: string[];
  secret_handling_policy: string;
  availability_state: "available" | "conditional" | "unavailable";
  limitations: string;
}

export interface WorkflowNodeDefinition {
  agent_id: string;
  depends_on: string[];
  optional_dependencies: string[];
  condition: "always" | "repository_configured";
}

export interface WorkflowDefinition {
  workflow_id: string;
  version: string;
  name: string;
  purpose: string;
  orchestrator_id: string;
  orchestrator_version: string;
  deterministic: boolean;
  nodes: WorkflowNodeDefinition[];
  entry_agent_ids: string[];
  terminal_agent_ids: string[];
  deterministic_order: string[];
  limitations: string;
}

export interface EvidenceReference {
  evidence_type?: string;
  evidence_id?: string;
  source?: string;
  [key: string]: unknown;
}

export interface WorkflowExecution {
  execution_id: string;
  workflow_id: string;
  workflow_version: string;
  project_id: string;
  analysis_run_id: string | null;
  input_fingerprint: string;
  idempotency_key: string;
  status: ExecutionStatus;
  attempt: number;
  structured_input: Record<string, unknown>;
  structured_output: Record<string, unknown>;
  evidence_references: EvidenceReference[];
  provider_version_metadata: Record<string, unknown>;
  token_total: number;
  cost_total_usd: number;
  failure_details: Record<string, unknown>;
  partial_completion_details: Record<string, unknown>;
  started_at: string;
  completed_at: string | null;
  created_at: string;
}

export interface AgentRun {
  agent_run_id: string;
  execution_id: string;
  agent_id: string;
  agent_version: string;
  dependency_agent_run_ids: string[];
  input_fingerprint: string;
  idempotency_key: string;
  status: ExecutionStatus;
  attempt: number;
  structured_input: Record<string, unknown>;
  structured_output: Record<string, unknown>;
  tool_activity_summary: ToolActivity[];
  evidence_references: EvidenceReference[];
  provider_version_metadata: Record<string, unknown>;
  token_total: number;
  cost_total_usd: number;
  failure_details: Record<string, unknown>;
  partial_completion_details: Record<string, unknown>;
  started_at: string;
  completed_at: string | null;
  created_at: string;
}

export interface ToolActivity {
  tool_id?: string;
  tool_version?: string;
  status?: ExecutionStatus;
  attempts?: number;
  side_effect_classification?: string;
  deterministic_fallback?: boolean;
  failure_code?: string | null;
  [key: string]: unknown;
}

export interface AgentEvent {
  event_id: string;
  execution_id: string;
  agent_run_id: string | null;
  agent_step_id: string | null;
  event_type: string;
  sequence_number: number;
  status: ExecutionStatus;
  structured_payload: Record<string, unknown>;
  evidence_references: EvidenceReference[];
  created_at: string;
}

export interface PaginatedAgentRuns {
  items: AgentRun[];
  total: number;
  limit: number;
  offset: number;
}

export interface PaginatedAgentEvents {
  items: AgentEvent[];
  total: number;
  limit: number;
  offset: number;
}

export interface StartWorkflowExecution {
  workflow_id: string;
  project_id: string;
  analysis_run_id?: string | null;
  website_id?: string | null;
  repository_connection_id?: string | null;
  page_analysis_execution_id?: string | null;
  evidence_references?: string[];
  idempotency_key: string;
  max_concurrency: number;
}
