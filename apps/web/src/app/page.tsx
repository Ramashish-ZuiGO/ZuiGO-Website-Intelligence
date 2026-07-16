"use client";

import { useEffect, useState } from "react";

type HealthStatus = "loading" | "healthy" | "error";

interface HealthResponse {
  status: string;
  service: string;
}

export default function Home() {
  const [healthStatus, setHealthStatus] = useState<HealthStatus>("loading");
  const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

  useEffect(() => {
    const controller = new AbortController();

    async function checkApiHealth() {
      try {
        const response = await fetch(`${apiUrl}/health`, { signal: controller.signal });
        if (!response.ok) throw new Error(`API returned ${response.status}`);

        const health: HealthResponse = await response.json();
        setHealthStatus(health.status === "healthy" ? "healthy" : "error");
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setHealthStatus("error");
      }
    }

    void checkApiHealth();
    return () => controller.abort();
  }, [apiUrl]);

  return (
    <main className="flex min-h-screen items-center justify-center px-6">
      <section className="w-full max-w-2xl rounded-2xl border border-slate-200 bg-white p-10 shadow-sm">
        <p className="mb-3 text-sm font-semibold uppercase tracking-[0.18em] text-slate-500">
          Platform foundation
        </p>
        <h1 className="text-4xl font-bold tracking-tight text-slate-950">
          ZuiGO Website Intelligence
        </h1>
        <p className="mt-4 text-lg leading-8 text-slate-600">
          The frontend foundation is running. Backend connectivity is shown below.
        </p>

        <div className="mt-8 rounded-xl bg-slate-50 p-5" aria-live="polite">
          <p className="text-sm font-medium text-slate-600">API status</p>
          {healthStatus === "loading" && (
            <p className="mt-2 font-semibold text-amber-700">Checking API connectivity…</p>
          )}
          {healthStatus === "healthy" && (
            <p className="mt-2 font-semibold text-emerald-700">API is reachable and healthy.</p>
          )}
          {healthStatus === "error" && (
            <p className="mt-2 font-semibold text-red-700">
              API is currently unreachable. Confirm the Docker services are running.
            </p>
          )}
        </div>
      </section>
    </main>
  );
}
