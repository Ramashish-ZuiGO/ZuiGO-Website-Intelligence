export type DeliveryStatus =
  | "pending"
  | "queued"
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

export interface RealWebsiteAnalysisStart {
  project_id: string;
  website_id: string;
  analysis_run_id: string;
  discovery_run_id: string;
  page_analysis_execution_id: string;
  workflow_execution_id: string;
  submitted_url: string;
  normalized_url: string;
  analysis_status: string;
  workflow_status: string;
  reused: boolean;
}

export interface RecentRealAnalysis {
  project_id: string;
  website_id: string;
  analysis_run_id: string;
  workflow_execution_id: string;
  submitted_url: string;
  normalized_url: string;
  status: string;
  created_at: string;
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
  submitted_website: string | null;
  page_coverage: {
    discovery_status: string;
    discovery_completeness: "complete" | "partial" | "failed" | "inconclusive";
    discovery_failure_code: string | null;
    discovery_failure_message: string | null;
    discovery_retry_available: boolean;
    discovered_pages: number;
    normalized_pages: number;
    eligible_pages: number;
    scheduled_pages: number;
    not_scheduled_pages: number;
    visited_pages: number;
    successfully_analysed_pages: number;
    failed_pages: number;
    failed_page_details: Array<{
      url: string;
      reason: string;
      reason_code: string;
    }>;
    document_assets: number;
    media_static_assets: number;
    resource_inventory: Array<{
      url: string;
      final_url: string | null;
      http_status: number | null;
      response_content_type: string | null;
      detected_content_type: string | null;
      content_type_detection: string;
      classification: string;
      classification_basis: string;
      failure_stage: string;
      failure_reason: string | null;
      browser_navigation: string;
    }>;
    skipped_pages: number;
    incomplete_pages: number;
    coverage_numerator: number;
    coverage_denominator: number;
    coverage_percentage: number | null;
    analysed_page_coverage_percentage: number | null;
    full_site_coverage_percentage: number | null;
    full_site_coverage_confidence: "established" | "not_established";
  };
  browser_engine_progress: {
    status: string;
    engines: Array<{
      engine: string;
      eligible_pages: number;
      queued_pages: number;
      attempted_pages: number;
      tested_pages: number;
      passed_pages: number;
      partial_pages: number;
      failed_pages: number;
      inconclusive_pages: number;
      unavailable_pages: number;
      timed_out_pages?: number;
      availability_status?: string;
    }>;
    matrix?: Array<{
      page_url: string;
      page_title: string | null;
      result: string;
      issue_count: number;
      engines: Record<string, string>;
    }>;
  };
  agent_states: Array<{ agent_id: string; status: string }>;
  stages: Array<{
    stage_id: string;
    label: string;
    weight: number;
    status: string;
  }>;
  completed_stage_ids: string[];
  active_stage_id: string | null;
  pending_stage_ids: string[];
  failed_stage_id: string | null;
  last_progress_update: string;
  stale: boolean;
  business_error_message: string | null;
  report_generation_available: boolean;
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

export interface ReportOccurrence {
  normalized_url: string;
  final_url: string;
  status_code: number | null;
  collection_status: string;
  page_title: string | null;
  page_type: string;
  section: string;
  selector: string | null;
  resource_url: string | null;
  location: string | null;
  observed_value: string | null;
  expected_value: string | null;
  evidence_timestamp: string;
  analysis_provider: string;
  analysis_provider_version: string | null;
  artifact_reference: unknown;
  scope: string;
  browser_engines_affected?: string[];
  browser_engines_where_it_works?: string[];
}

export interface DetailedReportFinding {
  finding_id: string;
  finding_code: string;
  finding_type: string;
  issue_title: string;
  plain_language_explanation: string;
  technical_explanation: string;
  category: string;
  severity: string;
  confidence: { classification: string; percent: number | null };
  affected_pages: ReportOccurrence[];
  exact_occurrences: ReportOccurrence[];
  affected_page_count: number;
  occurrence_count: number;
  evidence_references: Array<Record<string, unknown>>;
  evidence_source: Record<string, unknown>;
  detecting_agent: string;
  validating_agent: string;
  likely_cause: string;
  technical_impact: string;
  business_impact: string;
  recommended_remediation: string;
  responsible_role: string;
  estimated_effort_band: string;
  verification_procedure: string;
  related_finding_ids: string[];
  evidence_limitations: string;
  evidence_state: "available" | "unavailable" | "incomplete";
  scope: string;
}

export interface SectionAgentAttribution {
  agents_involved: Array<{
    agent_id: string;
    agent_version: string;
    execution_status: string;
    tools_used: string[];
    allowed_tool_ids: string[];
    evidence_reference_count: number;
    limitations: string;
  }>;
  tools_used: string[];
  execution_status: string;
  evidence_produced: Array<Record<string, unknown>>;
  unavailable_tools: string[];
  unavailable_providers: string[];
  fallback_behavior: string;
  private_reasoning_included: false;
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
