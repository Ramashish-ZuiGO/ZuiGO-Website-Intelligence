"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";

import { apiRequest } from "@/lib/api";
import type { Project } from "@/lib/types";

export default function ProjectsPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const loadProjects = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setProjects(await apiRequest<Project[]>("/api/v1/projects"));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to load projects.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    void apiRequest<Project[]>("/api/v1/projects")
      .then((loadedProjects) => {
        if (!cancelled) setProjects(loadedProjects);
      })
      .catch((requestError: unknown) => {
        if (!cancelled) {
          setError(
            requestError instanceof Error ? requestError.message : "Unable to load projects.",
          );
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function createProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const formData = new FormData(form);
    setSubmitting(true);
    setError(null);
    setSuccess(null);
    let project: Project;
    try {
      project = await apiRequest<Project>("/api/v1/projects", {
        method: "POST",
        body: JSON.stringify({
          name: formData.get("name"),
          description: formData.get("description") || null,
        }),
      });
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to create project.");
      setSubmitting(false);
      return;
    }

    form.reset();
    setProjects((current) => [project, ...current]);
    setSuccess(`Project “${project.name}” created.`);
    setSubmitting(false);
  }

  return (
    <main className="mx-auto min-h-screen max-w-5xl px-6 py-12">
      <header className="mb-10">
        <p className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-500">MVP</p>
        <h1 className="mt-2 text-4xl font-bold text-slate-950">Projects</h1>
        <p className="mt-3 text-slate-600">Create a project, then add websites to it.</p>
      </header>

      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-xl font-semibold">Create project</h2>
        <form className="mt-5 grid gap-4" onSubmit={createProject}>
          <label className="grid gap-2 font-medium">
            Name
            <input className="rounded-lg border border-slate-300 px-3 py-2" name="name" required maxLength={200} />
          </label>
          <label className="grid gap-2 font-medium">
            Description <span className="font-normal text-slate-500">(optional)</span>
            <textarea className="rounded-lg border border-slate-300 px-3 py-2" name="description" rows={3} />
          </label>
          <button className="w-fit rounded-lg bg-slate-950 px-5 py-2.5 font-semibold text-white disabled:opacity-60" disabled={submitting}>
            {submitting ? "Creating…" : "Create project"}
          </button>
        </form>
        {success && <p className="mt-4 text-emerald-700" role="status">{success}</p>}
        {error && <p className="mt-4 text-red-700" role="alert">{error}</p>}
      </section>

      <section className="mt-10">
        <div className="flex items-center justify-between">
          <h2 className="text-2xl font-semibold">Your projects</h2>
          <button className="text-sm font-semibold text-slate-700" onClick={() => void loadProjects()}>Refresh</button>
        </div>
        {loading && <p className="mt-5 text-slate-600" role="status">Loading projects…</p>}
        {!loading && projects.length === 0 && !error && (
          <div className="mt-5 rounded-xl border border-dashed border-slate-300 p-8 text-center text-slate-600">No projects yet. Create your first project above.</div>
        )}
        {!loading && projects.length > 0 && (
          <ul className="mt-5 grid gap-4">
            {projects.map((project) => (
              <li key={project.id} className="rounded-xl border border-slate-200 bg-white p-5">
                <Link className="text-lg font-semibold text-slate-950 underline-offset-4 hover:underline" href={`/projects/${project.id}`}>{project.name}</Link>
                {project.description && <p className="mt-2 text-slate-600">{project.description}</p>}
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
