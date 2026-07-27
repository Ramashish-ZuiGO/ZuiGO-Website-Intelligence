export type DeliveryStatus =
  | "pending"
  | "running"
  | "completed"
  | "partial"
  | "failed"
  | "cancelled"
  | "unavailable";

export interface AnalysisJourneyStart {
  analysis_run_id: string;
  workflow_execution_id: string;
  analysis_status: string;
  workflow_status: string;
  reused: boolean;
}

export interface EvidenceCoverage {
  status: "available" | "partial" | "unavailable";
  numerator: number;
  denominator: number;
  percentage: number | null;
}

export interface WorkflowProgress {
  execution_id: string;
  analysis_run_id: string | null;
  status: DeliveryStatus;
  current_stage: string;
  completed_agent_ids: string[];
  partial_agent_ids: string[];
  pending_agent_ids: string[];
  failed_agent_ids: string[];
  unavailable_agent_ids: string[];
  progress_percentage: number;
  evidence_coverage: EvidenceCoverage;
  attempt: number;
  retry_available: boolean;
  resume_available: boolean;
  started_at: string;
  completed_at: string | null;
  elapsed_seconds: number;
  unavailable_tools: string[];
  unavailable_providers: string[];
  safe_error_summaries: Array<{ code: string; message: string }>;
}

export interface ReportSection {
  section_id: string;
  section_key: string;
  position: number;
  title: string;
  status: "passed" | "failed" | "available" | "unavailable" | "incomplete" | "excluded";
  content: Record<string, unknown>;
  evidence_references: Array<Record<string, unknown>>;
  unavailable_reason: string | null;
}

export interface ReportArtifact {
  artifact_id: string;
  format: "html" | "pdf" | "json";
  media_type: string;
  filename: string;
  size_bytes: number;
  checksum_sha256: string;
  created_at: string;
}

export interface DeliveredReport {
  report_id: string;
  project_id: string;
  website_id: string;
  analysis_run_id: string;
  workflow_execution_id: string | null;
  score_execution_id: string | null;
  report_type: string;
  report_version: string;
  template_id: string;
  template_version: string;
  input_fingerprint: string;
  idempotency_key: string;
  status: "pending" | "running" | "completed" | "partial" | "failed" | "unavailable";
  evidence_coverage_numerator: number;
  evidence_coverage_denominator: number;
  evidence_coverage_percentage: number | null;
  confidence_percent: number | null;
  unavailable_sections: string[];
  provider_version_metadata: Record<string, unknown>;
  failure_details: Record<string, unknown>;
  partial_completion_details: Record<string, unknown>;
  started_at: string;
  completed_at: string | null;
  created_at: string;
  sections: ReportSection[];
  artifacts: ReportArtifact[];
}

export interface PaginatedReports {
  items: DeliveredReport[];
  total: number;
  limit: number;
  offset: number;
}
