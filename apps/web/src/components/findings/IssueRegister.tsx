"use client";

import React, { useMemo, useState } from "react";
import type { AnalysisFinding } from "@/lib/types";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Search, X, ChevronRight } from "lucide-react";
import { DataTable, Column } from "@/components/ui/DataTable";

export interface GroupedFinding {
  id: string;
  finding_code: string;
  category: string;
  title: string;
  description: string;
  severity: "critical" | "high" | "medium" | "low" | "informational";
  affectedUrls: Set<string>;
  occurrences: AnalysisFinding[];
  totalOccurrences: number;
  confidence_percent: number;
}

export function groupFindings(findings: AnalysisFinding[]): GroupedFinding[] {
  const grouped = new Map<string, GroupedFinding>();
  for (const f of findings) {
    if (!grouped.has(f.id)) {
      grouped.set(f.id, {
        id: f.id,
        finding_code: f.finding_code,
        category: f.category,
        title: f.title,
        description: f.description,
        severity: f.severity,
        affectedUrls: new Set(),
        occurrences: [],
        totalOccurrences: 0,
        confidence_percent: f.confidence_percent,
      });
    }
    const group = grouped.get(f.id)!;
    group.affectedUrls.add(f.affected_url);
    group.occurrences.push(f);
    group.totalOccurrences += 1;
  }
  return Array.from(grouped.values()).sort((a, b) => {
    const sevOrder: Record<string, number> = {
      critical: 0,
      high: 1,
      medium: 2,
      low: 3,
      informational: 4,
    };
    const diff = (sevOrder[a.severity] ?? 5) - (sevOrder[b.severity] ?? 5);
    if (diff !== 0) return diff;
    return b.totalOccurrences - a.totalOccurrences;
  });
}

interface IssueRegisterProps {
  findings: AnalysisFinding[];
}

export function IssueRegister({ findings }: IssueRegisterProps) {
  const grouped = useMemo(() => groupFindings(findings), [findings]);

  const [searchQuery, setSearchQuery] = useState("");
  const [severityFilter, setSeverityFilter] = useState<string>("all");
  const [categoryFilter, setCategoryFilter] = useState<string>("all");
  const [selectedFindingId, setSelectedFindingId] = useState<string | null>(null);

  const categories = useMemo(() => Array.from(new Set(grouped.map(g => g.category))), [grouped]);

  const filtered = useMemo(() => {
    return grouped.filter(g => {
      const matchSearch = g.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
                          g.finding_code.toLowerCase().includes(searchQuery.toLowerCase());
      const matchSeverity = severityFilter === "all" || g.severity === severityFilter;
      const matchCategory = categoryFilter === "all" || g.category === categoryFilter;
      return matchSearch && matchSeverity && matchCategory;
    });
  }, [grouped, searchQuery, severityFilter, categoryFilter]);

  const selectedFinding = useMemo(() =>
    grouped.find(g => g.id === selectedFindingId) ?? null
  , [grouped, selectedFindingId]);

  const columns: Column<GroupedFinding>[] = [
    {
      key: "severity",
      header: "Severity",
      render: (row) => <StatusBadge status={row.severity} />,
      className: "w-24",
    },
    {
      key: "issue",
      header: "Issue",
      render: (row) => (
        <div>
          <p className="font-semibold text-z-text">{row.title}</p>
          <p className="text-xs text-z-text-subtle font-mono mt-0.5">{row.finding_code}</p>
        </div>
      ),
    },
    {
      key: "category",
      header: "Category",
      render: (row) => <span className="capitalize">{row.category.replace(/_/g, " ")}</span>,
    },
    {
      key: "pages",
      header: "Affected Pages",
      render: (row) => row.affectedUrls.size.toString(),
      className: "text-right w-32",
    },
    {
      key: "occurrences",
      header: "Occurrences",
      render: (row) => row.totalOccurrences.toString(),
      className: "text-right w-32",
    },
    {
      key: "actions",
      header: "",
      render: (row) => (
        <div className="flex justify-end text-z-muted transition-colors opacity-50 hover:opacity-100">
          <span className="sr-only">View details</span>
          <ChevronRight className="h-5 w-5" />
        </div>
      ),
      className: "w-10",
    }
  ];

  return (
    <div className="flex flex-col md:flex-row gap-6 relative h-full">
      {/* Main Register List */}
      <div className={`flex-1 flex flex-col gap-4 transition-all duration-300 ${selectedFinding ? 'hidden lg:flex lg:w-2/3' : 'w-full'}`}>

        {/* Filters */}
        <div className="flex flex-wrap items-center gap-3 bg-z-surface p-4 rounded-xl border border-z-border">
          <div className="relative flex-1 min-w-[200px]">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-z-muted" />
            <input
              type="text"
              placeholder="Search findings..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-9 pr-4 py-2 bg-z-background border border-z-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-z-primary/50"
            />
          </div>

          <select
            value={severityFilter}
            onChange={(e) => setSeverityFilter(e.target.value)}
            className="px-3 py-2 bg-z-background border border-z-border rounded-lg text-sm font-medium focus:outline-none focus:ring-2 focus:ring-z-primary/50"
          >
            <option value="all">All Severities</option>
            <option value="critical">Critical</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
            <option value="informational">Informational</option>
          </select>

          <select
            value={categoryFilter}
            onChange={(e) => setCategoryFilter(e.target.value)}
            className="px-3 py-2 bg-z-background border border-z-border rounded-lg text-sm font-medium focus:outline-none focus:ring-2 focus:ring-z-primary/50 capitalize"
          >
            <option value="all">All Categories</option>
            {categories.map(c => (
              <option key={c} value={c}>{c.replace(/_/g, " ")}</option>
            ))}
          </select>

          <div className="text-sm font-semibold text-z-muted ml-auto whitespace-nowrap">
            {filtered.length === grouped.length
              ? `${grouped.length} finding${grouped.length === 1 ? '' : 's'}`
              : `${filtered.length} of ${grouped.length} finding${grouped.length === 1 ? '' : 's'}`}
          </div>
        </div>

        {/* Data Table (Desktop) */}
        <div className="bg-z-surface border border-z-border rounded-xl overflow-hidden shadow-sm hidden md:block">
          <DataTable<GroupedFinding>
            columns={columns}
            data={filtered}
            onRowClick={(row) => setSelectedFindingId(row.id)}
            keyExtractor={(row) => row.id}
            emptyMessage="No findings match your filters."
          />
        </div>

        {/* Mobile Cards */}
        <div className="md:hidden flex flex-col gap-3">
          {filtered.length === 0 ? (
            <div className="p-6 text-center text-sm text-z-muted border border-z-border rounded-xl bg-z-surface">
              No findings match your filters.
            </div>
          ) : (
            filtered.map((row) => (
              <button
                key={row.id}
                onClick={() => setSelectedFindingId(row.id)}
                className="text-left bg-z-surface border border-z-border rounded-xl p-4 flex items-center justify-between shadow-sm hover:border-z-primary/30 active:scale-[0.99] transition-all"
              >
                <div className="flex-1 min-w-0 pr-4">
                  <div className="mb-2"><StatusBadge status={row.severity} size="sm" /></div>
                  <p className="font-bold text-z-text text-sm mb-1 leading-tight">{row.title}</p>
                  <p className="text-xs text-z-text-subtle capitalize mb-2">{row.category.replace(/_/g, " ")}</p>
                  <p className="text-xs font-semibold text-z-muted">
                    {row.affectedUrls.size} page{row.affectedUrls.size !== 1 ? 's' : ''} &middot; {row.totalOccurrences} occurrence{row.totalOccurrences !== 1 ? 's' : ''}
                  </p>
                </div>
                <div className="text-z-muted flex-shrink-0">
                  <ChevronRight className="h-5 w-5 opacity-50" />
                </div>
              </button>
            ))
          )}
        </div>
      </div>

      {/* Detail Panel */}
      {selectedFinding && (
        <div className="w-full lg:w-1/3 bg-z-surface border border-z-border rounded-xl shadow-lg flex flex-col sticky top-6 self-start max-h-[calc(100vh-4rem)] overflow-y-auto">
          <div className="p-5 border-b border-z-border sticky top-0 bg-z-surface/95 backdrop-blur z-10 flex items-start justify-between">
            <div className="min-w-0">
              <StatusBadge status={selectedFinding.severity} size="sm" />
              <h3 className="text-lg font-bold text-z-text mt-3 leading-tight">{selectedFinding.title}</h3>
              <p className="text-xs font-mono text-z-muted mt-1">{selectedFinding.finding_code}</p>
            </div>
            <button
              onClick={() => setSelectedFindingId(null)}
              className="p-1.5 text-z-muted hover:text-z-text hover:bg-z-neutral-subtle rounded-md transition-colors"
              aria-label="Close details"
            >
              <X className="h-5 w-5" />
            </button>
          </div>

          <div className="p-5 flex flex-col gap-6">
            <section>
              <h4 className="text-sm font-bold text-z-text mb-2">Description</h4>
              <p className="text-sm text-z-text-subtle leading-relaxed">
                {selectedFinding.description}
              </p>
            </section>

            <section className="bg-z-neutral-subtle/50 rounded-lg p-4 border border-z-border/50">
              <div className="flex justify-between items-center mb-3">
                <h4 className="text-sm font-bold text-z-text">Affected Pages</h4>
                <span className="text-xs font-semibold bg-z-background px-2 py-0.5 rounded text-z-muted">
                  {selectedFinding.affectedUrls.size} Total
                </span>
              </div>
              <ul className="text-sm text-z-text-subtle space-y-2 max-h-48 overflow-y-auto pr-2 custom-scrollbar">
                {Array.from(selectedFinding.affectedUrls).map(url => (
                  <li key={url} className="break-all font-mono text-xs bg-z-background border border-z-border p-2 rounded truncate" title={url}>
                    {url}
                  </li>
                ))}
              </ul>
            </section>

            <section>
              <h4 className="text-sm font-bold text-z-text mb-2 flex justify-between">
                <span>Evidence Examples</span>
                <span className="text-xs font-normal text-z-muted">First 3 occurrences</span>
              </h4>
              <div className="space-y-3">
                {selectedFinding.occurrences.slice(0, 3).map((occ, idx) => (
                  <div key={idx} className="bg-z-background border border-z-border rounded-lg p-3 overflow-x-auto">
                    <pre className="text-[10px] font-mono text-z-text-subtle">
                      {JSON.stringify(occ.evidence, null, 2)}
                    </pre>
                  </div>
                ))}
              </div>
            </section>
          </div>
        </div>
      )}
    </div>
  );
}
