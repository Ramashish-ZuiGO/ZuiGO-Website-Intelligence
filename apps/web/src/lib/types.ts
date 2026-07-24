export interface Website {
  id: string;
  project_id: string;
  url: string;
  name: string | null;
  created_at: string;
  updated_at: string;
}

export interface Project {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProjectDetail extends Project {
  websites: Website[];
}

export interface DiscoveryRun {
  id: string;
  website_id: string;
  status: "queued" | "running" | "partial" | "completed" | "failed";
  current_stage: string | null;
  progress_percent: number;
  crawl_limit_reached: boolean;
  failure_code: string | null;
  failure_message: string | null;
}

export interface WebsitePage {
  id: string;
  normalized_url: string;
  page_title: string | null;
  page_type: string;
  page_type_confidence: number;
  discovery_source: string;
  crawl_depth: number;
  eligibility_status: "eligible" | "excluded" | "skipped";
  robots_status: "allowed" | "disallowed" | "unknown";
  latest_analysis_status: "pending" | "completed" | "partial" | "failed";
  exclusion_reason: string | null;
  skip_reason: string | null;
  page_analysis_level_1_status: string;
  page_analysis_level_2_status: string;
  page_analysis_level_1_run_id: string | null;
  page_analysis_level_2_run_id: string | null;
  page_analysis_level_1_at: string | null;
  page_analysis_level_2_at: string | null;
}

export interface WebsitePageList {
  items: WebsitePage[];
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
}

export interface CoverageSummary {
  discovery_run_id: string | null;
  discovered_urls: number;
  unique_pages: number;
  eligible_pages: number;
  excluded_pages: number;
  skipped_pages: number;
  robots_disallowed_pages: number;
  analyzed_pages: number;
  completed_analyses: number;
  partial_analyses: number;
  failed_analyses: number;
  pending_analyses: number;
  pages_requiring_action: number;
  pages_without_findings: number;
  analyzed_coverage_numerator: number;
  analyzed_coverage_denominator: number;
  analyzed_coverage_percent: number | null;
  crawl_limit_reached: boolean;
  maximum_depth_reached: number;
  level_1_attempted: number;
  level_1_successful: number;
  level_1_failed: number;
  level_1_partial: number;
  level_2_attempted: number;
  level_2_successful: number;
  level_2_failed: number;
  level_2_partial: number;
}

export type AnalysisStatus = "queued" | "running" | "completed" | "failed";

export interface AnalysisRun {
  id: string;
  website_id: string;
  status: AnalysisStatus;
  progress_percent: number;
  current_step: string | null;
  started_at: string | null;
  completed_at: string | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  result_summary: AnalysisResultSummary | null;
}

export interface AnalysisResultSummary {
  final_url: string;
  http_status_code: number | null;
  page_title: string | null;
  performance_score: number | null;
  accessibility_score: number | null;
  best_practices_score: number | null;
  seo_score: number | null;
  overall_score: number | null;
  technical_quality_score: number | null;
  confidence_percent: number | null;
  finding_count: number;
}

export interface AnalysisFinding {
  id: string;
  finding_code: string;
  category: string;
  title: string;
  description: string;
  severity: "critical" | "high" | "medium" | "low" | "informational";
  affected_url: string;
  evidence: Record<string, unknown>;
  source: "lighthouse" | "playwright" | "http";
  confidence_percent: number;
  created_at: string;
}

export interface AnalysisResults {
  result: {
    id: string;
    analysis_run_id: string;
    requested_url: string;
    final_url: string;
    http_status_code: number | null;
    page_title: string | null;
    meta_description: string | null;
    lighthouse_version: string | null;
    user_agent: string | null;
    analysis_started_at: string;
    analysis_completed_at: string;
  };
  lighthouse_metrics: Record<string, unknown>;
  playwright_measurements: Record<string, unknown>;
  findings: AnalysisFinding[];
  diagnostics: Record<string, DiagnosticGroup>;
}

export interface DiagnosticScore {
  label: "ZuiGO-derived";
  starting_score: number;
  inputs: Record<string, unknown>;
  deductions: Array<{ code: string; reason: string; points: number }>;
  final_score: number;
  formula_version: string;
  confidence_percent: number;
}

export interface DiagnosticGroup {
  status: "available" | "partial" | "unavailable";
  verified_observations: Record<string, unknown>;
  unavailable_observations: string[];
  evidence: Array<Record<string, unknown>>;
  score: DiagnosticScore | null;
  limitations: string[];
  collected_at: string;
  evidence_completeness?: string;
  why_it_matters?: string | null;
  copyright?: DiagnosticGroup;
}

export interface AnalysisScore {
  id: string;
  formula_version: string;
  overall_score: number | null;
  performance_score: number | null;
  accessibility_score: number | null;
  best_practices_score: number | null;
  seo_score: number | null;
  technical_quality_score: number | null;
  confidence_percent: number;
  available_categories: string[];
  unavailable_categories: string[];
  weights: Record<string, number>;
  deductions: Array<Record<string, unknown>>;
  calculation_details: Record<string, unknown>;
}

export interface AnalysisReport {
  report_id: string;
  analysis_run_id: string;
  analysis_status: AnalysisStatus;
  website: { id: string; name: string | null; url: string };
  result: AnalysisResults["result"];
  score: AnalysisScore;
  lighthouse_metrics: Record<string, unknown>;
  playwright_measurements: Record<string, unknown>;
  findings: AnalysisFinding[];
  interpretation: AnalysisInterpretation | null;
  diagnostics: Record<string, DiagnosticGroup>;
}

export interface InterpretationObservation {
  text: string;
  related_finding_codes: string[];
}

export interface InterpretationRecommendation {
  recommendation_id: string;
  title: string;
  explanation: string;
  related_finding_codes: string[];
  priority: "critical" | "high" | "medium" | "low";
  business_impact: string;
  recommended_fix: string;
  estimated_effort: string;
  responsible_role: string;
  expected_improvement: string;
  confidence_percent: number;
}

export interface PageAnalysisRun {
  id: string;
  website_page_id: string;
  analysis_level: number;
  status: string;
  failure_reason_code: string | null;
  failure_reason_text: string | null;
  analysis_started_at: string | null;
  analysis_completed_at: string | null;
  requested_url: string | null;
  final_url: string | null;
  canonical_url: string | null;
  http_status_code: number | null;
  page_title: string | null;
  meta_description: string | null;
  internal_link_count: number | null;
  external_link_count: number | null;
  image_count: number | null;
  images_missing_alt: number | null;
  form_count: number | null;
  language: string | null;
  content_type: string | null;
  structured_data_present: boolean | null;
  elapsed_ms: number | null;
  deep_analysis_run_id: string | null;
}

export interface PageAnalysisSummary {
  website_id: string;
  total_pages: number;
  eligible_pages: number;
  level_1_completed: number;
  level_1_partial: number;
  level_1_failed: number;
  level_1_skipped: number;
  level_1_pending: number;
  level_2_completed: number;
  level_2_partial: number;
  level_2_failed: number;
  level_2_skipped: number;
  level_2_pending: number;
  pages_with_findings: number;
  pages_without_findings: number;
  coverage_percent: number | null;
}

export interface SiteCoverageDetail {
  website_id: string;
  discovery_run_id: string | null;
  discovered_page_count: number;
  eligible_page_count: number;
  selected_page_count: number;
  level_1_attempted: number;
  level_1_successful: number;
  level_1_failed: number;
  level_1_partial: number;
  level_2_attempted: number;
  level_2_successful: number;
  level_2_failed: number;
  level_2_partial: number;
  skipped_page_count: number;
  unanalyzed_eligible_count: number;
  coverage_percent: number | null;
  clean_pass_percent: number | null;
  partial_result_status: boolean;
  coverage_limitations: string[];
}

export interface PageAnalysisActionRecommendation {
  page_id: string;
  page_url: string;
  page_title: string | null;
  issue_title: string;
  issue_category: string;
  severity: string;
  evidence: Record<string, unknown>;
  responsible_area: string;
  responsible_role: string;
  action_location: string;
  remediation: string;
  verification_method: string;
  source: string;
  confidence: string;
  analysis_level: number;
}

export interface PageLevelScore {
  page_id: string;
  page_url: string;
  page_title: string | null;
  analysis_level: number;
  analysis_status: string;
  score: number | null;
  confidence: string;
  score_available: boolean;
}

export interface ActionGenerationExecution {
  id: string;
  website_id: string;
  discovery_run_id: string | null;
  page_analysis_execution_id: string;
  status: string;
  total_findings_processed: number;
  total_actions_generated: number;
  unsupported_finding_count: number;
  insufficient_evidence_count: number;
  duplicate_within_execution_count: number;
  historical_equivalent_count: number;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ActionGroup {
  id: string;
  generation_execution_id: string;
  website_id: string;
  grouping_key: string;
  issue_title: string;
  category: string;
  severity: string;
  priority_score: number;
  priority_formula_version: string;
  confidence: string;
  estimated_effort: string;
  business_impact: string;
  responsible_area: string;
  responsible_role: string;
  action_location: string;
  why_this_matters: string;
  exact_correction: string;
  implementation_steps: string;
  verification_steps: string;
  expected_result: string;
  limitations: string;
  evidence_summary: Record<string, unknown>;
  source_audit: string;
  priority_components: Record<string, unknown>;
  affected_page_count: number;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface ActionItem {
  id: string;
  generation_execution_id: string;
  action_group_id: string | null;
  website_id: string;
  page_analysis_run_id: string | null;
  website_page_id: string;
  source_finding_identity: string;
  source_page_analysis_run_id: string | null;
  requested_url: string | null;
  final_url: string | null;
  page_title: string | null;
  issue_title: string;
  issue_category: string;
  severity: string;
  priority_score: number;
  priority_formula_version: string;
  priority_components: Record<string, unknown>;
  confidence: string;
  confidence_percent: number;
  estimated_effort: string;
  business_impact: string;
  responsible_area: string;
  responsible_role: string;
  action_location: string;
  why_this_matters: string;
  exact_correction: string;
  implementation_steps: string;
  verification_steps: string;
  expected_result: string;
  limitations: string;
  evidence_summary: Record<string, unknown>;
  source_audit: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface ActionStatusHistory {
  id: string;
  action_item_id: string;
  previous_status: string;
  new_status: string;
  reason: string | null;
  actor: string | null;
  source: string;
  changed_at: string;
}

export interface ActionGroupDetail extends ActionGroup {
  actions: ActionItem[];
}

export interface ActionItemDetail extends ActionItem {
  status_history: ActionStatusHistory[];
}

export interface ActionPlanSummary {
  website_id: string;
  generation_execution_id: string | null;
  total_actions: number;
  total_open: number;
  total_acknowledged: number;
  total_in_progress: number;
  total_resolved: number;
  total_ignored: number;
  total_reopened: number;
  critical_actions: number;
  high_priority_actions: number;
  pages_requiring_correction: number;
  grouped_issues: number;
  average_priority: number | null;
  generation_status: string | null;
  generation_coverage: number | null;
}

export interface ActionGenerationStartResponse {
  status: string;
  generation_execution_id: string;
  page_analysis_execution_id: string;
}

export interface PaginatedResponse<T = unknown> {
  items: T[];
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
}

export interface BulkStatusUpdateResult {
  total: number;
  succeeded: number;
  failed: number;
  failures: Array<{action_id: string; error: string}>;
}

export interface AnalysisInterpretation {
  id: string;
  generation_mode: "ai" | "deterministic_fallback";
  provider: string;
  model: string;
  prompt_version: string;
  executive_summary: string;
  overall_assessment: string;
  strengths: InterpretationObservation[];
  weaknesses: InterpretationObservation[];
  priority_recommendations: InterpretationRecommendation[];
  action_plan: Array<{
    timeframe: "immediate" | "short_term" | "medium_term";
    recommendation_ids: string[];
  }>;
  limitations: string[];
  fallback_reason: string | null;
  generated_at: string;
}

export type RepositoryProvider =
  | "local"
  | "github"
  | "gitlab"
  | "bitbucket"
  | "azure_devops";

export interface RepositoryConnection {
  id: string;
  project_id: string;
  provider: string;
  display_name: string;
  local_root: string;
  remote_url: string | null;
  default_branch: string | null;
  current_branch: string | null;
  current_commit_sha: string | null;
  framework_summary: Record<string, unknown> | null;
  status: string;
  last_scan_execution_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface RepositoryConnectionCreate {
  project_id: string;
  provider: string;
  display_name: string;
  local_root: string;
  remote_url?: string | null;
}

export interface RepositoryConnectionUpdate {
  display_name?: string | null;
  local_root?: string | null;
  status?: string | null;
  remote_url?: string | null;
}

export interface RepositoryConnectionValidate {
  local_root: string;
  is_git: boolean;
  error_message: string | null;
}

export interface RepositoryScanExecution {
  id: string;
  connection_id: string;
  requested_commit_sha: string | null;
  resolved_commit_sha: string | null;
  branch: string | null;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  total_files_discovered: number;
  eligible_files: number;
  scanned_files: number;
  skipped_files: number;
  failed_files: number;
  ignored_directories: string[] | null;
  detected_frameworks: Record<string, unknown> | null;
  limitations: string[] | null;
  failure_reason_code: string | null;
  failure_explanation: string | null;
  created_at: string;
  updated_at: string;
}

export interface RepositoryFileIndex {
  id: string;
  scan_execution_id: string;
  relative_path: string;
  normalized_path: string;
  extension: string | null;
  detected_language: string | null;
  file_size: number;
  line_count: number;
  content_hash: string | null;
  git_status: string | null;
  framework_role: string | null;
  module_hints: Record<string, unknown> | null;
  exported_symbols: string[] | null;
  redacted: boolean;
  redaction_metadata: Record<string, unknown> | null;
  first_lines: string | null;
  scan_status: string;
  skip_reason: string | null;
  created_at: string;
}

export interface DetectedTechnology {
  id: string;
  scan_execution_id: string;
  technology: string;
  confidence: string;
  supporting_files: string[] | null;
  evidence: Record<string, unknown> | null;
  limitations: string | null;
  created_at: string;
}

export interface ActionMatchingExecution {
  id: string;
  connection_id: string;
  scan_execution_id: string;
  generation_execution_id: string | null;
  status: string;
  total_actions: number;
  located_actions: number;
  unlocated_actions: number;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ActionRepositoryMatch {
  id: string;
  matching_execution_id: string;
  action_item_id: string;
  repository_file_id: string | null;
  relative_path: string | null;
  start_line: number | null;
  end_line: number | null;
  symbol_name: string | null;
  match_reason: string | null;
  evidence_snippet: string | null;
  match_confidence: string;
  mapping_strategy: string | null;
  is_primary: boolean;
  created_at: string;
}

export interface ScanSummary {
  total_files_discovered: number;
  eligible_files: number;
  scanned_files: number;
  skipped_files: number;
  failed_files: number;
  total_technologies: number;
  total_actions_matched: number;
  located_actions: number;
  unlocated_actions: number;
}
