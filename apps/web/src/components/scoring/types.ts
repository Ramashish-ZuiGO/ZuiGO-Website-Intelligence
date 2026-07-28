export type ScoreState =
  | "pending"
  | "running"
  | "completed"
  | "partial"
  | "failed"
  | "unavailable";

export interface ScoreExecution {
  execution_id: string;
  project_id: string;
  website_id: string;
  analysis_run_id: string;
  formula_id: string;
  formula_version: string;
  scoring_profile_id: string;
  scoring_profile_version: string;
  metric_registry_version: string;
  input_fingerprint: string;
  idempotency_key: string;
  status: ScoreState;
  overall_score: number | null;
  confidence_percent: number | null;
  confidence_classification: string;
  evidence_coverage_numerator: number;
  evidence_coverage_denominator: number;
  evidence_coverage_percentage: number | null;
  unavailable_metrics: string[];
  excluded_metrics: Array<Record<string, unknown>>;
  failure_details: Record<string, unknown>;
  partial_completion_details: Record<string, unknown>;
  started_at: string;
  completed_at: string | null;
  created_at: string;
  trend?: Record<string, unknown>;
}

export interface CategoryScore {
  category_id: string;
  raw_score: number | null;
  final_score: number | null;
  configured_weight: number;
  normalized_weight: number | null;
  contribution: number | null;
  band: string;
  included: boolean;
  exclusion_reason: string | null;
  thresholds: Record<string, unknown>;
  deductions: Array<Record<string, unknown>>;
  adjustments: Array<Record<string, unknown>>;
  evidence_references: Array<Record<string, unknown>>;
}

export interface MetricContribution {
  metric_id: string;
  raw_value: Record<string, unknown>;
  normalized_value: number | null;
  configured_weight: number;
  normalized_weight: number | null;
  contribution: number | null;
  inclusion_status: string;
  exclusion_reason: string | null;
  threshold_decision: Record<string, unknown>;
  deduction_or_adjustment: Record<string, unknown>;
  evidence_references: Array<Record<string, unknown>>;
}

export interface ScoreBreakdown {
  execution: ScoreExecution;
  snapshot: {
    snapshot_id: string;
    overall_score: number | null;
    category_scores: Record<string, number | null>;
    confidence_percent: number | null;
    evidence_coverage_percentage: number | null;
    unavailable_metrics: string[];
    excluded_metrics: Array<Record<string, unknown>>;
    evidence_references: Array<Record<string, unknown>>;
    calculation_details: Record<string, unknown>;
    created_at: string;
  };
  categories: CategoryScore[];
  contributions: MetricContribution[];
  explanation: {
    formula_summary: string;
    profile_summary: string;
    normalization_decisions: Array<Record<string, unknown>>;
    caps_floors_deductions: Array<Record<string, unknown>>;
    limitations: string[];
    reproducibility_payload: Record<string, unknown>;
  };
  trend: Record<string, unknown>;
}

export interface PaginatedScores {
  items: ScoreExecution[];
  total: number;
  limit: number;
  offset: number;
}

export interface ScoringFormula {
  formula_id: string;
  version: string;
  category_weights: Record<string, number>;
  rounding: string;
  unavailable_behavior: string;
  technical_quality_deductions: Record<string, number>;
  limitations: string[];
  llm_calculation_allowed: boolean;
}

export interface ScoringProfile {
  profile_id: string;
  version: string;
  name: string;
  bands: Record<string, number>;
  threshold_rules: Array<Record<string, unknown>>;
  limitations: string[];
}
