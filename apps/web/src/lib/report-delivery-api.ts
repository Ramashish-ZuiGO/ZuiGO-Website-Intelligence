import { apiRequest, apiUrl } from "@/lib/api";
import type {
  AnalysisJourneyStart,
  DeliveredReport,
  PaginatedReports,
  WorkflowProgress,
} from "@/components/reports/types";

function query(values: Record<string, string | number | undefined>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined && value !== "") params.set(key, String(value));
  }
  const encoded = params.toString();
  return encoded ? `?${encoded}` : "";
}

export const reportDeliveryApi = {
  startAnalysis: (
    projectId: string,
    websiteId: string,
    idempotencyKey: string,
  ) =>
    apiRequest<AnalysisJourneyStart>(
      `/api/v1/projects/${encodeURIComponent(projectId)}/websites/${encodeURIComponent(websiteId)}/analysis/start`,
      {
        method: "POST",
        body: JSON.stringify({ idempotency_key: idempotencyKey }),
      },
    ),
  progress: (executionId: string) =>
    apiRequest<WorkflowProgress>(
      `/api/v1/workflow-executions/${encodeURIComponent(executionId)}/progress`,
    ),
  generate: (
    analysisRunId: string,
    idempotencyKey: string,
    workflowExecutionId?: string,
  ) =>
    apiRequest<DeliveredReport>(
      `/api/v1/analysis-runs/${encodeURIComponent(analysisRunId)}/reports/generate`,
      {
        method: "POST",
        body: JSON.stringify({
          idempotency_key: idempotencyKey,
          workflow_execution_id: workflowExecutionId ?? null,
        }),
      },
    ),
  forRun: (analysisRunId: string, limit = 10, offset = 0) =>
    apiRequest<PaginatedReports>(
      `/api/v1/analysis-runs/${encodeURIComponent(analysisRunId)}/reports${query({ limit, offset })}`,
    ),
  history: (websiteId: string, limit = 10, offset = 0) =>
    apiRequest<PaginatedReports>(
      `/api/v1/websites/${encodeURIComponent(websiteId)}/reports/history${query({ limit, offset })}`,
    ),
  detail: (reportId: string) =>
    apiRequest<DeliveredReport>(
      `/api/v1/reports/${encodeURIComponent(reportId)}`,
    ),
  downloadUrl: (reportId: string, format: string) =>
    `${apiUrl}/api/v1/reports/${encodeURIComponent(reportId)}/download/${encodeURIComponent(format)}`,
};
