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
  | "seo"
  | "technical_quality"
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

export type RatingEnum = "good" | "needs_improvement" | "poor" | "unavailable" | "not_applicable";
export type ComparisonDirectionEnum = "higher_is_better" | "lower_is_better";
export type EvidenceTypeEnum = "field" | "lab" | "automated" | "manual" | "mixed";

export interface OfficialSourceMetadata {
  authoritative_organization: string;
  source_title: string;
  standard_version?: string | null;
  publication_date?: string | null;
  url?: string | null;
  evidence_type: EvidenceTypeEnum;
  review_date: string;
  limitations: string[];
}

export interface ThresholdRule {
  metric_id: string;
  good_threshold?: number | null;
  needs_improvement_threshold?: number | null;
  poor_threshold?: number | null;
  comparison_direction: ComparisonDirectionEnum;
  unit?: string | null;
  evidence_type: EvidenceTypeEnum;
  source_reference?: OfficialSourceMetadata | null;
  interpretation_text?: string | null;
  limitations: string[];
}

export interface ProfileDefinition {
  profile_id: string;
  name: string;
  version: string;
  description: string;
  intended_website_type: string;
  country_jurisdiction?: string | null;
  applicable_standards: string[];
  source_references: OfficialSourceMetadata[];
  threshold_rules: ThresholdRule[];
  limitations: string[];
  is_default: boolean;
  registry_version: string;
}

export interface MetricInterpretation {
  metric_id: string;
  raw_value?: number | string | null;
  unit?: string | null;
  rating: RatingEnum;
  selected_profile_id: string;
  selected_profile_version: string;
  thresholds_used: Record<string, number | null>;
  evidence_type?: EvidenceTypeEnum | null;
  source_reference?: OfficialSourceMetadata | null;
  explanation?: string | null;
  limitations: string[];
}
