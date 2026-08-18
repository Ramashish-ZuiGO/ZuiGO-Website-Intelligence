"use client";

import { useState, useMemo } from "react";

export interface Column<T> {
  key: string;
  header: string;
  render: (row: T, index: number) => React.ReactNode;
  sortable?: boolean;
  sortValue?: (row: T) => string | number;
  className?: string;
  headerClassName?: string;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  data: T[];
  pageSize?: number;
  keyExtractor: (row: T, index: number) => string;
  emptyMessage?: string;
  caption?: string;
  compact?: boolean;
  searchable?: boolean;
  searchPlaceholder?: string;
  searchFilter?: (row: T, query: string) => boolean;
  stickyHeader?: boolean;
  onRowClick?: (row: T) => void;
}

function Pagination({
  page,
  pageCount,
  total,
  pageSize,
  onPageChange,
}: {
  page: number;
  pageCount: number;
  total: number;
  pageSize: number;
  onPageChange: (page: number) => void;
}) {
  if (pageCount <= 1) return null;
  const start = page * pageSize + 1;
  const end = Math.min((page + 1) * pageSize, total);
  return (
    <nav
      aria-label="Table pagination"
      className="flex items-center justify-between gap-3 pt-3 text-sm"
    >
      <span className="text-slate-500">
        {start}–{end} of {total}
      </span>
      <div className="flex gap-1.5">
        <button
          type="button"
          className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50 disabled:opacity-40"
          disabled={page === 0}
          onClick={() => onPageChange(page - 1)}
        >
          Previous
        </button>
        <button
          type="button"
          className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50 disabled:opacity-40"
          disabled={page >= pageCount - 1}
          onClick={() => onPageChange(page + 1)}
        >
          Next
        </button>
      </div>
    </nav>
  );
}

export function DataTable<T>({
  columns,
  data,
  pageSize = 20,
  keyExtractor,
  emptyMessage = "No data available.",
  caption,
  compact = false,
  searchable = false,
  searchPlaceholder = "Search…",
  searchFilter,
  stickyHeader = false,
  onRowClick,
}: DataTableProps<T>) {
  const [page, setPage] = useState(0);
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  const filtered = useMemo(() => {
    if (!search.trim() || !searchFilter) return data;
    const q = search.trim().toLowerCase();
    return data.filter((row) => searchFilter(row, q));
  }, [data, search, searchFilter]);

  const sorted = useMemo(() => {
    if (!sortKey) return filtered;
    const col = columns.find((c) => c.key === sortKey);
    if (!col?.sortValue) return filtered;
    const fn = col.sortValue;
    return [...filtered].sort((a, b) => {
      const va = fn(a);
      const vb = fn(b);
      const cmp = typeof va === "number" && typeof vb === "number"
        ? va - vb
        : String(va).localeCompare(String(vb));
      return sortDir === "asc" ? cmp : -cmp;
    });
  }, [filtered, sortKey, sortDir, columns]);

  const pageCount = Math.max(1, Math.ceil(sorted.length / pageSize));
  const safePage = Math.min(page, pageCount - 1);
  const visible = sorted.slice(safePage * pageSize, (safePage + 1) * pageSize);

  const handleSort = (key: string) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
    setPage(0);
  };

  const cellPadding = compact ? "px-2 py-1.5" : "px-3 py-2.5";

  return (
    <div>
      {searchable && (
        <div className="mb-3">
          <input
            type="search"
            placeholder={searchPlaceholder}
            aria-label={caption ? `Search ${caption}` : searchPlaceholder.replace(/[.…]+$/, "") || "Search table"}
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(0);
            }}
            className="w-full max-w-xs rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
        </div>
      )}
      <div className="overflow-x-auto overscroll-x-contain rounded-lg border border-slate-200">
        <table className="w-full border-collapse text-left text-sm">
          {caption && (
            <caption className="sr-only">{caption}</caption>
          )}
          <thead>
            <tr className={`border-b border-slate-200 bg-slate-50 ${stickyHeader ? "sticky top-0 z-10" : ""}`}>
              {columns.map((col) => (
                <th
                  key={col.key}
                  scope="col"
                  aria-sort={
                    !col.sortable
                      ? undefined
                      : sortKey !== col.key
                        ? "none"
                        : sortDir === "asc"
                          ? "ascending"
                          : "descending"
                  }
                  className={`${cellPadding} text-xs font-semibold uppercase tracking-wide text-slate-500 ${col.headerClassName ?? ""}`}
                >
                  {col.sortable ? (
                    <button
                      className="inline-flex items-center gap-1 hover:text-slate-700"
                      onClick={() => handleSort(col.key)}
                      type="button"
                    >
                      {col.header}
                      {sortKey === col.key && (
                        <span aria-hidden="true">
                          {sortDir === "asc" ? "↑" : "↓"}
                        </span>
                      )}
                    </button>
                  ) : (
                    <span className="inline-flex items-center gap-1">{col.header}</span>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {visible.length > 0 ? (
              visible.map((row, index) => (
                <tr
                  key={keyExtractor(row, safePage * pageSize + index)}
                  className={`transition-colors hover:bg-slate-50 ${onRowClick ? "cursor-pointer" : ""}`}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                  onKeyDown={
                    onRowClick
                      ? (event) => {
                          if (event.key === "Enter" || event.key === " ") {
                            event.preventDefault();
                            onRowClick(row);
                          }
                        }
                      : undefined
                  }
                  role={onRowClick ? "button" : undefined}
                  tabIndex={onRowClick ? 0 : undefined}
                >
                  {columns.map((col) => (
                    <td
                      key={col.key}
                      className={`${cellPadding} ${col.className ?? ""}`}
                    >
                      {col.render(row, safePage * pageSize + index)}
                    </td>
                  ))}
                </tr>
              ))
            ) : (
              <tr>
                <td
                  colSpan={columns.length}
                  className={`${cellPadding} text-center text-slate-500`}
                >
                  {emptyMessage}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <Pagination
        page={safePage}
        pageCount={pageCount}
        total={sorted.length}
        pageSize={pageSize}
        onPageChange={setPage}
      />
    </div>
  );
}
