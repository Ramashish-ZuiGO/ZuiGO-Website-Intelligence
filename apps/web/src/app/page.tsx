"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useRef, useState } from "react";

import type { RecentRealAnalysis } from "@/components/reports/types";
import { ApiError } from "@/lib/api";
import { reportDeliveryApi } from "@/lib/report-delivery-api";

type BrowserEngine = "chromium" | "firefox" | "webkit";

const ENGINE_OPTIONS: Array<{
  value: BrowserEngine;
  label: string;
  description: string;
}> = [
  {
    value: "chromium",
    label: "Chromium engine",
    description: "Chrome-family rendering evidence",
  },
  {
    value: "firefox",
    label: "Firefox engine",
    description: "Gecko rendering evidence",
  },
  {
    value: "webkit",
    label: "WebKit engine",
    description: "Safari-family rendering evidence",
  },
];

function humanStatus(value: string): string {
  return value.replaceAll("_", " ");
}

export default function Home() {
  const router = useRouter();
  const idempotencyKey = useRef("");
  const [websiteUrl, setWebsiteUrl] = useState("");
  const [maximumPages, setMaximumPages] = useState(10);
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
        maximum_pages: maximumPages,
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
      setError(
        requestError instanceof ApiError
          ? requestError.message
          : "The analysis could not be started. Try again without changing the URL.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="min-h-screen bg-slate-50 text-slate-950">
      <section className="bg-slate-950 px-6 py-16 text-white">
        <div className="mx-auto max-w-6xl">
          <p className="text-sm font-black uppercase tracking-[0.2em] text-orange-300">
            ZuiGO Website Intelligence
          </p>
          <div className="mt-5 grid gap-10 lg:grid-cols-[1fr_28rem] lg:items-start">
            <div>
              <h1 className="max-w-3xl text-4xl font-black leading-tight sm:text-6xl">
                Understand what is holding your website back.
              </h1>
              <p className="mt-5 max-w-2xl text-lg leading-8 text-slate-200">
                Enter a public website. ZuiGO discovers its pages, tests retained
                evidence across browser engines, runs eight specialist agents, and
                produces an evidence-grounded report.
              </p>
              <ul className="mt-7 grid gap-2 text-sm text-slate-200 sm:grid-cols-2">
                <li>✓ Exact affected pages and evidence</li>
                <li>✓ Chromium, Firefox, and WebKit engines</li>
                <li>✓ Explainable scores and action plan</li>
                <li>✓ Accessible HTML, PDF, JSON, and appendix exports</li>
              </ul>
            </div>

            <form
              className="rounded-2xl bg-white p-6 text-slate-950 shadow-2xl"
              onSubmit={(event) => void submit(event)}
            >
              <h2 className="text-xl font-black">Start website analysis</h2>
              <label className="mt-5 block text-sm font-bold" htmlFor="website-url">
                Public website URL
              </label>
              <input
                autoComplete="url"
                className="mt-2 w-full rounded-lg border border-slate-400 px-4 py-3 focus-visible:outline-4 focus-visible:outline-offset-2 focus-visible:outline-orange-600"
                id="website-url"
                inputMode="url"
                onChange={(event) => {
                  setWebsiteUrl(event.target.value);
                  idempotencyKey.current = "";
                }}
                placeholder="example.com"
                required
                type="text"
                value={websiteUrl}
              />
              <label className="mt-5 block text-sm font-bold" htmlFor="maximum-pages">
                Maximum pages: {maximumPages}
              </label>
              <input
                className="mt-2 w-full accent-orange-600"
                id="maximum-pages"
                max={50}
                min={1}
                onChange={(event) => setMaximumPages(Number(event.target.value))}
                type="range"
                value={maximumPages}
              />

              <details className="mt-5 rounded-lg border border-slate-300 p-4">
                <summary className="cursor-pointer font-bold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-600">
                  Advanced settings
                </summary>
                <fieldset className="mt-4">
                  <legend className="font-bold">Browser-engine tests</legend>
                  <div className="mt-2 grid gap-2">
                    {ENGINE_OPTIONS.map((option) => (
                      <label
                        className="flex cursor-pointer gap-3 rounded-lg border p-3"
                        key={option.value}
                      >
                        <input
                          checked={engines.includes(option.value)}
                          className="mt-1 accent-orange-600"
                          onChange={() => toggleEngine(option.value)}
                          type="checkbox"
                        />
                        <span>
                          <strong>{option.label}</strong>
                          <span className="block text-xs text-slate-600">
                            {option.description}
                          </span>
                        </span>
                      </label>
                    ))}
                  </div>
                </fieldset>
                <label className="mt-4 flex gap-3 text-sm">
                  <input
                    checked={includeMobile}
                    className="accent-orange-600"
                    onChange={(event) => setIncludeMobile(event.target.checked)}
                    type="checkbox"
                  />
                  Include mobile viewport testing at 390 × 844
                </label>
              </details>

              {error && (
                <p className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-800" role="alert">
                  {error}
                </p>
              )}
              <button
                className="mt-5 w-full rounded-lg bg-orange-500 px-5 py-3 font-black text-slate-950 disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-4 focus-visible:outline-offset-4 focus-visible:outline-slate-950"
                disabled={submitting}
                type="submit"
              >
                {submitting ? "Starting real analysis…" : "Start Website Analysis"}
              </button>
              <p className="mt-3 text-xs text-slate-600">
                Public HTTP/HTTPS sites only. Private networks, localhost, metadata
                endpoints, unsafe redirects, and credential-bearing URLs are blocked.
              </p>
            </form>
          </div>
        </div>
      </section>

      <section className="mx-auto grid max-w-6xl gap-8 px-6 py-12 lg:grid-cols-[1fr_20rem]">
        <div>
          <h2 className="text-2xl font-black">Recent real analyses</h2>
          <p className="mt-2 text-slate-600">
            Historical runs remain independent and preserve their original evidence.
          </p>
          {loadingRecent ? (
            <p className="mt-5" role="status">Loading recent analyses…</p>
          ) : recent.length === 0 ? (
            <p className="mt-5 rounded-xl border bg-white p-5 text-slate-600">
              No real analysis has been submitted yet.
            </p>
          ) : (
            <ul className="mt-5 grid gap-3">
              {recent.map((item) => {
                const query = new URLSearchParams({
                  projectId: item.project_id,
                  websiteId: item.website_id,
                  workflowExecutionId: item.workflow_execution_id,
                });
                return (
                  <li className="rounded-xl border bg-white p-4" key={item.workflow_execution_id}>
                    <Link
                      className="font-bold underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-600"
                      href={`/analysis-runs/${item.analysis_run_id}?${query.toString()}`}
                    >
                      {item.normalized_url}
                    </Link>
                    <p className="mt-1 text-sm capitalize text-slate-600">
                      {humanStatus(item.status)} · {new Date(item.created_at).toLocaleString()}
                    </p>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
        <aside className="rounded-2xl border border-blue-200 bg-blue-50 p-5">
          <h2 className="font-black">Need a predictable walkthrough?</h2>
          <p className="mt-2 text-sm text-slate-700">
            The prepared demonstration is separate from real analyses and opens only
            when you choose it.
          </p>
          <Link
            aria-label="Open presentation mode: prepared demo"
            className="mt-4 inline-flex rounded-lg border border-blue-900 px-4 py-2 text-sm font-bold text-blue-950 focus-visible:outline-4 focus-visible:outline-offset-2 focus-visible:outline-orange-600"
            href="/presentation"
          >
            Open Prepared Demo
          </Link>
        </aside>
      </section>
    </main>
  );
}
