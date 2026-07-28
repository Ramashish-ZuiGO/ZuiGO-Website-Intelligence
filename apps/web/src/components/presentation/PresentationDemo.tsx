"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";

import { ReportDeliveryPanel } from "@/components/reports/ReportDeliveryPanel";
import type {
  DemoStage,
  PresentationDemo as PresentationDemoData,
} from "@/components/presentation/types";
import { presentationDemoApi } from "@/lib/presentation-demo-api";

const IDEMPOTENCY_STORAGE_KEY = "zuigo:presentation-demo:execution-key:v1";
const REQUEST_TIMEOUT_MS = 12_000;
const PROGRESS_STEP_MS = 220;
const PREVIEW_STAGES: DemoStage[] = [
  {
    stage_id: "discovery",
    name: "Discovery",
    agent_ids: ["discovery_agent"],
    parallel: false,
    status: "pending",
  },
  {
    stage_id: "parallel_analysis",
    name: "Performance, accessibility, and site diagnostics",
    agent_ids: [
      "performance_agent",
      "accessibility_agent",
      "site_diagnostics_agent",
    ],
    parallel: true,
    status: "pending",
  },
  {
    stage_id: "evidence_validation",
    name: "Evidence validation",
    agent_ids: ["evidence_validation_agent"],
    parallel: false,
    status: "pending",
  },
  {
    stage_id: "repository_intelligence",
    name: "Repository intelligence",
    agent_ids: ["repository_intelligence_agent"],
    parallel: false,
    status: "pending",
  },
  {
    stage_id: "remediation",
    name: "Remediation",
    agent_ids: ["remediation_agent"],
    parallel: false,
    status: "pending",
  },
  {
    stage_id: "report",
    name: "Report",
    agent_ids: ["report_agent"],
    parallel: false,
    status: "pending",
  },
];

type ScreenState =
  | "loading"
  | "idle"
  | "running"
  | "ready"
  | "completed"
  | "partial"
  | "failed"
  | "fallback"
  | "resetting"
  | "error";

function createExecutionKey(): string {
  const existing = window.localStorage.getItem(IDEMPOTENCY_STORAGE_KEY);
  if (existing) return existing;
  const value = `presentation-${crypto.randomUUID()}`;
  window.localStorage.setItem(IDEMPOTENCY_STORAGE_KEY, value);
  return value;
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

function humanize(value: string): string {
  return value.replaceAll("_", " ");
}

function statusClass(status: string): string {
  if (status === "completed" || status === "available") {
    return "border-emerald-300 bg-emerald-50 text-emerald-900";
  }
  if (status === "failed") return "border-red-300 bg-red-50 text-red-900";
  if (status === "running") return "border-blue-300 bg-blue-50 text-blue-900";
  return "border-amber-300 bg-amber-50 text-amber-950";
}

function StageFlow({
  stages,
  currentIndex,
  running,
}: {
  stages: DemoStage[];
  currentIndex: number;
  running: boolean;
}) {
  return (
    <ol className="mt-5 grid gap-3 lg:grid-cols-6" aria-label="Demo analysis stages">
      {stages.map((stage, index) => {
        const displayedStatus = running
          ? index < currentIndex
            ? "completed"
            : index === currentIndex
              ? "running"
              : "pending"
          : stage.status;
        return (
          <li
            className={`rounded-xl border p-3 ${statusClass(displayedStatus)}`}
            key={stage.stage_id}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs font-black uppercase tracking-wide">
                {index + 1}
              </span>
              <span className="text-xs font-bold uppercase">
                {humanize(displayedStatus)}
              </span>
            </div>
            <h3 className="mt-2 text-sm font-bold">{stage.name}</h3>
            {stage.parallel && (
              <p className="mt-2 text-xs font-semibold">Parallel agent group</p>
            )}
            <ul className="mt-2 space-y-1 text-xs">
              {stage.agent_ids.map((agentId) => (
                <li key={agentId}>{humanize(agentId)}</li>
              ))}
            </ul>
          </li>
        );
      })}
    </ol>
  );
}

export function PresentationDemo() {
  const [data, setData] = useState<PresentationDemoData | null>(null);
  const [screenState, setScreenState] = useState<ScreenState>("loading");
  const [currentStage, setCurrentStage] = useState(-1);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    presentationDemoApi
      .status(controller.signal)
      .then((result) => {
        if (!mounted.current) return;
        setData(result.prepared ? result : null);
        setScreenState(result.prepared ? "ready" : "idle");
      })
      .catch(() => {
        if (!mounted.current || controller.signal.aborted) return;
        setScreenState("idle");
      });
    return () => {
      mounted.current = false;
      controller.abort();
    };
  }, []);

  async function openPrepared() {
    setError(null);
    setScreenState("loading");
    try {
      const result = await presentationDemoApi.prepare();
      setData(result);
      setCurrentStage(result.stages.length - 1);
      setScreenState("ready");
    } catch {
      setError(
        "The prepared report could not be opened. Confirm that the local API is running.",
      );
      setScreenState("error");
    }
  }

  async function runDemo() {
    setError(null);
    setScreenState("running");
    setCurrentStage(0);
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
      const request = presentationDemoApi.run(
        createExecutionKey(),
        controller.signal,
      );
      for (let index = 0; index < PREVIEW_STAGES.length; index += 1) {
        if (!mounted.current) return;
        setCurrentStage(index);
        await delay(PROGRESS_STEP_MS);
      }
      const result = await request;
      if (!mounted.current) return;
      setData(result);
      setCurrentStage(result.stages.length - 1);
      setScreenState(
        result.used_prepared_fallback
          ? "fallback"
          : result.live_execution_status === "failed"
            ? "failed"
            : result.report_status === "partial"
              ? "partial"
              : "completed",
      );
    } catch {
      if (!mounted.current) return;
      try {
        const prepared = await presentationDemoApi.prepare();
        if (!mounted.current) return;
        setData({
          ...prepared,
          presentation_status: "fallback",
          used_prepared_fallback: true,
          status_message:
            "Live demo did not complete. Showing the last verified prepared fallback report.",
        });
        setCurrentStage(prepared.stages.length - 1);
        setScreenState("fallback");
      } catch {
        setError(
          "The live demo and prepared report are unavailable. No execution is being shown as completed.",
        );
        setScreenState("error");
      }
    } finally {
      window.clearTimeout(timeout);
    }
  }

  async function resetDemo() {
    setError(null);
    setScreenState("resetting");
    try {
      await presentationDemoApi.reset();
      window.localStorage.removeItem(IDEMPOTENCY_STORAGE_KEY);
      setData(null);
      setCurrentStage(-1);
      setScreenState("idle");
    } catch {
      setError("The managed demo data could not be reset. No other project was changed.");
      setScreenState("error");
    }
  }

  const stages = data?.stages.length ? data.stages : PREVIEW_STAGES;
  const progress =
    currentStage < 0
      ? 0
      : Math.min(100, Math.round(((currentStage + 1) / stages.length) * 100));
  const busy = ["loading", "running", "resetting"].includes(screenState);

  return (
    <main className="min-h-screen bg-slate-950 text-slate-100">
      <div className="mx-auto max-w-[1500px] px-5 py-8 lg:px-10">
        <header className="rounded-3xl border border-white/10 bg-gradient-to-br from-slate-900 via-slate-900 to-blue-950 p-6 shadow-2xl lg:p-10">
          <div className="flex flex-wrap items-start justify-between gap-6">
            <div>
              <p className="text-sm font-black uppercase tracking-[0.24em] text-orange-400">
                ZuiGO presentation mode
              </p>
              <h1 className="mt-3 text-4xl font-black tracking-tight lg:text-6xl">
                Website intelligence, with the evidence visible
              </h1>
              <p className="mt-4 max-w-3xl text-lg leading-8 text-slate-300">
                A deterministic local demonstration of eight agents moving from
                discovery to an evidence-grounded, exportable report.
              </p>
            </div>
            <Link
              className="rounded-lg border border-slate-500 px-4 py-2 font-semibold focus-visible:outline-4 focus-visible:outline-offset-4 focus-visible:outline-orange-400"
              href="/"
            >
              Exit presentation mode
            </Link>
          </div>

          <div className="mt-8 flex flex-wrap gap-3" aria-label="Demo controls">
            <button
              className="rounded-lg bg-orange-500 px-5 py-3 font-black text-slate-950 shadow focus-visible:outline-4 focus-visible:outline-offset-4 focus-visible:outline-white disabled:cursor-not-allowed disabled:opacity-50"
              disabled={busy}
              onClick={() => void runDemo()}
              type="button"
            >
              Run Demo Analysis
            </button>
            <button
              className="rounded-lg border border-slate-400 bg-white/5 px-5 py-3 font-bold focus-visible:outline-4 focus-visible:outline-offset-4 focus-visible:outline-orange-400 disabled:cursor-not-allowed disabled:opacity-50"
              disabled={busy}
              onClick={() => void openPrepared()}
              type="button"
            >
              Open Prepared Demo Report
            </button>
            <button
              className="rounded-lg border border-red-400 px-5 py-3 font-bold text-red-100 focus-visible:outline-4 focus-visible:outline-offset-4 focus-visible:outline-red-300 disabled:cursor-not-allowed disabled:opacity-50"
              disabled={busy || !data}
              onClick={() => void resetDemo()}
              type="button"
            >
              Reset Demo
            </button>
          </div>

          <div
            className="mt-6 rounded-xl border border-white/10 bg-black/20 p-4"
            aria-atomic="true"
            aria-live="polite"
            role={error ? "alert" : "status"}
          >
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="font-bold">
                {error ??
                  (screenState === "loading"
                    ? "Loading prepared demo status…"
                    : screenState === "running"
                      ? `Running deterministic stage ${currentStage + 1} of ${stages.length}.`
                      : screenState === "resetting"
                        ? "Resetting managed demo data…"
                        : data?.status_message ??
                          "Choose a demo action. No analysis has been claimed yet.")}
              </p>
              <span className="rounded-full border border-white/20 px-3 py-1 text-sm font-bold uppercase">
                {humanize(screenState)}
              </span>
            </div>
            {screenState === "running" && (
              <div className="mt-3">
                <div className="h-3 overflow-hidden rounded-full bg-slate-700">
                  <div
                    className="h-full bg-orange-400 transition-[width]"
                    style={{ width: `${progress}%` }}
                  />
                </div>
                <p className="mt-2 text-sm">{progress}% workflow progress</p>
              </div>
            )}
          </div>
        </header>

        <section className="mt-7" aria-labelledby="workflow-heading">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <p className="text-sm font-bold uppercase tracking-wider text-blue-300">
                Orchestrated workflow
              </p>
              <h2 className="mt-1 text-2xl font-black" id="workflow-heading">
                Six visible stages, including one parallel agent group
              </h2>
            </div>
            <p className="text-sm text-slate-300">
              Unavailable evidence remains explicitly unavailable.
            </p>
          </div>
          <StageFlow
            currentIndex={currentStage}
            running={screenState === "running"}
            stages={stages}
          />
        </section>

        {data && (
          <>
            {data.used_prepared_fallback && (
              <aside
                className="mt-7 rounded-xl border-2 border-amber-400 bg-amber-950/50 p-5"
                role="note"
              >
                <h2 className="text-xl font-black">Prepared fallback report</h2>
                <p className="mt-2">
                  The live execution status is{" "}
                  <strong>{data.live_execution_status ?? "unavailable"}</strong>. The
                  verified report below is prepared local evidence, not the output of
                  that failed execution.
                </p>
              </aside>
            )}

            <section
              className="mt-7 grid gap-4 md:grid-cols-2 xl:grid-cols-4"
              aria-labelledby="health-heading"
            >
              <h2 className="sr-only" id="health-heading">
                Site health overview
              </h2>
              <div className="rounded-2xl bg-white p-5 text-slate-950">
                <p className="text-sm font-bold uppercase text-slate-500">
                  Overall score
                </p>
                <p className="mt-2 text-5xl font-black">
                  {data.overall_score === null ? "Unavailable" : `${data.overall_score}/100`}
                </p>
                <p className="mt-2 text-sm">
                  Confidence:{" "}
                  {data.score_confidence_percent === null
                    ? "Unavailable"
                    : `${data.score_confidence_percent}%`}
                </p>
              </div>
              <div className="rounded-2xl bg-white p-5 text-slate-950">
                <p className="text-sm font-bold uppercase text-slate-500">
                  Evidence coverage
                </p>
                <p className="mt-2 text-4xl font-black">
                  {data.evidence_coverage_numerator}/
                  {data.evidence_coverage_denominator}
                </p>
                <p className="mt-2 text-sm">
                  {data.evidence_coverage_percentage === null
                    ? "Unavailable"
                    : `${data.evidence_coverage_percentage.toFixed(2)}%`}
                </p>
              </div>
              <div className="rounded-2xl bg-white p-5 text-slate-950">
                <p className="text-sm font-bold uppercase text-slate-500">
                  Prepared identity
                </p>
                <p className="mt-2 text-xl font-black">{data.website_name}</p>
                <p className="mt-2 break-all text-sm">{data.website_url}</p>
              </div>
              <div className="rounded-2xl bg-emerald-400 p-5 text-emerald-950">
                <p className="text-sm font-bold uppercase">Report status</p>
                <p className="mt-2 text-3xl font-black">
                  {data.report_ready ? "Report ready" : "Not ready"}
                </p>
                <p className="mt-2 text-sm">
                  Evidence state: {humanize(data.report_status ?? "unavailable")}
                </p>
              </div>
            </section>

            <section className="mt-7" aria-labelledby="agents-heading">
              <h2 className="text-2xl font-black" id="agents-heading">
                Eight reusable agents and their contributions
              </h2>
              <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                {data.agents.map((agent) => (
                  <article
                    className="rounded-xl border border-slate-700 bg-slate-900 p-4"
                    key={agent.agent_id}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <h3 className="font-black">{agent.name}</h3>
                      <span
                        className={`rounded-full border px-2 py-1 text-xs font-bold uppercase ${statusClass(agent.status)}`}
                      >
                        {humanize(agent.status)}
                      </span>
                    </div>
                    <p className="mt-3 text-sm leading-6 text-slate-300">
                      {agent.contribution}
                    </p>
                    <p className="mt-3 text-xs text-slate-400">
                      Tools: {agent.tool_ids.join(", ")}
                    </p>
                  </article>
                ))}
              </div>
            </section>

            <div className="mt-7 grid gap-5 lg:grid-cols-2">
              <section
                className="rounded-2xl bg-white p-5 text-slate-950"
                aria-labelledby="findings-heading"
              >
                <h2 className="text-2xl font-black" id="findings-heading">
                  Top findings
                </h2>
                <ol className="mt-4 space-y-3">
                  {data.top_findings.map((finding) => (
                    <li
                      className="rounded-lg border border-slate-200 p-4"
                      key={finding.finding_id}
                    >
                      <div className="flex flex-wrap justify-between gap-2">
                        <h3 className="font-bold">{finding.title}</h3>
                        <span className="text-sm font-black uppercase">
                          {finding.severity}
                        </span>
                      </div>
                      <p className="mt-2 break-all text-sm">{finding.page_url}</p>
                      <p className="mt-1 text-sm">
                        Evidence: {humanize(finding.evidence_state)}
                      </p>
                    </li>
                  ))}
                </ol>
              </section>
              <section
                className="rounded-2xl bg-white p-5 text-slate-950"
                aria-labelledby="actions-heading"
              >
                <h2 className="text-2xl font-black" id="actions-heading">
                  Priority action plan
                </h2>
                <ol className="mt-4 space-y-3">
                  {data.top_actions.map((action) => (
                    <li
                      className="rounded-lg border border-slate-200 p-4"
                      key={action.action_id}
                    >
                      <div className="flex flex-wrap justify-between gap-2">
                        <h3 className="font-bold">{action.title}</h3>
                        <span className="font-black">
                          Priority {action.priority_score}/100
                        </span>
                      </div>
                      <p className="mt-2 text-sm">
                        Owner: {action.responsible_role}
                      </p>
                      <p className="mt-1 text-sm">
                        Verify: {action.verification}
                      </p>
                    </li>
                  ))}
                </ol>
              </section>
            </div>

            <section
              className="mt-7 rounded-2xl border border-slate-700 bg-slate-900 p-5"
              aria-labelledby="exports-heading"
            >
              <h2 className="text-2xl font-black" id="exports-heading">
                Verified report exports
              </h2>
              <p className="mt-2 text-slate-300">
                Each export has a stable safe filename and a retained SHA-256 checksum.
              </p>
              <div className="mt-4 flex flex-wrap gap-3">
                {data.artifacts.map((artifact) => (
                  <a
                    className="rounded-lg bg-white px-4 py-3 font-black text-slate-950 focus-visible:outline-4 focus-visible:outline-offset-4 focus-visible:outline-orange-400"
                    href={presentationDemoApi.artifactUrl(artifact.download_url)}
                    key={artifact.format}
                  >
                    Download {artifact.format.toUpperCase()}
                    <span className="sr-only">
                      , {artifact.size_bytes} bytes, SHA-256 {artifact.checksum_sha256}
                    </span>
                  </a>
                ))}
              </div>
            </section>

            {data.report_ready &&
              data.website_id &&
              data.analysis_run_id &&
              data.workflow_execution_id && (
                <section
                  className="mt-7 rounded-2xl bg-slate-100 p-4 text-slate-950 lg:p-6"
                  aria-labelledby="report-viewer-heading"
                >
                  <h2 className="mb-4 text-2xl font-black" id="report-viewer-heading">
                    Prepared report viewer
                  </h2>
                  <ReportDeliveryPanel
                    analysisRunId={data.analysis_run_id}
                    compact
                    projectId={data.project_id ?? undefined}
                    showStartAction={false}
                    websiteId={data.website_id}
                    workflowExecutionId={data.workflow_execution_id}
                  />
                </section>
              )}
          </>
        )}
      </div>
    </main>
  );
}
