import { apiUrl } from "@/lib/api";

// ---------------------------------------------------------------------------
// Token storage — localStorage, keyed by "zuigo_access_token"
// ---------------------------------------------------------------------------

const TOKEN_KEY = "zuigo_access_token";

/** Read the stored bearer token, or null if not logged in. */
export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

/** Persist a bearer token after successful login. */
export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

/** Remove the stored token (logout or 401 invalidation). */
export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

// ---------------------------------------------------------------------------
// Login API
// ---------------------------------------------------------------------------

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_at: string;
}

interface LoginErrorEnvelope {
  error?: {
    code?: string;
    message?: string;
    details?: unknown;
    request_id?: string;
  };
}

export class AuthError extends Error {
  constructor(
    message: string,
    public readonly code: string,
  ) {
    super(message);
    this.name = "AuthError";
  }
}

/**
 * Authenticate with username + password.
 * On success, stores the access_token and returns the full response.
 * On failure, throws AuthError with the server's error code.
 *
 * Does NOT store the password — only the returned token.
 */
export async function login(
  username: string,
  password: string,
): Promise<LoginResponse> {
  const response = await fetch(`${apiUrl}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });

  if (!response.ok) {
    let message = "Login failed.";
    let code = "LOGIN_FAILED";
    try {
      const payload = (await response.json()) as LoginErrorEnvelope;
      if (payload.error?.message) message = payload.error.message;
      if (payload.error?.code) code = payload.error.code;
    } catch {
      // Use default message
    }
    throw new AuthError(message, code);
  }

  const data = (await response.json()) as LoginResponse;
  setToken(data.access_token);
  return data;
}
