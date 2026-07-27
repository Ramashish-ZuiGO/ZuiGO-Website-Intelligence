export type DiagnosticStatus =
  | "pending"
  | "running"
  | "completed"
  | "partial"
  | "failed"
  | "cancelled"
  | "unavailable";

export interface SiteDiagnosticExecution {
  id: string;
  execution_id: string;
  website_id: string;
  analysis_run_id: string;
  workflow_id: string;
  workflow_version: string;
  selected_profile_id: string;
  selected_profile_version: string;
  input_fingerprint: string;
  evidence_fingerprint: string;
  idempotency_key: string;
  diagnostic_engine_version: string;
  rule_registry_version: string;
  status: DiagnosticStatus;
  total_page_count: number;
  processed_page_count: number;
  failed_page_count: number;
  evidence_coverage_numerator: number;
  evidence_coverage_denominator: number;
  evidence_coverage_ratio: number;
  error_metadata: Record<string, unknown>;
  partial_completion_metadata: Record<string, unknown>;
  started_at: string;
  completed_at: string | null;
  created_at: string;
}

export interface SiteDiagnosticFinding {
  id: string;
  execution_id: string;
  rule_id: string;
  rule_version: string;
  category: string;
  severity: string;
  confidence: string;
  scope: string;
  title: string;
  description: string;
  why_it_matters: string;
  affected_page_count: number;
  total_eligible_page_count: number;
  occurrence_count: number;
  affected_ratio: number;
  evidence_summary: string;
  evidence_references: Array<Record<string, unknown>>;
  remediation_guidance: string;
  responsible_role: string;
  verification_guidance: string;
  created_at: string;
}

export interface SiteDiagnosticOccurrence {
  id: string;
  finding_id: string;
  website_page_id: string | null;
  normalized_url: string | null;
  evidence_reference: string;
  occurrence_fingerprint: string;
  element_selector: string | null;
  resource_url: string | null;
  location: string | null;
  context: Record<string, unknown>;
  observed_value: string | null;
  expected_value: string | null;
  supporting_evidence: Record<string, unknown>;
  created_at: string;
}

export interface SiteDiagnosticFindingDetail extends SiteDiagnosticFinding {
  occurrences: SiteDiagnosticOccurrence[];
}

export interface SiteDiagnosticRule {
  id: string;
  registry_version: string;
  rule_version: string;
  category: string;
  default_severity: string;
  supported_scopes: string[];
  detection_method: string;
  evidence_requirements: string[];
  limitations: string;
  remediation_guidance: string;
  responsible_role: string;
  verification_guidance: string;
  title: string;
  description: string;
}

export interface SiteDiagnosticLinkGraphNode {
  page_id: string;
  normalized_url: string;
  eligibility_status: string;
  crawl_depth: number;
  inbound_link_count: number;
  outbound_link_count: number;
  outbound_evidence_available: boolean;
  http_status_code: number | null;
  canonical_values: string[];
}

export interface SiteDiagnosticLinkGraphEdge {
  source_page_id: string;
  source_url: string;
  raw_target: string;
  target_url: string;
  target_page_id: string | null;
  target_http_status: number | null;
  redirect_chain: Array<Record<string, unknown>>;
  target_eligibility_status: string | null;
  target_robots_status: string | null;
  target_robots_directives: Record<string, unknown>;
  target_canonical_values: string[];
  evidence_reference: string;
}

export interface SiteDiagnosticMalformedEdge {
  source_page_id: string;
  source_url: string;
  raw_target: string;
  evidence_reference: string;
}

export interface SiteDiagnosticLinkGraph {
  execution_id: string;
  website_id: string;
  evidence_complete: boolean;
  discovery_run_id: string | null;
  total_nodes: number;
  total_edges: number;
  total_malformed_edges: number;
  node_offset: number;
  node_limit: number;
  edge_offset: number;
  edge_limit: number;
  nodes: SiteDiagnosticLinkGraphNode[];
  edges: SiteDiagnosticLinkGraphEdge[];
  malformed_edges: SiteDiagnosticMalformedEdge[];
}
