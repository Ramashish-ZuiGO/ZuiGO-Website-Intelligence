import type {
  DemoReset,
  PresentationDemo,
} from "@/components/presentation/types";
import { apiRequest, apiUrl } from "@/lib/api";

export const presentationDemoApi = {
  status: (signal?: AbortSignal) =>
    apiRequest<PresentationDemo>("/api/v1/demo", { signal }),
  prepare: () =>
    apiRequest<PresentationDemo>("/api/v1/demo/prepare", {
      method: "POST",
    }),
  run: (idempotencyKey: string, signal?: AbortSignal) =>
    apiRequest<PresentationDemo>("/api/v1/demo/run", {
      method: "POST",
      body: JSON.stringify({
        idempotency_key: idempotencyKey,
        simulate_failure: false,
      }),
      signal,
    }),
  reset: () =>
    apiRequest<DemoReset>("/api/v1/demo/reset", {
      method: "POST",
    }),
  artifactUrl: (path: string) => `${apiUrl}${path}`,
};
