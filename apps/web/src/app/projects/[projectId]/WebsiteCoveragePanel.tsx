"use client";

import { useCallback, useEffect, useState } from "react";

import { apiRequest } from "@/lib/api";
import type {
  CoverageSummary,
  DiscoveryRun,
  WebsitePageList,
} from "@/lib/types";

const explanations: Record<string, string> = {
  discovered: "Every URL observation before normalization. Repeated links can appear more than once.",
  eligible: "Unique in-scope HTTP pages not blocked by robots or safety exclusions. External, destructive, and disallowed pages are excluded.",
  coverage: "Eligible pages with a completed, partial, or failed analysis attempt divided by all eligible pages. This is coverage, not a quality score.",
  excluded: "Pages outside scope, blocked by robots, or matching state-changing safety patterns.",
  skipped: "In-scope candidates not fetched as HTML because of an optional fetch failure, response type, or HTTP response.",
  robots: "Whether the applicable ZuiGO-Discovery robots policy allowed the URL. Unknown means permissions could not be established.",
  depth: "Number of internal-link steps from the submitted homepage. Sitemap URLs begin at depth zero.",
  limit: "Whether any configured URL, sitemap, HTML-page, link, depth, response-size, redirect, or deadline boundary stopped further discovery.",
};

function Info({ kind }: { kind: keyof typeof explanations }) {
  return (
    <span
      aria-label={explanations[kind]}
      className="ml-1 inline-flex size-5 cursor-help items-center justify-center rounded-full border text-xs"
      role="img"
      title={explanations[kind]}
    >
      i
    </span>
  );
}

export function WebsiteCoveragePanel({ websiteId }: { websiteId: string }) {
  const [coverage, setCoverage] = useState<CoverageSummary | null>(null);
  const [pages, setPages] = useState<WebsitePageList | null>(null);
  const [run, setRun] = useState<DiscoveryRun | null>(null);
  const [page, setPage] = useState(1);
  const [eligibility, setEligibility] = useState("");
  const [search, setSearch] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const parameters = new URLSearchParams({ page: String(page), page_size: "10" });
    if (eligibility) parameters.set("eligibility", eligibility);
    if (search) parameters.set("search", search);
    const [nextCoverage, nextPages] = await Promise.all([
      apiRequest<CoverageSummary>(`/api/v1/websites/${websiteId}/coverage`),
      apiRequest<WebsitePageList>(`/api/v1/websites/${websiteId}/pages?${parameters}`),
    ]);
    setCoverage(nextCoverage);
    setPages(nextPages);
  }, [eligibility, page, search, websiteId]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load().catch((requestError: unknown) => {
        setError(requestError instanceof Error ? requestError.message : "Coverage could not be loaded.");
      });
    }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  useEffect(() => {
    if (!run || !["queued", "running"].includes(run.status)) return;
    const timer = window.setInterval(() => {
      void apiRequest<DiscoveryRun>(`/api/v1/discovery-runs/${run.id}`).then((nextRun) => {
        setRun(nextRun);
        if (!["queued", "running"].includes(nextRun.status)) void load();
      });
    }, 2000);
    return () => window.clearInterval(timer);
  }, [load, run]);

  async function start() {
    setError(null);
    try {
      setRun(await apiRequest<DiscoveryRun>(`/api/v1/websites/${websiteId}/discovery-runs`, { method: "POST" }));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Discovery could not start.");
    }
  }

  const analyzedLabel = coverage
    ? `${coverage.analyzed_coverage_numerator}/${coverage.analyzed_coverage_denominator} pages — ${coverage.analyzed_coverage_percent === null ? "Unavailable" : `${coverage.analyzed_coverage_percent}%`}`
    : "Not available";

  return (
    <section className="mt-5 border-t pt-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="font-semibold">Website Coverage</h3>
        <button className="rounded-lg border px-3 py-1.5 text-sm font-semibold disabled:opacity-50" disabled={run?.status === "queued" || run?.status === "running"} onClick={() => void start()} type="button">
          {run?.status === "running" || run?.status === "queued" ? `Discovering ${run.progress_percent}%` : "Discover pages"}
        </button>
      </div>
      {error && <p className="mt-2 text-sm text-red-700" role="alert">{error}</p>}
      {!coverage?.discovery_run_id ? (
        <p className="mt-3 text-sm text-slate-600">No discovery run yet. Start bounded discovery to build coverage.</p>
      ) : (
        <>
          <dl className="mt-4 grid gap-2 text-sm sm:grid-cols-3">
            <div><dt className="text-slate-500">Pages Discovered <Info kind="discovered" /></dt><dd className="font-semibold">{coverage.discovered_urls}</dd></div>
            <div><dt className="text-slate-500">Unique</dt><dd className="font-semibold">{coverage.unique_pages}</dd></div>
            <div><dt className="text-slate-500">Eligible Pages <Info kind="eligible" /></dt><dd className="font-semibold">{coverage.eligible_pages}</dd></div>
            <div className="sm:col-span-2"><dt className="text-slate-500">Analyzed Coverage <Info kind="coverage" /></dt><dd className="font-semibold">{analyzedLabel}</dd></div>
            <div><dt className="text-slate-500">Pending</dt><dd>{coverage.pending_analyses}</dd></div>
            <div><dt className="text-slate-500">Completed</dt><dd>{coverage.completed_analyses}</dd></div>
            <div><dt className="text-slate-500">Partial</dt><dd>{coverage.partial_analyses}</dd></div>
            <div><dt className="text-slate-500">Failed</dt><dd>{coverage.failed_analyses}</dd></div>
            <div><dt className="text-slate-500">Excluded Pages <Info kind="excluded" /></dt><dd>{coverage.excluded_pages}</dd></div>
            <div><dt className="text-slate-500">Skipped Pages <Info kind="skipped" /></dt><dd>{coverage.skipped_pages}</dd></div>
            <div><dt className="text-slate-500">Robots-disallowed <Info kind="robots" /></dt><dd>{coverage.robots_disallowed_pages}</dd></div>
            <div><dt className="text-slate-500">Crawl limit <Info kind="limit" /></dt><dd>{coverage.crawl_limit_reached ? "Yes" : "No"}</dd></div>
          </dl>
          <div className="mt-5 flex flex-wrap gap-2">
            <input aria-label="Search page URLs" className="rounded border px-3 py-1.5 text-sm" onChange={(event) => { setPage(1); setSearch(event.target.value); }} placeholder="Search URL or title" value={search} />
            <select aria-label="Filter by eligibility" className="rounded border px-3 py-1.5 text-sm" onChange={(event) => { setPage(1); setEligibility(event.target.value); }} value={eligibility}>
              <option value="">All eligibility</option><option value="eligible">Eligible</option><option value="excluded">Excluded</option><option value="skipped">Skipped</option>
            </select>
          </div>
          {pages?.items.length ? (
            <div className="mt-3 overflow-x-auto">
              <table className="w-full min-w-[900px] text-left text-xs">
                <thead><tr className="border-b"><th className="p-2">Page URL</th><th>Title</th><th>Type</th><th>Source</th><th>Depth <Info kind="depth" /></th><th>Eligibility</th><th>Robots <Info kind="robots" /></th><th>Analysis</th><th>Reason</th><th>Action</th></tr></thead>
                <tbody>{pages.items.map((item) => <tr className="border-b align-top" key={item.id}><td className="max-w-64 break-all p-2">{item.normalized_url}</td><td>{item.page_title || "—"}</td><td>{item.page_type.replaceAll("_", " ")}</td><td>{item.discovery_source.replaceAll("_", " ")}</td><td>{item.crawl_depth}</td><td>{item.eligibility_status}</td><td>{item.robots_status}</td><td>{item.latest_analysis_status}</td><td>{item.exclusion_reason || item.skip_reason || "—"}</td><td><a className="underline" href={item.normalized_url} rel="noreferrer" target="_blank">View page</a></td></tr>)}</tbody>
              </table>
            </div>
          ) : <p className="mt-4 text-sm text-slate-600">No discovered pages match these filters.</p>}
          {pages && pages.total_pages > 1 && <div className="mt-3 flex items-center gap-3 text-sm"><button disabled={page <= 1} onClick={() => setPage((value) => value - 1)}>Previous</button><span>Page {page} of {pages.total_pages}</span><button disabled={page >= pages.total_pages} onClick={() => setPage((value) => value + 1)}>Next</button></div>}
        </>
      )}
    </section>
  );
}
