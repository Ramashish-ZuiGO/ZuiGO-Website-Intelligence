"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import type {
  DemoArtifact,
  DemoFinding,
  DemoStage,
  PageInventoryItem,
  PresentationDemo as PresentationDemoData,
} from "@/components/presentation/types";
import { presentationDemoApi } from "@/lib/presentation-demo-api";

const IDEMPOTENCY_STORAGE_KEY = "zuigo:presentation-demo:execution-key:v2";
const REQUEST_TIMEOUT_MS = 12_000;
const PAGE_SIZE = 5;
const TABS = [
  "Overview",
  "Pages",
  "Browser Compatibility",
  "Findings",
  "Action Plan",
  "Scores",
  "Agents",
  "Technical Details",
] as const;
type Tab = (typeof TABS)[number];
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

function createExecutionKey(): string {
  const existing = window.localStorage.getItem(IDEMPOTENCY_STORAGE_KEY);
  if (existing) return existing;
  const key = `presentation-${crypto.randomUUID()}`;
  window.localStorage.setItem(IDEMPOTENCY_STORAGE_KEY, key);
  return key;
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

function humanize(value: string): string {
  return value.replaceAll("_", " ");
}

function statusClass(status: string): string {
  if (["completed", "available", "compatible"].includes(status)) {
    return "border-emerald-300 bg-emerald-50 text-emerald-950";
  }
  if (["failed", "incompatible"].includes(status)) {
    return "border-red-300 bg-red-50 text-red-950";
  }
  if (status === "running") return "border-blue-300 bg-blue-50 text-blue-950";
  return "border-amber-300 bg-amber-50 text-amber-950";
}

function ExportLink({
  artifact,
  primary = false,
}: {
  artifact: DemoArtifact;
  primary?: boolean;
}) {
  return (
    <a
      aria-label={primary ? "Export Presentation PDF" : artifact.label}
      className={`rounded-lg px-4 py-3 text-sm font-bold focus-visible:outline-4 focus-visible:outline-offset-4 focus-visible:outline-orange-500 ${
        primary
          ? "bg-orange-500 text-slate-950"
          : "border border-slate-400 bg-white text-slate-950"
      }`}
      href={presentationDemoApi.artifactUrl(artifact.download_url)}
    >
      {artifact.label}
      <span className="sr-only">
        , {artifact.size_bytes} bytes, checksum {artifact.checksum_sha256}
      </span>
    </a>
  );
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
    <ol className="grid gap-2 md:grid-cols-3 xl:grid-cols-6" aria-label="Analysis stages">
      {stages.map((stage, index) => {
        const status = running
          ? index < currentIndex
            ? "completed"
            : index === currentIndex
              ? "running"
              : "pending"
          : stage.status;
        return (
          <li className={`rounded-lg border p-3 ${statusClass(status)}`} key={stage.stage_id}>
            <p className="text-xs font-bold uppercase">
              Stage {index + 1} - {humanize(status)}
            </p>
            <p className="mt-1 text-sm font-bold">{stage.name}</p>
            {stage.parallel && <p className="mt-1 text-xs">Parallel agent group</p>}
          </li>
        );
      })}
    </ol>
  );
}

function FindingCard({ finding }: { finding: DemoFinding }) {
  return (
    <article className="rounded-xl border border-slate-200 bg-white p-5 text-slate-950">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-bold uppercase text-slate-500">
            {finding.affected_page_count} affected page(s) - {finding.occurrence_count} occurrence(s)
          </p>
          <h3 className="mt-1 text-lg font-black">{finding.title}</h3>
        </div>
        <span className={`rounded-full border px-3 py-1 text-xs font-black uppercase ${statusClass(
          finding.severity === "critical" || finding.severity === "high"
            ? "failed"
            : "partial",
        )}`}>
          {finding.severity}
        </span>
      </div>
      <p className="mt-3">{finding.plain_language_explanation}</p>
      <p className="mt-2"><strong>Why it matters:</strong> {finding.why_it_matters}</p>
      <dl className="mt-4 grid gap-3 text-sm md:grid-cols-2">
        <div>
          <dt className="font-bold">Business impact</dt>
          <dd>{finding.business_impact}</dd>
        </div>
        <div>
          <dt className="font-bold">Technical impact</dt>
          <dd>{finding.technical_impact}</dd>
        </div>
        <div>
          <dt className="font-bold">Affected browser engines</dt>
          <dd>{finding.affected_browsers.join(", ") || "No engine-specific failure"}</dd>
        </div>
        <div>
          <dt className="font-bold">Works in tested engines</dt>
          <dd>{finding.works_in_browsers.join(", ") || "Not established"}</dd>
        </div>
      </dl>
      <h4 className="mt-4 font-bold">Example pages</h4>
      <ul className="mt-1 space-y-1 text-sm">
        {finding.example_pages.slice(0, 5).map((url) => (
          <li className="break-all" key={url}>
            {url}
          </li>
        ))}
      </ul>
      {finding.remaining_page_count > 0 && (
        <p className="mt-1 text-sm">and {finding.remaining_page_count} more affected pages</p>
      )}
      <div className="mt-4 rounded-lg bg-slate-50 p-4 text-sm">
        <p><strong>Recommended fix:</strong> {finding.recommended_fix}</p>
        <p className="mt-2"><strong>Owner:</strong> {finding.responsible_role} - effort {finding.estimated_effort}</p>
        <p className="mt-2"><strong>Verify:</strong> {finding.verification}</p>
      </div>
      <details className="mt-4">
        <summary className="cursor-pointer font-bold underline focus-visible:outline-2 focus-visible:outline-orange-600">
          Technical explanation and evidence
        </summary>
        <div className="mt-3 rounded-lg border border-slate-200 p-3 text-sm">
          <p>{finding.technical_explanation}</p>
          <p className="mt-2"><strong>Evidence summary:</strong> {finding.evidence_summary}</p>
          <p className="mt-2"><strong>Source and time:</strong> {finding.evidence_source}, {finding.evidence_timestamp}</p>
          <p className="mt-2"><strong>Detected by:</strong> {finding.detecting_agent}; <strong>validated by:</strong> {finding.validating_agent}</p>
          <p className="mt-2"><strong>Limitations:</strong> {finding.limitations}</p>
        </div>
      </details>
      <details className="mt-4">
        <summary className="cursor-pointer font-bold underline focus-visible:outline-2 focus-visible:outline-orange-600">
          View All Affected Pages
        </summary>
        <div className="mt-3 space-y-3">
          {finding.all_affected_pages.map((page, index) => (
            <article className="rounded-lg border border-slate-200 p-3 text-sm" key={`${page.normalized_url}-${index}`}>
              <p className="break-all font-bold">{page.normalized_url}</p>
              <p>{page.page_title ?? "Page title unavailable"}</p>
              <p><strong>Location:</strong> {page.selector ?? page.resource_url ?? page.location ?? "Not retained"}</p>
              <p><strong>Observed:</strong> {page.observed_value ?? "Unavailable"}</p>
              <p><strong>Expected:</strong> {page.expected_value ?? "Unavailable"}</p>
              <p><strong>Evidence:</strong> {page.analysis_provider}, {page.evidence_timestamp}</p>
            </article>
          ))}
        </div>
      </details>
    </article>
  );
}

function PageInventory({
  pages,
  onOpen,
}: {
  pages: PageInventoryItem[];
  onOpen: (url: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const filtered = useMemo(
    () =>
      pages.filter(
        (page) =>
          (!status || page.analysis_status === status) &&
          (!query || `${page.url} ${page.title}`.toLowerCase().includes(query.toLowerCase())),
      ),
    [pages, query, status],
  );
  const visible = filtered.slice(offset, offset + PAGE_SIZE);
  return (
    <section aria-labelledby="page-inventory-heading">
      <h2 className="text-2xl font-black" id="page-inventory-heading">Page Inventory</h2>
      <p className="mt-2 text-slate-600">Discovered does not mean analysed. Each row shows its retained state.</p>
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <label className="font-bold">Filter pages
          <input className="mt-1 w-full rounded border border-slate-400 px-3 py-2 font-normal focus-visible:outline-2 focus-visible:outline-orange-600" onChange={(event) => { setQuery(event.target.value); setOffset(0); }} type="search" value={query} />
        </label>
        <label className="font-bold">Analysis status
          <select className="mt-1 w-full rounded border border-slate-400 px-3 py-2 font-normal focus-visible:outline-2 focus-visible:outline-orange-600" onChange={(event) => { setStatus(event.target.value); setOffset(0); }} value={status}>
            <option value="">All statuses</option>
            {[...new Set(pages.map((page) => page.analysis_status))].sort().map((item) => <option key={item} value={item}>{humanize(item)}</option>)}
          </select>
        </label>
      </div>
      <p className="mt-3 text-sm font-bold" aria-live="polite">Showing {visible.length} of {filtered.length} matching pages.</p>
      <div className="mt-3 overflow-x-auto">
        <table className="min-w-[1050px] w-full border-collapse text-sm">
          <caption className="sr-only">Page URL, title, type, status, browsers, issues, severity, coverage, and details</caption>
          <thead><tr className="bg-slate-100 text-left">
            {["Page", "Section/type", "HTTP", "Analysis", "Browser engines tested", "Issues", "Highest severity", "Evidence coverage", "Details"].map((heading) => <th className="border border-slate-300 p-2" key={heading} scope="col">{heading}</th>)}
          </tr></thead>
          <tbody>{visible.map((page) => <tr key={page.url}>
            <td className="border border-slate-300 p-2"><strong>{page.title}</strong><br/><span className="break-all">{page.url}</span></td>
            <td className="border border-slate-300 p-2">{page.page_type}</td>
            <td className="border border-slate-300 p-2">{page.http_status ?? "Unavailable"}</td>
            <td className="border border-slate-300 p-2">{humanize(page.analysis_status)}</td>
            <td className="border border-slate-300 p-2">{page.browsers_tested.join(", ") || "Not tested"}</td>
            <td className="border border-slate-300 p-2">{page.issue_count}</td>
            <td className="border border-slate-300 p-2">{page.highest_severity}</td>
            <td className="border border-slate-300 p-2">{page.evidence_coverage_percentage === null ? "Unavailable" : `${page.evidence_coverage_percentage}%`}</td>
            <td className="border border-slate-300 p-2"><button className="font-bold underline focus-visible:outline-2 focus-visible:outline-orange-600" onClick={() => onOpen(page.url)} type="button">View page-level details</button></td>
          </tr>)}</tbody>
        </table>
      </div>
      <div className="mt-4 flex gap-2">
        <button className="rounded border px-3 py-2 disabled:opacity-40" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))} type="button">Previous</button>
        <button className="rounded border px-3 py-2 disabled:opacity-40" disabled={offset + PAGE_SIZE >= filtered.length} onClick={() => setOffset(offset + PAGE_SIZE)} type="button">Next</button>
      </div>
    </section>
  );
}

export function PresentationDemo() {
  const [data, setData] = useState<PresentationDemoData | null>(null);
  const [screenState, setScreenState] = useState<ScreenState>("loading");
  const [activeTab, setActiveTab] = useState<Tab>("Overview");
  const [currentStage, setCurrentStage] = useState(-1);
  const [selectedPage, setSelectedPage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    presentationDemoApi.status(controller.signal).then((result) => {
      if (!mounted.current) return;
      setData(result.prepared ? result : null);
      setScreenState(result.prepared ? "ready" : "idle");
    }).catch(() => {
      if (mounted.current && !controller.signal.aborted) setScreenState("idle");
    });
    return () => { mounted.current = false; controller.abort(); };
  }, []);

  async function openPrepared() {
    setError(null); setScreenState("loading");
    try {
      const result = await presentationDemoApi.prepare();
      setData(result); setCurrentStage(result.stages.length - 1); setScreenState("ready");
    } catch {
      setError("The prepared report could not be opened. Confirm that the local API is running.");
      setScreenState("error");
    }
  }

  async function runDemo() {
    setError(null); setScreenState("running"); setCurrentStage(0);
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
      const request = presentationDemoApi.run(createExecutionKey(), controller.signal);
      for (let index = 0; index < PREVIEW_STAGES.length; index += 1) {
        if (!mounted.current) return;
        setCurrentStage(index);
        await delay(180);
      }
      const result = await request;
      if (!mounted.current) return;
      setData(result); setCurrentStage(result.stages.length - 1);
      setScreenState(result.used_prepared_fallback ? "fallback" : result.report_status === "partial" ? "partial" : "completed");
      setActiveTab("Overview");
    } catch {
      try {
        const prepared = await presentationDemoApi.prepare();
        if (!mounted.current) return;
        setData({ ...prepared, presentation_status: "fallback", used_prepared_fallback: true, status_message: "Live demo did not complete. Showing the last verified prepared fallback report." });
        setScreenState("fallback");
      } catch {
        setError("The live demo and prepared report are unavailable. No execution is being shown as completed.");
        setScreenState("error");
      }
    } finally { window.clearTimeout(timeout); }
  }

  async function resetDemo() {
    setError(null); setScreenState("resetting");
    try {
      await presentationDemoApi.reset();
      window.localStorage.removeItem(IDEMPOTENCY_STORAGE_KEY);
      setData(null); setCurrentStage(-1); setScreenState("idle");
    } catch {
      setError("The managed demo data could not be reset. No other project was changed.");
      setScreenState("error");
    }
  }

  const presentationPdf = data?.artifacts.find((item) => item.kind === "presentation_pdf");
  const busy = ["loading", "running", "resetting"].includes(screenState);
  const stages = data?.stages.length ? data.stages : PREVIEW_STAGES;
  const compatibility = data?.browser_compatibility;

  function openPage(url: string) {
    setSelectedPage(url);
    setActiveTab("Technical Details");
  }

  return (
    <main className="min-h-screen bg-slate-100 text-slate-950">
      <header className="bg-slate-950 text-white">
        <div className="mx-auto max-w-[1440px] px-5 py-7 lg:px-10">
          <div className="flex flex-wrap items-start justify-between gap-5">
            <div><p className="text-sm font-black uppercase tracking-[.22em] text-orange-400">ZuiGO presentation mode</p>
              <h1 className="mt-2 text-3xl font-black lg:text-5xl">Website health, priorities, and proof</h1>
              <p className="mt-3 max-w-3xl text-slate-300">Clear decisions first. Page, browser-engine, and technical evidence remains available on demand.</p>
            </div>
            <Link className="rounded border border-slate-500 px-4 py-2 font-bold focus-visible:outline-4 focus-visible:outline-orange-400" href="/">Exit presentation mode</Link>
          </div>
          <div className="mt-6 flex flex-wrap gap-3" aria-label="Demo controls">
            <button className="rounded-lg bg-orange-500 px-5 py-3 font-black text-slate-950 focus-visible:outline-4 focus-visible:outline-white disabled:opacity-50" disabled={busy} onClick={() => void runDemo()} type="button">Run Demo Analysis</button>
            <button className="rounded-lg border border-slate-400 px-5 py-3 font-bold focus-visible:outline-4 focus-visible:outline-orange-400 disabled:opacity-50" disabled={busy} onClick={() => void openPrepared()} type="button">Open Prepared Demo Report</button>
            <button className="rounded-lg border border-red-400 px-5 py-3 font-bold focus-visible:outline-4 focus-visible:outline-red-300 disabled:opacity-50" disabled={busy || !data} onClick={() => void resetDemo()} type="button">Reset Demo</button>
          </div>
          <div aria-live="polite" aria-atomic="true" className="mt-5 rounded-lg border border-white/20 p-4" role={error ? "alert" : "status"}>
            <strong>{error ?? (screenState === "loading" ? "Loading prepared report…" : screenState === "running" ? `Running stage ${currentStage + 1} of ${stages.length}.` : screenState === "resetting" ? "Resetting managed demo data…" : data?.status_message ?? "Choose a demo action. No result is claimed yet.")}</strong>
            <span className="ml-3 rounded-full border border-white/30 px-2 py-1 text-xs font-bold uppercase">{humanize(screenState)}</span>
          </div>
        </div>
      </header>

      {data && <div className="mx-auto max-w-[1440px] px-5 py-6 lg:px-10">
        {data.used_prepared_fallback && <aside className="rounded-xl border-2 border-amber-500 bg-amber-50 p-5" role="note"><h2 className="text-xl font-black">Prepared fallback report</h2><p>The live execution remains {data.live_execution_status ?? "unavailable"}. This verified prepared report is not presented as its output.</p></aside>}

        <section className="mt-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-5" aria-label="Website analysis overview">
          <article className="rounded-xl bg-slate-950 p-5 text-white"><p className="text-sm font-bold">Overall score</p><p className="mt-2 text-4xl font-black">{data.overall_score}/100</p><p>Confidence {data.score_confidence_percent}%</p></article>
          <article className="rounded-xl bg-white p-5 shadow-sm"><p className="text-sm font-bold">Page coverage</p><p className="mt-2 text-3xl font-black">{data.page_coverage.coverage_numerator}/{data.page_coverage.coverage_denominator}</p><p>{data.page_coverage.coverage_percentage}% analysed</p></article>
          <article className="rounded-xl bg-white p-5 shadow-sm"><p className="text-sm font-bold">Browser compatibility</p><p className="mt-2 text-3xl font-black">{compatibility?.summary.compatibility_percentage}%</p><p>3 Playwright engines</p></article>
          <article className="rounded-xl bg-white p-5 shadow-sm"><p className="text-sm font-bold">Website</p><p className="mt-2 font-black">{data.website_name}</p><p className="break-all text-sm">{data.website_url}</p></article>
          <article className="rounded-xl bg-emerald-100 p-5"><p className="text-sm font-bold">Report state</p><p className="mt-2 text-2xl font-black">{data.report_ready ? "Report ready" : "Not ready"}</p><p>{humanize(data.report_status ?? "unavailable")}</p></article>
        </section>

        <div className="mt-5 flex flex-wrap gap-3">
          {presentationPdf && <ExportLink artifact={presentationPdf} primary />}
          <button className="rounded-lg bg-slate-950 px-4 py-3 text-sm font-bold text-white focus-visible:outline-4 focus-visible:outline-orange-500" onClick={() => setActiveTab("Findings")} type="button">Open Full Report</button>
        </div>

        <nav className="mt-6 overflow-x-auto border-b border-slate-300" aria-label="Presentation report views">
          <div className="flex min-w-max gap-1" role="tablist">
            {TABS.map((tab) => <button aria-controls="presentation-panel" aria-selected={activeTab === tab} className={`px-4 py-3 font-bold focus-visible:outline-3 focus-visible:outline-orange-600 ${activeTab === tab ? "border-b-4 border-orange-500 bg-white" : ""}`} key={tab} onClick={() => setActiveTab(tab)} role="tab" type="button">{tab}</button>)}
          </div>
        </nav>

        <div className="mt-5 rounded-xl bg-white p-5 shadow-sm lg:p-7" id="presentation-panel" role="tabpanel">
          {activeTab === "Overview" && <>
            <section aria-labelledby="category-heading"><h2 className="text-2xl font-black" id="category-heading">Category scores</h2><div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">{data.category_scores.map((score) => <article className="rounded-lg border p-4" key={score.label}><h3 className="font-bold">{score.label}</h3><p className="mt-1 text-2xl font-black">{score.score}/100</p></article>)}</div></section>
            <section className="mt-8" aria-labelledby="top-findings-heading"><h2 className="text-2xl font-black" id="top-findings-heading">Top five findings</h2><div className="mt-4 grid gap-4 lg:grid-cols-2">{data.top_findings.slice(0, 5).map((finding) => <FindingCard finding={finding} key={finding.title} />)}</div></section>
            <section className="mt-8" aria-labelledby="top-actions-heading"><h2 className="text-2xl font-black" id="top-actions-heading">Top five actions</h2><ol className="mt-4 grid gap-3 lg:grid-cols-2">{data.top_actions.slice(0, 5).map((action) => <li className="rounded-lg border p-4" key={action.priority_rank}><strong>{action.priority_rank}. {action.title}</strong><p>Owner: {action.responsible_role} - effort {action.effort}</p><p>{action.expected_measurable_outcome}</p></li>)}</ol></section>
            <section className="mt-8" aria-labelledby="compact-agents-heading"><h2 className="text-2xl font-black" id="compact-agents-heading">Eight-agent summary</h2><div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">{data.agents.map((agent) => <article className="rounded-lg bg-slate-50 p-4" key={agent.agent_id}><h3 className="font-black">{agent.name}</h3><p>{agent.responsibility}</p><p className="mt-2 text-sm"><strong>{humanize(agent.status)}</strong> - {agent.processed_summary}</p></article>)}</div></section>
          </>}

          {activeTab === "Pages" && <PageInventory onOpen={openPage} pages={data.page_inventory} />}

          {activeTab === "Browser Compatibility" && compatibility && <section aria-labelledby="browser-heading"><h2 className="text-2xl font-black" id="browser-heading">Browser Compatibility</h2><p className="mt-2">These are Playwright browser-engine tests, not claims about every branded browser version.</p><div className="mt-4 grid gap-3 md:grid-cols-3">{compatibility.engine_coverage.map((engine) => <article className="rounded-lg border p-4" key={engine.engine}><h3 className="font-black">{engine.engine}</h3><p className="text-2xl font-black">{engine.tested_pages}/{engine.eligible_pages}</p><p>{engine.percentage}% of eligible pages</p></article>)}</div><p className="mt-4 font-bold">Viewports: {compatibility.viewports.map((item) => `${item.name} ${item.width} x ${item.height}`).join("; ")}</p><div className="mt-5 overflow-x-auto"><table className="min-w-[850px] w-full border-collapse"><caption className="sr-only">Compatibility by page and Playwright engine</caption><thead><tr>{["Page", "Chromium", "Firefox", "WebKit", "Result", "Issues"].map((item) => <th className="border p-2 text-left" key={item} scope="col">{item}</th>)}</tr></thead><tbody>{compatibility.matrix.map((row) => <tr key={row.page_url}><td className="border p-2"><strong>{row.page_title}</strong><br/><span className="break-all text-sm">{row.page_url}</span></td>{["chromium", "firefox", "webkit"].map((engine) => <td className="border p-2" key={engine}>{compatibility.status_labels[row.engines[engine]]}</td>)}<td className="border p-2 font-bold">{compatibility.status_labels[row.result]}</td><td className="border p-2">{row.issue_count}</td></tr>)}</tbody></table></div><h3 className="mt-6 text-lg font-black">Limitations and retest</h3><ul className="list-disc pl-5">{compatibility.limitations.map((item) => <li key={item}>{item}</li>)}</ul><p className="mt-2">After fixes, repeat the same pages, engines, profile, and 1440 x 900 and 390 x 844 viewports.</p></section>}

          {activeTab === "Findings" && <section aria-labelledby="findings-heading"><h2 className="text-2xl font-black" id="findings-heading">Priority findings</h2><p className="mt-2">A maximum of ten canonical findings appears here; exact occurrences remain available within each card.</p><div className="mt-4 space-y-4">{data.top_findings.slice(0, 10).map((finding) => <FindingCard finding={finding} key={finding.title} />)}</div></section>}

          {activeTab === "Action Plan" && <section aria-labelledby="actions-heading"><h2 className="text-2xl font-black" id="actions-heading">Priority Action Plan</h2><ol className="mt-4 space-y-4">{data.top_actions.slice(0, 10).map((action) => <li className="rounded-xl border p-5" key={action.priority_rank}><h3 className="text-lg font-black">{action.priority_rank}. {action.title} - {action.priority_score}/100</h3><dl className="mt-3 grid gap-3 md:grid-cols-2"><div><dt className="font-bold">Impact</dt><dd>{action.impact}</dd></div><div><dt className="font-bold">Effort and owner</dt><dd>{action.effort} - {action.responsible_role}</dd></div><div><dt className="font-bold">Expected result</dt><dd>{action.expected_measurable_outcome}</dd></div><div><dt className="font-bold">Verification</dt><dd>{action.verification_method}</dd></div></dl></li>)}</ol></section>}

          {activeTab === "Scores" && <section aria-labelledby="scores-heading"><h2 className="text-2xl font-black" id="scores-heading">Explainable scores</h2><p className="mt-2">Overall Score Formula v1.0.0 remains deterministic. Confidence and coverage are separate from score.</p><div className="mt-5 grid gap-4 md:grid-cols-2 lg:grid-cols-3">{data.category_scores.map((item) => <article className="rounded-xl border p-5" key={item.label}><h3 className="font-black">{item.label}</h3><p className="text-4xl font-black">{item.score}/100</p></article>)}</div></section>}

          {activeTab === "Agents" && <section aria-labelledby="agents-heading"><h2 className="text-2xl font-black" id="agents-heading">Eight agents, one evidence chain</h2><div className="mt-4 grid gap-4 md:grid-cols-2">{data.agents.map((agent) => <article className="rounded-xl border p-5" key={agent.agent_id}><h3 className="text-lg font-black">{agent.name}</h3><p>{agent.responsibility}</p><p className="mt-3"><strong>Status:</strong> {humanize(agent.status)}</p><p><strong>Processed:</strong> {agent.processed_summary}</p></article>)}</div></section>}

          {activeTab === "Technical Details" && <section aria-labelledby="technical-heading"><h2 className="text-2xl font-black" id="technical-heading">Technical Details</h2><p className="mt-2">Optional evidence details are separated from the default presentation view.</p>{selectedPage && (() => { const page = data.page_inventory.find((item) => item.url === selectedPage); return page ? <article className="mt-4 rounded-lg border p-4"><h3 className="font-black">{page.title}</h3><p className="break-all">{page.url}</p><p>Status: {humanize(page.analysis_status)} - HTTP {page.http_status ?? "unavailable"}</p><p>Browser engines: {page.browsers_tested.join(", ") || "Not tested"}</p><p>Evidence coverage: {page.evidence_coverage_percentage ?? "Unavailable"}%</p></article> : null; })()}<h3 className="mt-6 text-lg font-black">Coverage definitions</h3><dl className="mt-2 grid gap-3 md:grid-cols-2">{Object.entries(data.page_coverage.definitions).map(([term, definition]) => <div className="rounded-lg bg-slate-50 p-3" key={term}><dt className="font-black">{humanize(term)}</dt><dd>{definition}</dd></div>)}</dl><h3 className="mt-6 text-lg font-black">Workflow stages</h3><div className="mt-3"><StageFlow currentIndex={currentStage} running={screenState === "running"} stages={stages} /></div><h3 className="mt-6 text-lg font-black">Optional exports</h3><div className="mt-3 flex flex-wrap gap-3">{data.artifacts.map((artifact) => <ExportLink artifact={artifact} key={artifact.kind} />)}</div><p className="mt-4 text-sm">Analysis started {data.page_coverage.started_at}; completed {data.page_coverage.completed_at}; duration {data.page_coverage.duration_seconds} seconds.</p></section>}
        </div>
      </div>}
    </main>
  );
}
