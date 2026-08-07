import type {
  AnalysisComparison,
  ReanalysisSettings,
  ReanalysisStart,
} from "@/components/comparisons/types";
import { apiRequest, apiUrl } from "@/lib/api";

export const analysisComparisonApi = {
  settings: (baselineRunId: string) =>
    apiRequest<ReanalysisSettings>(
      `/api/v1/analysis-runs/${encodeURIComponent(baselineRunId)}/reanalysis-settings`,
    ),
  reanalyse: (
    baselineRunId: string,
    input: {
      confirmed: true;
      idempotency_key: string;
      browser_engines: Array<"chromium" | "firefox" | "webkit">;
      include_mobile: boolean;
      max_concurrency: number;
    },
  ) =>
    apiRequest<ReanalysisStart>(
      `/api/v1/analysis-runs/${encodeURIComponent(baselineRunId)}/reanalyse`,
      { method: "POST", body: JSON.stringify(input) },
    ),
  detail: (currentRunId: string, baselineRunId: string) =>
    apiRequest<AnalysisComparison>(
      `/api/v1/analysis-runs/${encodeURIComponent(currentRunId)}/comparisons/${encodeURIComponent(baselineRunId)}`,
    ),
  generate: (currentRunId: string, baselineRunId: string, idempotencyKey: string) =>
    apiRequest<AnalysisComparison>(
      `/api/v1/analysis-runs/${encodeURIComponent(currentRunId)}/comparisons/${encodeURIComponent(baselineRunId)}/generate`,
      {
        method: "POST",
        body: JSON.stringify({ idempotency_key: idempotencyKey }),
      },
    ),
  downloadUrl: (comparisonId: string, format: string) =>
    `${apiUrl}/api/v1/analysis-comparisons/${encodeURIComponent(comparisonId)}/download/${encodeURIComponent(format)}`,
};
