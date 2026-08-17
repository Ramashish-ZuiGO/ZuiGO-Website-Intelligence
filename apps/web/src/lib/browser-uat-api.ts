import { apiRequest } from "@/lib/api";
import { ApiError } from "@/lib/api";
import type {
  BrowserUatExecution,
  BrowserUatResults,
} from "@/components/browser-uat/types";

const BASE = "/api/v1/analysis-runs";

function tier0Path(analysisRunId: string): string {
  return `${BASE}/${encodeURIComponent(analysisRunId)}/browser-uat/tier0`;
}

export const browserUatApi = {
  /** Start a real Chrome/Edge/Safari check. Returns 202 (new) or 200 (replay). */
  start: (analysisRunId: string, idempotencyKey: string) =>
    apiRequest<BrowserUatExecution>(tier0Path(analysisRunId), {
      method: "POST",
      body: JSON.stringify({ idempotency_key: idempotencyKey }),
    }),

  /** Get the most recent check status. 404 if never started. */
  status: (analysisRunId: string) =>
    apiRequest<BrowserUatExecution>(tier0Path(analysisRunId)),

  /** Get real findings once a check reaches a terminal state. */
  results: (analysisRunId: string) =>
    apiRequest<BrowserUatResults>(`${tier0Path(analysisRunId)}/results`),
};

export { ApiError };
