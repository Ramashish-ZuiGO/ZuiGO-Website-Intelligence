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
  lighthouse_metrics: Record<string, number | string | null>;
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
  lighthouse_metrics: Record<string, number | string | null>;
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
