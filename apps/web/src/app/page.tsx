"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useRef, useState } from "react";
import { Globe, Search, Loader2, Monitor, AlertTriangle, ExternalLink } from "lucide-react";

import type { RecentRealAnalysis } from "@/components/reports/types";
import { ApiError } from "@/lib/api";
import { reportDeliveryApi } from "@/lib/report-delivery-api";
import { StatusBadge } from "@/components/ui/StatusBadge";

type BrowserEngine = "chromium" | "firefox" | "webkit";

const ENGINE_OPTIONS: Array<{
  value: BrowserEngine;
  label: string;
  description: string;
}> = [
  {
    value: "chromium",
    label: "Chromium",
    description: "Chrome engine",
  },
  {
    value: "firefox",
    label: "Firefox",
    description: "Gecko engine",
  },
  {
    value: "webkit",
    label: "WebKit",
    description: "Safari engine",
  },
];

function humanStatus(value: string | null | undefined): string {
  if (!value) return "unknown";
  return value.replaceAll("_", " ");
}

export default function Home() {
  const router = useRouter();
  const idempotencyKey = useRef("");
  const [websiteUrl, setWebsiteUrl] = useState("");
  const [engines, setEngines] = useState<BrowserEngine[]>([
    "chromium",
    "firefox",
    "webkit",
  ]);
  const [includeMobile, setIncludeMobile] = useState(true);
  const [recent, setRecent] = useState<RecentRealAnalysis[]>([]);
  const [loadingRecent, setLoadingRecent] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void reportDeliveryApi
      .recentRealAnalyses()
      .then((items) => {
        if (!cancelled) setRecent(items);
      })
      .catch(() => {
        if (!cancelled) setRecent([]);
      })
      .finally(() => {
        if (!cancelled) setLoadingRecent(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function toggleEngine(engine: BrowserEngine) {
    setEngines((current) =>
      current.includes(engine)
        ? current.filter((item) => item !== engine)
        : [...current, engine],
    );
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (engines.length === 0) {
      setError("Select at least one browser engine.");
      return;
    }
    setSubmitting(true);
    setError(null);
    if (!idempotencyKey.current) {
      idempotencyKey.current = `real-analysis-${crypto.randomUUID()}`;
    }
    try {
      const started = await reportDeliveryApi.startRealAnalysis({
        website_url: websiteUrl,
        idempotency_key: idempotencyKey.current,
        browser_engines: engines,
        include_mobile: includeMobile,
      });
      idempotencyKey.current = "";
      const query = new URLSearchParams({
        projectId: started.project_id,
        websiteId: started.website_id,
        workflowExecutionId: started.workflow_execution_id,
      });
      router.push(
        `/analysis-runs/${encodeURIComponent(started.analysis_run_id)}?${query.toString()}`,
      );
    } catch (requestError) {
      if (requestError instanceof ApiError) {
        setError(requestError.message);
      } else if (requestError instanceof TypeError) {
        setError(
          "Could not reach the analysis server. Check that the backend is running and try again.",
        );
      } else {
        setError(
          "The analysis could not be started due to an unexpected error. Please try again.",
        );
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main>
      {/* HERO SECTION */}
      <section className="bg-z-dark text-z-ink-inverse pt-12 pb-16 border-b border-z-dark-muted">
        <div className="z-container max-w-4xl mx-auto text-center">
          <h1 className="text-4xl sm:text-5xl font-display font-semibold tracking-tight" style={{ color: "#FFFFFF" }}>
            Understand what is holding your website back.
          </h1>
          <p className="mt-4 text-lg text-z-ink-muted max-w-2xl mx-auto leading-relaxed">
            Enter a public website. ZuiGO discovers its pages, tests retained
            evidence across browser engines, runs eight specialist agents, and
            produces an evidence-grounded report.
          </p>

          <form
            className="mt-8 max-w-2xl mx-auto text-left"
            onSubmit={(event) => void submit(event)}
          >
            <div className="flex flex-col sm:flex-row gap-3">
              <div className="relative flex-1">
                <Globe className="absolute left-4 top-1/2 -translate-y-1/2 h-5 w-5 text-z-ink-muted" aria-hidden="true" />
                <input
                  autoComplete="url"
                  className="w-full bg-z-dark-surface border border-z-dark-muted rounded-md py-3.5 pl-12 pr-4 text-white placeholder-z-ink-muted focus:outline-none focus:ring-2 focus:ring-z-focus-ring focus:border-transparent transition-all"
                  id="website-url"
                  inputMode="url"
                  onChange={(event) => {
                    setWebsiteUrl(event.target.value);
                    idempotencyKey.current = "";
                  }}
                  placeholder="https://example.com"
                  required
                  type="url"
                  value={websiteUrl}
                  disabled={submitting}
                  aria-label="Public website URL"
                />
              </div>
              <button
                className="z-btn z-btn-primary z-btn-lg sm:w-auto w-full h-12"
                disabled={submitting}
                type="submit"
              >
                {submitting ? <Loader2 className="h-5 w-5 animate-spin" /> : <Search className="h-5 w-5" />}
                {submitting ? "Starting..." : "Analyze Website"}
              </button>
            </div>

            <details className="mt-4 group rounded-md border border-z-dark-muted bg-z-dark-surface/50 p-4 text-sm [&_summary::-webkit-details-marker]:hidden">
              <summary className="cursor-pointer font-medium text-z-ink-muted hover:text-white flex items-center gap-2 outline-none focus-visible:ring-2 focus-visible:ring-z-focus-ring rounded-sm w-max">
                <Monitor className="h-4 w-4" />
                Advanced settings
              </summary>
              <div className="mt-4 pt-4 border-t border-z-dark-muted">
                <fieldset>
                  <legend className="font-medium text-white mb-1">Browser engine checks</legend>
                  <p className="text-xs text-z-ink-muted mb-3">
                    Optional rendering-engine checks. Engine results do not represent full branded-browser UAT certification.
                  </p>
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                    {ENGINE_OPTIONS.map((option) => (
                      <label
                        className={`flex flex-col gap-1 p-3 rounded-md border cursor-pointer transition-colors ${
                          engines.includes(option.value)
                            ? "border-z-accent bg-z-accent/10"
                            : "border-z-dark-muted text-z-ink-muted hover:border-z-ink-muted/80 hover:text-white"
                        }`}
                        key={option.value}
                      >
                        <div className="flex items-center gap-2">
                          <input
                            checked={engines.includes(option.value)}
                            className="accent-z-accent h-4 w-4"
                            onChange={() => toggleEngine(option.value)}
                            type="checkbox"
                            disabled={submitting}
                          />
                          <span className={`font-medium ${engines.includes(option.value) ? "text-white" : ""}`}>
                            {option.label}
                          </span>
                        </div>
                      </label>
                    ))}
                  </div>
                </fieldset>
                <label className="mt-4 flex items-center gap-2 text-z-ink-muted hover:text-white cursor-pointer w-max">
                  <input
                    checked={includeMobile}
                    className="accent-z-accent h-4 w-4"
                    onChange={(event) => setIncludeMobile(event.target.checked)}
                    type="checkbox"
                    disabled={submitting}
                  />
                  Include mobile viewport testing at 390 × 844
                </label>
              </div>
            </details>

            {error && (
              <div className="mt-4 p-4 rounded-md bg-z-danger-subtle border border-z-danger/20 text-z-danger text-sm flex items-start gap-3" role="alert">
                <AlertTriangle className="h-5 w-5 shrink-0" />
                <p>{error}</p>
              </div>
            )}

            <p className="mt-4 text-xs text-z-ink-muted text-center sm:text-left">
              Public HTTP/HTTPS sites only. Private networks, localhost, and credential-bearing URLs are blocked.
            </p>
            <div className="mt-8 text-center sm:text-left">
              <Link href="/presentation" className="text-sm font-medium text-z-ink-muted hover:text-white transition-colors flex items-center gap-2 justify-center sm:justify-start">
                <Monitor className="h-4 w-4" />
                Open Prepared Demo
              </Link>
            </div>
          </form>
        </div>
      </section>

      {/* RECENT ANALYSES SECTION */}
      <section className="z-container py-16">
        <div className="max-w-5xl mx-auto">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
            <div>
              <h2 className="text-xl font-display font-semibold text-z-ink">Recent analyses</h2>
              <p className="mt-1 text-sm text-z-ink-secondary">
                Review previous website analyses and reports.
              </p>
            </div>
          </div>

          {loadingRecent ? (
            <div className="z-card text-center py-16 text-z-ink-muted">
              <Loader2 className="h-8 w-8 animate-spin mx-auto mb-3" />
              <p>Loading recent analyses…</p>
            </div>
          ) : recent.length === 0 ? (
            <div className="z-card text-center py-16">
              <Globe className="h-10 w-10 text-z-border-strong mx-auto mb-3" />
              <p className="text-z-ink-secondary">No analysis has been submitted yet.</p>
            </div>
          ) : (
            <div className="z-card p-0 overflow-x-auto">
              <table className="w-full text-left whitespace-nowrap">
                <thead className="bg-z-surface-muted border-b border-z-border text-xs font-semibold text-z-ink-secondary uppercase tracking-wider">
                  <tr>
                    <th className="px-6 py-4">Website</th>
                    <th className="px-6 py-4">Status</th>
                    <th className="px-6 py-4">Date Started</th>
                    <th className="px-6 py-4 text-right">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-z-border">
                  {recent.map((item) => {
                    const query = new URLSearchParams({
                      projectId: item.project_id,
                      websiteId: item.website_id,
                      workflowExecutionId: item.workflow_execution_id,
                    });

                    return (
                      <tr key={item.workflow_execution_id} className="hover:bg-z-surface-muted transition-colors group">
                        <td className="px-6 py-4">
                          <span className="font-medium text-z-ink z-mono">{item.normalized_url}</span>
                        </td>
                        <td className="px-6 py-4">
                          <StatusBadge
                            status={
                              item.status === "completed" ? "passed" :
                              item.status === "failed" ? "failed" :
                              item.status === "pending" || item.status === "queued" ? "queued" :
                              "running"
                            }
                            label={humanStatus(item.status)}
                          />
                        </td>
                        <td className="px-6 py-4 text-sm text-z-ink-secondary">
                          {new Date(item.created_at).toLocaleString()}
                        </td>
                        <td className="px-6 py-4 text-right">
                          <Link
                            className="inline-flex items-center gap-1.5 text-sm font-medium text-z-accent hover:text-z-accent-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-z-focus-ring rounded-sm"
                            href={`/analysis-runs/${item.analysis_run_id}?${query.toString()}`}
                          >
                            View Report
                            <ExternalLink className="h-4 w-4" />
                          </Link>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>
    </main>
  );
}
