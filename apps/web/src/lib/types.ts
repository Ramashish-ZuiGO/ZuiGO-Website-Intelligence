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
}
