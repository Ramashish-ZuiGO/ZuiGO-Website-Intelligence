"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { apiRequest } from "@/lib/api";
import type {
  ActionRepositoryMatch,
  DetectedTechnology,
  RepositoryConnection,
  RepositoryScanExecution,
} from "@/lib/types";

interface RepositoryPanelProps {
  projectId: string;
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    active: "bg-emerald-100 text-emerald-800",
    inactive: "bg-slate-100 text-slate-500",
    pending: "bg-amber-100 text-amber-800",
    unlinked: "bg-red-100 text-red-800",
    queued: "bg-blue-100 text-blue-800",
    running: "bg-amber-100 text-amber-800",
    completed: "bg-emerald-100 text-emerald-800",
    partial: "bg-orange-100 text-orange-800",
    failed: "bg-red-100 text-red-800",
  };
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-bold ${colors[status] ?? "bg-slate-100 text-slate-600"}`}>
      {status.replace("_", " ")}
    </span>
  );
}

function ConfidenceBadge({ confidence }: { confidence: string }) {
  const colors: Record<string, string> = {
    high: "bg-emerald-100 text-emerald-800",
    medium: "bg-amber-100 text-amber-800",
    low: "bg-red-100 text-red-800",
  };
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-bold ${colors[confidence] ?? "bg-slate-100 text-slate-600"}`}>
      {confidence}
    </span>
  );
}

const PROVIDER_OPTIONS = [
  { value: "local", label: "Local" },
  { value: "github", label: "GitHub" },
  { value: "gitlab", label: "GitLab" },
  { value: "bitbucket", label: "Bitbucket" },
  { value: "azure_devops", label: "Azure DevOps" },
];

export function RepositoryPanel({ projectId }: RepositoryPanelProps) {
  const [connection, setConnection] = useState<RepositoryConnection | null>(null);
  const [connectionLoading, setConnectionLoading] = useState(false);
  const [latestScan, setLatestScan] = useState<RepositoryScanExecution | null>(null);
  const [technologies, setTechnologies] = useState<DetectedTechnology[]>([]);
  const [matchResults, setMatchResults] = useState<ActionRepositoryMatch[]>([]);
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [showMatchResults, setShowMatchResults] = useState(false);
  const [matchResultsLoading, setMatchResultsLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [validating, setValidating] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [technologiesLoading, setTechnologiesLoading] = useState(false);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadConnection = useCallback(async () => {
    setConnectionLoading(true);
    try {
      const result = await apiRequest<RepositoryConnection[]>(
        `/api/v1/projects/${projectId}/repository/connections`
      );
      if (result.length > 0) {
        setConnection(result[0]);
      }
    } catch {
      // No connection exists
    } finally {
      setConnectionLoading(false);
    }
  }, [projectId]);

  const loadTechnologies = useCallback(async (scanId: string) => {
    setTechnologiesLoading(true);
    try {
      const result = await apiRequest<DetectedTechnology[]>(
        `/api/v1/projects/${projectId}/repository/scans/${scanId}/technologies`
      );
      setTechnologies(result);
    } catch {
      setTechnologies([]);
    } finally {
      setTechnologiesLoading(false);
    }
  }, [projectId]);

  const startPolling = useCallback((connId: string) => {
    if (pollingRef.current) clearInterval(pollingRef.current);
    pollingRef.current = setInterval(async () => {
      try {
        const result = await apiRequest<{ items: RepositoryScanExecution[] }>(
          `/api/v1/projects/${projectId}/repository/connections/${connId}/scans?page_size=1`
        );
        if (result.items.length > 0) {
          const scan = result.items[0];
          setLatestScan(scan);
          if (["completed", "failed", "partial"].includes(scan.status)) {
            if (pollingRef.current) {
              clearInterval(pollingRef.current);
              pollingRef.current = null;
            }
            setScanning(false);
            if (scan.status === "completed") {
              void loadTechnologies(scan.id).catch(() => {});
            }
          }
        }
      } catch {
        if (pollingRef.current) {
          clearInterval(pollingRef.current);
          pollingRef.current = null;
        }
        setScanning(false);
      }
    }, 3000);
  }, [projectId, loadTechnologies]);

  const loadLatestScan = useCallback(async (connId: string) => {
    try {
      const result = await apiRequest<{ items: RepositoryScanExecution[] }>(
        `/api/v1/projects/${projectId}/repository/connections/${connId}/scans?page_size=1`
      );
      if (result.items.length > 0) {
        setLatestScan(result.items[0]);
        if (result.items[0].status === "completed") {
          void loadTechnologies(result.items[0].id).catch(() => {});
        }
        if (["queued", "running"].includes(result.items[0].status)) {
          startPolling(connId);
        }
      }
    } catch {
      // No scans yet
    }
  }, [projectId, loadTechnologies, startPolling]);

  useEffect(() => {
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadConnection().catch(() => {});
    }, 0);
    return () => window.clearTimeout(timer);
  }, [loadConnection]);

  useEffect(() => {
    if (connection) {
      const id = connection.id;
      // eslint-disable-next-line react-hooks/set-state-in-effect
      void loadLatestScan(id).catch(() => {});
    }
  }, [connection, loadLatestScan]);

  async function createConnection(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setSuccess(null);
    setCreating(true);
    const form = e.currentTarget;
    const formData = new FormData(form);
    try {
      const result = await apiRequest<RepositoryConnection>(
        `/api/v1/projects/${projectId}/repository/connections`,
        {
          method: "POST",
          body: JSON.stringify({
            project_id: projectId,
            provider: formData.get("provider"),
            display_name: formData.get("display_name"),
            local_root: formData.get("local_root"),
            remote_url: formData.get("remote_url") || null,
          }),
        }
      );
      setConnection(result);
      setSuccess("Repository connection created successfully.");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to create connection.");
    } finally {
      setCreating(false);
    }
  }

  async function updateConnection(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!connection) return;
    setError(null);
    setSuccess(null);
    const form = e.currentTarget;
    const formData = new FormData(form);
    try {
      const result = await apiRequest<RepositoryConnection>(
        `/api/v1/projects/${projectId}/repository/connections/${connection.id}`,
        {
          method: "PATCH",
          body: JSON.stringify({
            display_name: formData.get("display_name") || null,
            local_root: formData.get("local_root") || null,
            remote_url: formData.get("remote_url") || null,
          }),
        }
      );
      setConnection(result);
      setEditing(false);
      setSuccess("Repository connection updated successfully.");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to update connection.");
    }
  }

  async function deleteConnection() {
    if (!connection) return;
    if (!window.confirm("Delete this repository connection? This cannot be undone.")) return;
    setError(null);
    setSuccess(null);
    setDeleting(true);
    try {
      await apiRequest<void>(
        `/api/v1/projects/${projectId}/repository/connections/${connection.id}`,
        { method: "DELETE" }
      );
      setConnection(null);
      setLatestScan(null);
      setTechnologies([]);
      setMatchResults([]);
      setSuccess("Repository connection deleted.");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to delete connection.");
    } finally {
      setDeleting(false);
    }
  }

  async function validateConnection() {
    if (!connection) return;
    setError(null);
    setSuccess(null);
    setValidating(true);
    try {
      const result = await apiRequest<RepositoryConnection>(
        `/api/v1/projects/${projectId}/repository/connections/${connection.id}/validate`,
        { method: "POST" }
      );
      setConnection(result);
      setSuccess("Connection validated successfully.");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Validation failed.");
    } finally {
      setValidating(false);
    }
  }

  async function startScan() {
    if (!connection) return;
    setError(null);
    setSuccess(null);
    setScanning(true);
    try {
      const result = await apiRequest<RepositoryScanExecution>(
        `/api/v1/projects/${projectId}/repository/connections/${connection.id}/scans`,
        { method: "POST" }
      );
      setLatestScan(result);
      startPolling(connection.id);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to start scan.");
      setScanning(false);
    }
  }

  async function loadMatchResults() {
    if (!connection) return;
    setMatchResultsLoading(true);
    setShowMatchResults(true);
    try {
      const result = await apiRequest<ActionRepositoryMatch[]>(
        `/api/v1/projects/${projectId}/repository/connections/${connection.id}/match-results`
      );
      setMatchResults(result);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to load match results.");
    } finally {
      setMatchResultsLoading(false);
    }
  }

  async function copyToClipboard(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setSuccess("Copied to clipboard.");
    } catch {
      setError("Unable to copy.");
    }
  }

  const isScanRunning = latestScan && ["queued", "running"].includes(latestScan.status);

  if (connectionLoading) {
    return <p className="mt-4 text-sm text-slate-500" role="status">Loading repository connection…</p>;
  }

  return (
    <section className="mt-5 border-t pt-5">
      {error && <p className="mt-2 text-sm text-red-700" role="alert">{error}</p>}
      {success && <p className="mt-2 text-sm text-emerald-700" role="status">{success}</p>}

      {!connection && (
        <div className="mt-4 rounded-xl border bg-white p-4">
          <h4 className="font-semibold">Connect Repository</h4>
          <form className="mt-4 grid gap-4 sm:grid-cols-2" onSubmit={(e) => void createConnection(e)}>
            <label className="grid gap-1.5 text-sm font-medium">
              Provider
              <select
                aria-label="Repository provider"
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
                defaultValue="local"
                name="provider"
              >
                {PROVIDER_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </label>
            <label className="grid gap-1.5 text-sm font-medium">
              Display name
              <input
                aria-label="Display name"
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
                name="display_name"
                placeholder="My project repo"
                required
                type="text"
              />
            </label>
            <label className="grid gap-1.5 text-sm font-medium">
              Local root path
              <input
                aria-label="Local root path"
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
                name="local_root"
                placeholder="C:\projects\my-app"
                required
                type="text"
              />
            </label>
            <label className="grid gap-1.5 text-sm font-medium">
              Remote URL
              <input
                aria-label="Remote URL"
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
                name="remote_url"
                placeholder="https://github.com/user/repo.git"
                type="url"
              />
            </label>
            <div className="sm:col-span-2">
              <button
                aria-label="Create repository connection"
                className="rounded-lg border bg-slate-950 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
                disabled={creating}
                type="submit"
              >
                {creating ? "Connecting…" : "Connect"}
              </button>
            </div>
          </form>
        </div>
      )}

      {connection && !editing && (
        <div className="mt-4 rounded-xl border bg-white p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h4 className="font-semibold">{connection.display_name}</h4>
              <p className="mt-0.5 text-xs text-slate-500 capitalize">{connection.provider}</p>
            </div>
            <StatusBadge status={connection.status} />
          </div>

          <div className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
            <div>
              <span className="text-xs text-slate-500">Local root</span>
              <div className="flex items-center gap-1">
                <code className="truncate text-xs text-slate-700">{connection.local_root}</code>
                <button
                  aria-label="Copy local root path"
                  className="shrink-0 text-xs text-blue-600 underline"
                  onClick={() => void copyToClipboard(connection.local_root)}
                  type="button"
                >
                  Copy
                </button>
              </div>
            </div>
            {connection.current_branch && (
              <div>
                <span className="text-xs text-slate-500">Branch</span>
                <p className="font-mono text-xs">{connection.current_branch}</p>
              </div>
            )}
            {connection.current_commit_sha && (
              <div>
                <span className="text-xs text-slate-500">Commit</span>
                <div className="flex items-center gap-1">
                  <code className="truncate text-xs">{connection.current_commit_sha.slice(0, 12)}</code>
                  <button
                    aria-label="Copy commit SHA"
                    className="shrink-0 text-xs text-blue-600 underline"
                    onClick={() => void copyToClipboard(connection.current_commit_sha!)}
                    type="button"
                  >
                    Copy
                  </button>
                </div>
              </div>
            )}
            {connection.default_branch && (
              <div>
                <span className="text-xs text-slate-500">Default branch</span>
                <p className="font-mono text-xs">{connection.default_branch}</p>
              </div>
            )}
            {connection.remote_url && (
              <div className="sm:col-span-2">
                <span className="text-xs text-slate-500">Remote URL</span>
                <p className="truncate text-xs text-slate-700">{connection.remote_url}</p>
              </div>
            )}
          </div>

          <div className="mt-3 flex flex-wrap gap-2">
            <button
              aria-label="Validate connection"
              className="rounded-lg border px-3 py-1.5 text-sm font-semibold disabled:opacity-50"
              disabled={validating}
              onClick={() => void validateConnection()}
              type="button"
            >
              {validating ? "Validating…" : "Validate"}
            </button>
            <button
              aria-label="Edit connection"
              className="rounded-lg border px-3 py-1.5 text-sm font-semibold"
              onClick={() => setEditing(true)}
              type="button"
            >
              Edit
            </button>
            <button
              aria-label="Delete connection"
              className="rounded-lg border border-red-300 px-3 py-1.5 text-sm font-semibold text-red-700 disabled:opacity-50"
              disabled={deleting}
              onClick={() => void deleteConnection()}
              type="button"
            >
              {deleting ? "Deleting…" : "Delete"}
            </button>
          </div>
        </div>
      )}

      {connection && editing && (
        <div className="mt-4 rounded-xl border bg-white p-4">
          <h4 className="font-semibold">Edit Connection</h4>
          <form className="mt-4 grid gap-4 sm:grid-cols-2" onSubmit={(e) => void updateConnection(e)}>
            <label className="grid gap-1.5 text-sm font-medium">
              Display name
              <input
                aria-label="Display name"
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
                defaultValue={connection.display_name}
                name="display_name"
                required
                type="text"
              />
            </label>
            <label className="grid gap-1.5 text-sm font-medium">
              Local root path
              <input
                aria-label="Local root path"
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
                defaultValue={connection.local_root}
                name="local_root"
                required
                type="text"
              />
            </label>
            <label className="grid gap-1.5 text-sm font-medium">
              Remote URL
              <input
                aria-label="Remote URL"
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
                defaultValue={connection.remote_url ?? ""}
                name="remote_url"
                type="url"
              />
            </label>
            <div className="flex gap-2 sm:col-span-2">
              <button
                aria-label="Save connection changes"
                className="rounded-lg border bg-slate-950 px-4 py-2 text-sm font-semibold text-white"
                type="submit"
              >
                Save
              </button>
              <button
                aria-label="Cancel editing"
                className="rounded-lg border px-4 py-2 text-sm font-semibold"
                onClick={() => setEditing(false)}
                type="button"
              >
                Cancel
              </button>
            </div>
          </form>
        </div>
      )}

      {connection && (
        <div className="mt-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h4 className="font-semibold">Repository Scan</h4>
            <button
              aria-label={isScanRunning ? "Scan in progress" : "Start repository scan"}
              className="rounded-lg border bg-slate-950 px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50"
              disabled={scanning || !!isScanRunning}
              onClick={() => void startScan()}
              type="button"
            >
              {isScanRunning ? "Scanning…" : scanning ? "Starting…" : "Start scan"}
            </button>
          </div>

          {isScanRunning && (
            <p className="mt-3 text-sm text-amber-700" role="status">
              Scanning repository…
            </p>
          )}

          {latestScan && !isScanRunning && (
            <div className="mt-3 rounded-xl border bg-white p-4">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium">Scan status:</span>
                <StatusBadge status={latestScan.status} />
              </div>

              <div className="mt-3 grid grid-cols-2 gap-3 text-sm sm:grid-cols-5">
                <div className="rounded-lg bg-slate-50 p-2">
                  <p className="text-xs text-slate-500">Discovered</p>
                  <p className="text-lg font-bold">{latestScan.total_files_discovered}</p>
                </div>
                <div className="rounded-lg bg-slate-50 p-2">
                  <p className="text-xs text-slate-500">Eligible</p>
                  <p className="text-lg font-bold">{latestScan.eligible_files}</p>
                </div>
                <div className="rounded-lg bg-slate-50 p-2">
                  <p className="text-xs text-slate-500">Scanned</p>
                  <p className="text-lg font-bold">{latestScan.scanned_files}</p>
                </div>
                <div className="rounded-lg bg-slate-50 p-2">
                  <p className="text-xs text-slate-500">Skipped</p>
                  <p className="text-lg font-bold">{latestScan.skipped_files}</p>
                </div>
                <div className="rounded-lg bg-slate-50 p-2">
                  <p className="text-xs text-slate-500">Failed</p>
                  <p className="text-lg font-bold text-red-700">{latestScan.failed_files}</p>
                </div>
              </div>

              {latestScan.status === "failed" && (
                <div className="mt-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm">
                  <p className="font-semibold text-red-800">Scan failed</p>
                  {latestScan.failure_reason_code && (
                    <p className="mt-1 text-xs text-red-700">Code: {latestScan.failure_reason_code}</p>
                  )}
                  {latestScan.failure_explanation && (
                    <p className="mt-1 text-xs text-red-700">{latestScan.failure_explanation}</p>
                  )}
                </div>
              )}

              {latestScan.limitations && latestScan.limitations.length > 0 && (
                <div className="mt-3">
                  <p className="text-xs font-semibold text-slate-500">Limitations</p>
                  <ul className="mt-1 list-inside list-disc text-xs text-slate-500">
                    {latestScan.limitations.map((lim, i) => <li key={i}>{lim}</li>)}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {connection && latestScan && latestScan.status === "completed" && (
        <div className="mt-6">
          <h4 className="font-semibold">Detected Technologies</h4>
          {technologiesLoading ? (
            <p className="mt-2 text-sm text-slate-500" role="status">Loading technologies…</p>
          ) : technologies.length === 0 ? (
            <p className="mt-2 text-sm text-slate-500">No technologies detected.</p>
          ) : (
            <div className="mt-2 flex flex-wrap gap-2">
              {technologies.map((tech) => (
                <div className="rounded-lg border bg-white px-3 py-2 text-sm" key={tech.id}>
                  <span className="font-semibold">{tech.technology}</span>
                  <span className="ml-2"><ConfidenceBadge confidence={tech.confidence} /></span>
                  {tech.supporting_files && tech.supporting_files.length > 0 && (
                    <p className="mt-1 text-xs text-slate-500">{tech.supporting_files.length} file{tech.supporting_files.length !== 1 ? "s" : ""}</p>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {connection && (
        <div className="mt-6">
          <h4 className="font-semibold">Repository-Aware Remediation</h4>
          <p className="mt-1 text-xs text-slate-500">
            View match results between action items and repository source files.
          </p>
          <button
            aria-label="View repository match results"
            className="mt-2 rounded-lg border px-3 py-1.5 text-sm font-semibold disabled:opacity-50"
            disabled={matchResultsLoading}
            onClick={() => void loadMatchResults()}
            type="button"
          >
            {matchResultsLoading ? "Loading…" : showMatchResults ? "Refresh matches" : "View matches"}
          </button>

          {showMatchResults && !matchResultsLoading && (
            <div className="mt-3">
              {matchResults.length === 0 ? (
                <p className="text-sm text-slate-500">No match results found.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[600px] text-left text-xs">
                    <thead>
                      <tr className="border-b">
                        <th className="p-2">Action item</th>
                        <th>File path</th>
                        <th>Symbol</th>
                        <th>Confidence</th>
                        <th>Match reason</th>
                      </tr>
                    </thead>
                    <tbody>
                      {matchResults.map((match) => (
                        <tr className="border-b align-top" key={match.id}>
                          <td className="max-w-40 break-all p-2 font-semibold">{match.action_item_id}</td>
                          <td className="max-w-48 break-all p-2 font-mono">
                            {match.relative_path}
                            {match.start_line != null && `:${match.start_line}`}
                            {match.end_line != null && `-${match.end_line}`}
                          </td>
                          <td className="p-2 font-mono">{match.symbol_name || "—"}</td>
                          <td className="p-2"><ConfidenceBadge confidence={match.match_confidence} /></td>
                          <td className="max-w-48 p-2 text-slate-600">{match.match_reason || "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
