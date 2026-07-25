export type MetricValueType =
  | "score"
  | "percentage"
  | "count"
  | "duration"
  | "bytes"
  | "ratio"
  | "boolean"
  | "status"
  | "text"
  | "unavailable";

export type MetricCategory =
  | "site_score"
  | "category_score"
  | "page_score"
  | "diagnostic_score"
  | "action_plan"
  | "coverage"
  | "repository"
  | "performance"
  | "accessibility"
  | "security"
  | "compatibility"
  | "other";

export interface MetricDefinition {
  metric_id: string;
  label: string;
  category: MetricCategory;
  description: string;
  explanation: string;
  value_type: MetricValueType;
  unit?: string | null;
  display_scale?: string | null;
  min_value?: number | null;
  max_value?: number | null;
  higher_is_better?: boolean | null;
  evidence_source: string;
  calculation_summary: string;
  interpretation_guidance: string;
  profile_reference?: string | null;
  known_limitations: string;
  confidence_applicability: string;
  methodology_version?: string | null;
  registry_version: string;
}
