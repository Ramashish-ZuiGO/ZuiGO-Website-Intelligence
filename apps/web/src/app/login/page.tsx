"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useState } from "react";
import { Activity, Loader2 } from "lucide-react";

import { login, AuthError } from "@/lib/auth";

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!username.trim() || !password) return;

    setSubmitting(true);
    setError(null);

    try {
      await login(username.trim(), password);
      const redirect = searchParams.get("redirect") || "/";
      router.replace(redirect);
    } catch (reason) {
      if (reason instanceof AuthError) {
        setError(reason.message);
      } else {
        setError("Unable to connect. Please check your network and try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form
      className="rounded-xl border border-z-border bg-z-surface p-6 shadow-sm"
      onSubmit={(e) => void handleSubmit(e)}
    >
      {error && (
        <div
          className="mb-4 rounded-lg bg-z-danger-subtle border border-z-danger/20 px-4 py-3 text-sm text-z-danger"
          role="alert"
        >
          {error}
        </div>
      )}

      <div className="space-y-4">
        <div>
          <label
            className="block text-sm font-medium text-z-ink mb-1.5"
            htmlFor="login-username"
          >
            Username
          </label>
          <input
            autoComplete="username"
            autoFocus
            className="w-full rounded-lg border border-z-border bg-z-surface px-3 py-2 text-sm text-z-ink placeholder:text-z-ink-muted focus:border-z-accent focus:outline-none focus:ring-2 focus:ring-z-accent/20"
            id="login-username"
            onChange={(e) => setUsername(e.target.value)}
            placeholder="Username"
            required
            type="text"
            value={username}
          />
        </div>

        <div>
          <label
            className="block text-sm font-medium text-z-ink mb-1.5"
            htmlFor="login-password"
          >
            Password
          </label>
          <input
            autoComplete="current-password"
            className="w-full rounded-lg border border-z-border bg-z-surface px-3 py-2 text-sm text-z-ink placeholder:text-z-ink-muted focus:border-z-accent focus:outline-none focus:ring-2 focus:ring-z-accent/20"
            id="login-password"
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Password"
            required
            type="password"
            value={password}
          />
        </div>
      </div>

      <button
        className="mt-6 w-full rounded-lg bg-z-accent px-4 py-2.5 text-sm font-semibold text-white hover:bg-z-accent-hover disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
        disabled={submitting || !username.trim() || !password}
        type="submit"
      >
        {submitting ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            Signing in…
          </>
        ) : (
          "Sign in"
        )}
      </button>
    </form>
  );
}

export default function LoginPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-z-canvas px-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <div className="inline-flex items-center gap-2 font-display text-2xl font-bold tracking-tight text-z-ink">
            <Activity className="h-6 w-6 text-z-accent" aria-hidden="true" />
            <span className="flex items-baseline">
              Zu
              <span className="relative inline-block leading-none">
                ı
                <span
                  className="absolute left-[50%] top-[-0.05em] h-[0.22em] w-[0.22em] -translate-x-1/2 rounded-full"
                  aria-hidden="true"
                  style={{ backgroundColor: "var(--brand-dot, var(--z-accent))" }}
                />
              </span>
              GO
              <span className="ml-1.5 font-medium text-z-ink-muted text-[0.85em]">
                WebIQ
              </span>
            </span>
          </div>
          <p className="mt-2 text-sm text-z-ink-secondary">
            Sign in to continue
          </p>
        </div>

        <Suspense fallback={null}>
          <LoginForm />
        </Suspense>

        <p className="mt-6 text-center text-xs text-z-ink-muted">
          ZuiGO WebIQ · Website intelligence platform
        </p>
      </div>
    </div>
  );
}
