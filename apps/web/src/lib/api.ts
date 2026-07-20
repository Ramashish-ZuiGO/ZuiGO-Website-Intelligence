export const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

interface ApiErrorEnvelope {
  error?: {
    message?: string;
    request_id?: string;
  };
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
    try {
      const payload = (await response.json()) as ApiErrorEnvelope;
      if (payload.error?.message) message = payload.error.message;
      if (payload.error?.request_id) message += ` Request ID: ${payload.error.request_id}`;
    } catch {
      // Preserve the safe status-based message when the response is not JSON.
    }
    throw new Error(message);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
