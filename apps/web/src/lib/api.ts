export const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

interface ApiErrorEnvelope {
  error?: {
    code?: string;
    message?: string;
    details?: unknown;
    request_id?: string;
  };
}

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly code: string,
    public readonly details: unknown = null,
    public readonly requestId: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiUrl}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });

  if (!response.ok) {
    let message = `Request failed with status ${response.status}.`;
    let code = `HTTP_${response.status}`;
    let details: unknown = null;
    let requestId: string | null = response.headers.get("X-Request-ID");
    try {
      const payload = (await response.json()) as ApiErrorEnvelope;
      if (payload.error?.code) code = payload.error.code;
      if (payload.error?.message) message = payload.error.message;
      if (payload.error?.details !== undefined) details = payload.error.details;
      if (payload.error?.request_id) requestId = payload.error.request_id;
    } catch {
      // Preserve the safe status-based message when the response is not JSON.
    }
    throw new ApiError(message, response.status, code, details, requestId);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
