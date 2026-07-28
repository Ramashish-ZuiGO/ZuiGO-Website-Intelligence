export type PresentationStatus =
  | "ready"
  | "completed"
  | "fallback"
  | "not_prepared";

export interface DemoAgent {
  agent_id: string;
  name: string;
  status: string;
  contribution: string;
  tool_ids: string[];
}

export interface DemoStage {
  stage_id: string;
  name: string;
  agent_ids: string[];
  parallel: boolean;
  status: string;
}

export interface DemoFinding {
  finding_id: string;
  title: string;
  severity: string;
  page_url: string;
  evidence_state: string;
}

export interface DemoAction {
  action_id: string;
  title: string;
  priority_score: number;
  responsible_role: string;
  verification: string;
}

export interface DemoArtifact {
  format: "html" | "pdf" | "json";
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
