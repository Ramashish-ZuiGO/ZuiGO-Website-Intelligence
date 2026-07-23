"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";

import { apiRequest } from "@/lib/api";
import type { ProjectDetail, Website } from "@/lib/types";
import { ActionPlanPanel } from "./ActionPlanPanel";
import { PageAnalysisPanel } from "./PageAnalysisPanel";
import { WebsiteAnalysisPanel } from "./WebsiteAnalysisPanel";
import { WebsiteCoveragePanel } from "./WebsiteCoveragePanel";

export default function ProjectDetailsPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const router = useRouter();
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void apiRequest<ProjectDetail>(`/api/v1/projects/${projectId}`)
      .then((loadedProject) => {
        if (!cancelled) setProject(loadedProject);
      })
      .catch((requestError: unknown) => {
        if (!cancelled) {
          setError(
            requestError instanceof Error ? requestError.message : "Unable to load project.",
          );
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  async function addWebsite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const formData = new FormData(form);
    setSubmitting(true);
    setError(null);
    setSuccess(null);
    let website: Website;
    try {
      website = await apiRequest<Website>(`/api/v1/projects/${projectId}/websites`, {
        method: "POST",
        body: JSON.stringify({
          url: formData.get("url"),
          name: formData.get("name") || null,
        }),
      });
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to add website.");
      setSubmitting(false);
      return;
    }

    form.reset();
    setProject((current) =>
      current ? { ...current, websites: [...current.websites, website] } : current,
    );
    setSuccess("Website added successfully.");
    setSubmitting(false);
  }

  async function deleteProject() {
    if (!window.confirm("Delete this project and all its websites?")) return;
    setError(null);
    setSuccess(null);
    try {
      await apiRequest<void>(`/api/v1/projects/${projectId}`, { method: "DELETE" });
      router.push("/projects");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to delete project.");
    }
  }

  if (loading) return <main className="mx-auto max-w-5xl px-6 py-12"><p role="status">Loading project…</p></main>;

  return (
    <main className="mx-auto min-h-screen max-w-5xl px-6 py-12">
      <Link className="text-sm font-semibold text-slate-600 hover:text-slate-950" href="/projects">← All projects</Link>
      {error && !project && <p className="mt-8 text-red-700" role="alert">{error}</p>}
      {project && (
        <>
          <header className="mt-6 flex items-start justify-between gap-6">
            <div><h1 className="text-4xl font-bold text-slate-950">{project.name}</h1>{project.description && <p className="mt-3 text-slate-600">{project.description}</p>}</div>
            <button className="rounded-lg border border-red-300 px-4 py-2 font-semibold text-red-700" onClick={() => void deleteProject()}>Delete project</button>
          </header>

          <section className="mt-10 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <h2 className="text-xl font-semibold">Add website</h2>
            <form className="mt-5 grid gap-4" onSubmit={addWebsite}>
              <label className="grid gap-2 font-medium">Website URL<input className="rounded-lg border border-slate-300 px-3 py-2" name="url" type="url" placeholder="https://example.com" required /></label>
              <label className="grid gap-2 font-medium">Name <span className="font-normal text-slate-500">(optional)</span><input className="rounded-lg border border-slate-300 px-3 py-2" name="name" maxLength={200} /></label>
              <button className="w-fit rounded-lg bg-slate-950 px-5 py-2.5 font-semibold text-white disabled:opacity-60" disabled={submitting}>{submitting ? "Adding…" : "Add website"}</button>
            </form>
            {success && <p className="mt-4 text-emerald-700" role="status">{success}</p>}
            {error && <p className="mt-4 text-red-700" role="alert">{error}</p>}
          </section>

          <section className="mt-10"><h2 className="text-2xl font-semibold">Websites</h2>
            {project.websites.length === 0 ? <div className="mt-5 rounded-xl border border-dashed border-slate-300 p-8 text-center text-slate-600">No websites yet. Add the first URL above.</div> : (
              <ul className="mt-5 grid gap-4">{project.websites.map((website) => <li className="rounded-xl border border-slate-200 bg-white p-5" key={website.id}><p className="font-semibold">{website.name || "Unnamed website"}</p><a className="mt-1 block break-all text-slate-600 underline" href={website.url} target="_blank" rel="noreferrer">{website.url}</a><WebsiteAnalysisPanel websiteId={website.id} /><WebsiteCoveragePanel websiteId={website.id} /><PageAnalysisPanel websiteId={website.id} /><ActionPlanPanel websiteId={website.id} /></li>)}</ul>
            )}
          </section>
        </>
      )}
    </main>
  );
}
