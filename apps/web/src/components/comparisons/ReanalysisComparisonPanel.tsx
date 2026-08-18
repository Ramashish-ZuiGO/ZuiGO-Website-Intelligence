"use client";

import { useEffect, useState } from "react";

import type { ReanalysisSettings } from "@/components/comparisons/types";
import { analysisComparisonApi } from "@/lib/analysis-comparison-api";
import { ENGINE_SHORT_LABELS } from "@/lib/browser-engines";

interface ReanalysisComparisonPanelProps {
  analysisRunId: string;
  projectId?: string;
}

export function ReanalysisComparisonPanel({
  analysisRunId,
  projectId,
}: ReanalysisComparisonPanelProps) {
  const [open, setOpen] = useState(false);
  const [settings, setSettings] = useState<ReanalysisSettings | null>(null);
  const [engines, setEngines] = useState<ReanalysisSettings["browser_engines"]>([]);
  const [includeMobile, setIncludeMobile] = useState(true);
  const [confirmed, setConfirmed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || settings) return;
    void analysisComparisonApi
      .settings(analysisRunId)
      .then((value) => {
        setSettings(value);
        setEngines(value.browser_engines);
        setIncludeMobile(value.include_mobile);
      })
      .catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : "Reanalysis settings are unavailable.");
      });
  }, [analysisRunId, open, settings]);

  function toggleEngine(engine: keyof typeof ENGINE_SHORT_LABELS) {
    setEngines((current) =>
      current.includes(engine)
        ? current.filter((item) => item !== engine)
        : [...current, engine],
    );
  }

  async function submit() {
    if (!settings || !confirmed || engines.length === 0) return;
    setSubmitting(true);
    setError(null);
    try {
      const result = await analysisComparisonApi.reanalyse(analysisRunId, {
        confirmed: true,
        idempotency_key: `reanalysis-${analysisRunId}-${crypto.randomUUID()}`,
        browser_engines: engines,
        include_mobile: includeMobile,
        max_concurrency: settings.max_concurrency,
      });
      const query = new URLSearchParams({
        websiteId: settings.website_id,
        workflowExecutionId: result.workflow_execution_id,
        baselineRunId: analysisRunId,
      });
      if (projectId) query.set("projectId", projectId);
      window.location.assign(`/analysis-runs/${result.analysis_run_id}?${query.toString()}`);
    } catch (reason: unknown) {
      let message = "The reanalysis could not be started.";
      if (reason instanceof Error) {
        message = reason.message;
        const details = (reason as unknown as Record<string, unknown>).details;
        if (Array.isArray(details) && details.length > 0) {
          const fields = details
            .map((d: Record<string, unknown>) => `${d.field}: ${d.message}`)
            .join("; ");
          message = `${message} (${fields})`;
        }
      }
      setError(message);
      setSubmitting(false);
    }
  }

  return (
    <section className="mt-6 rounded-2xl border border-blue-200 bg-blue-50 p-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-slate-950">Measure progress over time</h2>
          <p className="mt-1 text-sm text-slate-700">
            Run the same eight-agent analysis again and compare retained evidence.
          </p>
        </div>
        <button
          className="rounded-lg bg-blue-800 px-4 py-2 font-semibold text-white focus-visible:outline focus-visible:outline-4 focus-visible:outline-offset-2 focus-visible:outline-blue-800"
          onClick={() => setOpen((value) => !value)}
          type="button"
        >
          Re-analyse website
        </button>
      </div>
      {open && (
        <form
          aria-label="Review reanalysis settings"
          className="mt-5 grid gap-4 rounded-xl bg-white p-5"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          {!settings && !error && <p role="status">Loading the previous settings…</p>}
          {settings && (
            <>
              <dl className="grid gap-3 text-sm sm:grid-cols-2">
                <div>
                  <dt className="font-semibold">Website</dt>
                  <dd className="break-all">{settings.website_url}</dd>
                </div>
                <div>
                  <dt className="font-semibold">Baseline analysis</dt>
                  <dd>{new Date(settings.baseline_created_at).toLocaleString()}</dd>
                </div>
              </dl>
              <fieldset>
                <legend className="font-semibold">Browser engines</legend>
                <div className="mt-2 flex flex-wrap gap-4">
                  {Object.entries(ENGINE_SHORT_LABELS).map(([engine, label]) => (
                    <label className="flex items-center gap-2" key={engine}>
                      <input
                        checked={engines.includes(engine as keyof typeof ENGINE_SHORT_LABELS)}
                        onChange={() => toggleEngine(engine as keyof typeof ENGINE_SHORT_LABELS)}
                        type="checkbox"
                      />
                      {label}
                    </label>
                  ))}
                </div>
                {engines.length === 0 && (
                  <p className="mt-1 text-sm text-red-700">Select at least one browser.</p>
                )}
              </fieldset>
              <label className="flex items-center gap-2">
                <input
                  checked={includeMobile}
                  onChange={(event) => setIncludeMobile(event.target.checked)}
                  type="checkbox"
                />
                Include mobile analysis
              </label>
              <label className="flex items-start gap-2 rounded-lg bg-amber-50 p-3">
                <input
                  checked={confirmed}
                  className="mt-1"
                  onChange={(event) => setConfirmed(event.target.checked)}
                  type="checkbox"
                />
                <span>
                  I understand this creates a new independent analysis. The baseline remains
                  unchanged.
                </span>
              </label>
              <button
                className="w-fit rounded-lg bg-slate-950 px-4 py-2 font-semibold text-white disabled:opacity-50"
                disabled={!confirmed || engines.length === 0 || submitting}
                type="submit"
              >
                {submitting ? "Starting reanalysis…" : "Confirm and start"}
              </button>
            </>
          )}
          {error && <p className="text-red-700" role="alert">{error}</p>}
        </form>
      )}
    </section>
  );
}
