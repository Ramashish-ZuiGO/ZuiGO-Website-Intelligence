import { apiRequest } from "@/lib/api";
import type {
  PaginatedScores,
  ScoreBreakdown,
  ScoreExecution,
  ScoringFormula,
  ScoringProfile,
} from "@/components/scoring/types";

function query(values: Record<string, string | number | undefined>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined && value !== "") params.set(key, String(value));
  }
  const encoded = params.toString();
  return encoded ? `?${encoded}` : "";
}

export const scoringApi = {
  calculate: (runId: string, idempotencyKey: string) =>
    apiRequest<ScoreExecution>(`/api/v1/analysis-runs/${runId}/scores/calculate`, {
      method: "POST",
      body: JSON.stringify({ idempotency_key: idempotencyKey }),
    }),
  listForRun: (runId: string, limit = 25, offset = 0) =>
    apiRequest<PaginatedScores>(
      `/api/v1/analysis-runs/${runId}/scores${query({ limit, offset })}`,
    ),
  latestForWebsite: (websiteId: string) =>
    apiRequest<ScoreExecution>(`/api/v1/websites/${websiteId}/scores`),
  history: (
    websiteId: string,
    filters: {
      formulaVersion?: string;
      profileId?: string;
      status?: string;
      limit?: number;
      offset?: number;
    } = {},
  ) =>
    apiRequest<PaginatedScores>(
      `/api/v1/websites/${websiteId}/scores/history${query({
        formula_version: filters.formulaVersion,
        profile_id: filters.profileId,
        status: filters.status,
        limit: filters.limit,
        offset: filters.offset,
      })}`,
    ),
  get: (executionId: string) =>
    apiRequest<ScoreExecution>(`/api/v1/scores/${executionId}`),
  breakdown: (executionId: string) =>
    apiRequest<ScoreBreakdown>(`/api/v1/scores/${executionId}/breakdown`),
  formulas: () => apiRequest<ScoringFormula[]>("/api/v1/scoring/formulas"),
  profiles: () => apiRequest<ScoringProfile[]>("/api/v1/scoring/profiles"),
};
