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
