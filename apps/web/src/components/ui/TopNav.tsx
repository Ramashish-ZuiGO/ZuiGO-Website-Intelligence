"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, Folder, LayoutDashboard } from "lucide-react";

export function TopNav() {
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-50 w-full border-b border-z-border bg-z-dark text-z-ink-inverse">
      <div className="z-container flex h-14 items-center justify-between">
        <div className="flex items-center gap-8">
          <Link
            href="/"
            className="flex items-center gap-2 font-display text-lg font-bold tracking-tight text-white focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-z-focus-ring"
            aria-label="ZuiGO WebIQ Home"
          >
            <Activity className="h-5 w-5 text-z-accent" aria-hidden="true" />
            <span className="flex items-baseline">
              Zu
              <span className="relative inline-block leading-none">
                ı
                <span
                  className="absolute left-[50%] top-[-0.05em] h-[0.22em] w-[0.22em] -translate-x-1/2 rounded-full"
                  aria-hidden="true"
                  style={{ backgroundColor: 'var(--brand-dot, var(--z-accent))' }}
                />
              </span>
              GO
              <span className="ml-1.5 font-medium text-z-ink-muted text-[0.85em]">WebIQ</span>
            </span>
          </Link>
          <nav className="hidden md:flex items-center gap-2" aria-label="Global">
            <Link
              href="/"
              className={`flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium transition-colors hover:bg-z-dark-surface ${
                pathname === "/" ? "bg-z-dark-surface text-white" : "text-z-ink-muted"
              }`}
            >
              <LayoutDashboard className="h-4 w-4" aria-hidden="true" />
              Dashboard
            </Link>
            <Link
              href="/projects"
              className={`flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium transition-colors hover:bg-z-dark-surface ${
                pathname.startsWith("/projects") ? "bg-z-dark-surface text-white" : "text-z-ink-muted"
              }`}
            >
              <Folder className="h-4 w-4" aria-hidden="true" />
              Projects
            </Link>
          </nav>
        </div>
        <div className="flex items-center gap-4">
          <Link
            href="/presentation"
            className="z-btn z-btn-sm bg-z-dark-surface text-z-ink-muted hover:text-white border-transparent"
            aria-label="Open sample report"
          >
            Sample Report
          </Link>
        </div>
      </div>
    </header>
  );
}
