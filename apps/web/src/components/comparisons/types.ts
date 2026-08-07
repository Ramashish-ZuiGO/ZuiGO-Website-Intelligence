export type ComparisonDirection =
  | "Improved"
  | "Regressed"
  | "Unchanged"
  | "Resolved"
  | "Persistent"
  | "New"
  | "Inconclusive"
  | "Not comparable";

export interface ReanalysisSettings {
  baseline_analysis_run_id: string;
  website_id: string;
  website_url: string;
  baseline_created_at: string;
  maximum_pages: number | null;
  browser_engines: Array<"chromium" | "firefox" | "webkit">;
  include_mobile: boolean;
  max_concurrency: number;
}

export interface ReanalysisStart {
  baseline_analysis_run_id: string;
  analysis_run_id: string;
  discovery_run_id: string;
  page_analysis_execution_id: string;
  workflow_execution_id: string;
  analysis_status: string;
  workflow_status: string;
  reused: boolean;
}

export interface ComparisonArtifact {
  artifact_id: string;
  format: "html" | "pdf" | "json";
  media_type: string;
  filename: string;
  checksum_sha256: string;
  created_at: string;
}

export interface ComparisonFinding {
  title: string;
  category: string;
  classification: string;
  severity_before: string;
  severity_after: string;
  affected_page_count_before: number;
  affected_page_count_after: number;
  affected_urls_before: string[];
  affected_urls_after: string[];
  affected_urls: string[];
  browser: string[];
  observed_change: string;
  recommended_next_action: string;
  evidence_limitation: string;
  direction?: string;
}

interface CountDelta {
  before: number | null;
  after: number | null;
  delta: number | null;
}

export interface ComparisonPayload {
  schema_version: string;
  website: { name: string; url: string };
  baseline: { analysis_date: string; status: string };
  current: { analysis_date: string; status: string };
  summary: {
    direction: ComparisonDirection;
    resolved_count: number;
    persistent_count: number;
    new_count: number;
    regression_count: number;
    inconclusive_count: number;
  };
  scores: {
    overall_score_before: number | null;
    overall_score_after: number | null;
    overall_delta: number | null;
    confidence_before: number | null;
    confidence_after: number | null;
    direction: ComparisonDirection;
    formula_version_before: string | null;
    formula_version_after: string | null;
    categories: Array<{
      category: string;
      score_before: number | null;
      score_after: number | null;
      delta: number | null;
      direction: ComparisonDirection;
      status_before: string | null;
      status_after: string | null;
    }>;
  };
  coverage: {
    discovered: CountDelta;
    scheduled: CountDelta;
    visited: CountDelta;
    successfully_analysed: CountDelta;
    coverage_percentage: CountDelta;
    comparable: boolean;
    direction: ComparisonDirection;
    missing_current_urls: string[];
    newly_analysed_urls: string[];
    limitation: string | null;
  };
  browser_compatibility: {
    engines: Array<{
      engine: string;
      before: Record<string, number>;
      after: Record<string, number>;
      direction: ComparisonDirection;
      comparable_page_count: number;
      new_failures: string[];
      resolved_failures: string[];
      untested_combinations: string[];
      limitation: string | null;
    }>;
  };
  findings: {
    resolved: ComparisonFinding[];
    persistent: ComparisonFinding[];
    new: ComparisonFinding[];
    regressions: ComparisonFinding[];
    changed_severity: ComparisonFinding[];
    inconclusive: ComparisonFinding[];
  };
  action_plan: Array<{
    title: string;
    classification: string;
    priority_before: number | null;
    priority_after: number | null;
    status_before: string | null;
    status_after: string | null;
    supporting_evidence: string;
    verification_method: string;
  }>;
  limitations: string[];
}

export interface AnalysisComparison {
  comparison_id: string;
  status: string;
  result_payload: ComparisonPayload;
  artifacts: ComparisonArtifact[];
}
