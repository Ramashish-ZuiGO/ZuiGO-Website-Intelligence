export type PresentationStatus =
  | "ready"
  | "completed"
  | "fallback"
  | "not_prepared";

export interface DemoAgent {
  agent_id: string;
  name: string;
  responsibility: string;
  status: string;
  processed_summary: string;
}

export interface DemoStage {
  stage_id: string;
  name: string;
  agent_ids: string[];
  parallel: boolean;
  status: string;
}

export interface PageCoverage {
  total_urls_discovered: number;
  total_pages_scheduled: number;
  total_pages_visited: number;
  successfully_analysed_pages: number;
  failed_pages: number;
  skipped_pages: number;
  excluded_pages: number;
  redirected_pages: number;
  duplicate_normalized_pages: number;
  pages_with_incomplete_evidence: number;
  coverage_numerator: number;
  coverage_denominator: number;
  coverage_percentage: number | null;
  started_at: string;
  completed_at: string;
  duration_seconds: number;
  definitions: Record<string, string>;
}

export interface PageInventoryItem {
  url: string;
  title: string;
  page_type: string;
  http_status: number | null;
  analysis_status: string;
  browsers_tested: string[];
  issue_count: number;
  highest_severity: string;
  evidence_coverage_percentage: number | null;
}

export interface BrowserMatrixItem {
  page_url: string;
  page_title: string;
  engines: Record<string, string>;
  result: string;
  issue_count: number;
}

export interface BrowserCompatibility {
  browser_engine_tests: true;
  engines: Array<{ engine: string; label: string }>;
  viewports: Array<{ name: string; width: number; height: number }>;
  eligible_page_count: number;
  engine_coverage: Array<{
    engine: string;
    tested_pages: number;
    eligible_pages: number;
    percentage: number | null;
  }>;
  matrix: BrowserMatrixItem[];
  summary: {
    compatibility_percentage: number | null;
    compatible_pages: number;
    partially_compatible_pages: number;
    incompatible_pages: number;
    untested_or_inconclusive_pages: number;
  };
  status_labels: Record<string, string>;
  limitations: string[];
}

export interface DemoFinding {
  title: string;
  severity: string;
  affected_page_count: number;
  occurrence_count: number;
  affected_browsers: string[];
  works_in_browsers: string[];
  plain_language_explanation: string;
  technical_explanation: string;
  why_it_matters: string;
  business_impact: string;
  technical_impact: string;
  evidence_summary: string;
  evidence_source: string;
  evidence_timestamp: string;
  example_pages: string[];
  remaining_page_count: number;
  recommended_fix: string;
  responsible_role: string;
  estimated_effort: string;
  verification: string;
  confidence: { classification: string; percent: number | null };
  detecting_agent: string;
  validating_agent: string;
  limitations: string;
  all_affected_pages: Array<{
    normalized_url: string;
    page_title: string | null;
    selector: string | null;
    resource_url: string | null;
    location: string | null;
    observed_value: string | null;
    expected_value: string | null;
    evidence_timestamp: string;
    analysis_provider: string;
    browser_engine_affected?: string[];
    browser_engine_where_it_works?: string[];
  }>;
}

export interface DemoAction {
  priority_rank: number;
  title: string;
  priority_score: number;
  responsible_role: string;
  impact: string;
  effort: string;
  problem_being_solved: string;
  affected_scope: { page_count: number; occurrence_count?: number };
  affected_browsers: string[];
  dependencies: unknown[];
  expected_measurable_outcome: string;
  verification_method: string;
  related_finding_ids: string[];
  evidence_references: Array<Record<string, unknown>>;
}

export interface DemoArtifact {
  kind:
    | "presentation_html"
    | "presentation_pdf"
    | "technical_appendix"
    | "evidence_json"
    | "page_inventory";
  label: string;
  filename: string;
  size_bytes: number;
  checksum_sha256: string;
  download_url: string;
}

export interface PresentationDemo {
  prepared: boolean;
  presentation_status: PresentationStatus;
  live_execution_status: string | null;
  used_prepared_fallback: boolean;
  status_message: string;
  project_id: string | null;
  project_name: string | null;
  website_id: string | null;
  website_name: string | null;
  website_url: string | null;
  analysis_run_id: string | null;
  workflow_execution_id: string | null;
  report_id: string | null;
  report_status: string | null;
  report_ready: boolean;
  overall_score: number | null;
  score_confidence_percent: number | null;
  evidence_coverage_numerator: number;
  evidence_coverage_denominator: number;
  evidence_coverage_percentage: number | null;
  page_coverage: PageCoverage;
  page_inventory: PageInventoryItem[];
  browser_compatibility: BrowserCompatibility;
  category_scores: Array<{ label: string; score: number }>;
  agents: DemoAgent[];
  stages: DemoStage[];
  top_findings: DemoFinding[];
  top_actions: DemoAction[];
  artifacts: DemoArtifact[];
  reused: boolean;
}

export interface DemoReset {
  reset: boolean;
  deleted_project_count: number;
  status_message: string;
}
