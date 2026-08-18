"use client";

import React, { useState, useEffect } from "react";
import { apiRequest } from "@/lib/api";
import type { ExtractedContent } from "@/lib/types";
import { EmptyState } from "@/components/ui/EmptyState";

type Tab =
  | "overview"
  | "sections"
  | "tables"
  | "faqs"
  | "images"
  | "links"
  | "downloads"
  | "structured"
  | "raw";

function Badge({ children, variant = "default" }: { children: React.ReactNode; variant?: "default" | "success" | "info" | "muted" }) {
  const styles = {
    default: "bg-slate-100 text-slate-700 border-slate-200",
    success: "bg-emerald-50 text-emerald-700 border-emerald-200",
    info: "bg-blue-50 text-blue-700 border-blue-200",
    muted: "bg-slate-50 text-slate-500 border-slate-100",
  };
  return (
    <span className={`inline-flex items-center px-2 py-0.5 text-xs font-medium rounded-full border ${styles[variant]}`}>
      {children}
    </span>
  );
}

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex flex-col items-center justify-center p-4 bg-white rounded-xl border border-slate-200 shadow-sm">
      <span className="text-2xl font-semibold text-slate-900">{value}</span>
      <span className="text-xs text-slate-500 mt-1">{label}</span>
    </div>
  );
}

function SectionHeading({ children }: { children: React.ReactNode }) {
  return <h3 className="text-base font-semibold text-slate-900 mb-3">{children}</h3>;
}

function normalizeContent(raw: ExtractedContent): ExtractedContent {
  return {
    ...raw,
    sections: Array.isArray(raw.sections) ? raw.sections : [],
    headings: Array.isArray(raw.headings) ? raw.headings : [],
    paragraphs: Array.isArray(raw.paragraphs) ? raw.paragraphs : [],
    tables: Array.isArray(raw.tables) ? raw.tables : [],
    faqs: Array.isArray(raw.faqs) ? raw.faqs : [],
    images: Array.isArray(raw.images) ? raw.images : [],
    important_links: Array.isArray(raw.important_links) ? raw.important_links : [],
    downloadable_files: Array.isArray(raw.downloadable_files) ? raw.downloadable_files : [],
    structured_data: raw.structured_data && typeof raw.structured_data === "object" ? raw.structured_data : {},
    metadata: raw.metadata && typeof raw.metadata === "object" ? raw.metadata : {},
    content_stats: raw.content_stats ?? { word_count: 0, paragraph_count: 0, heading_count: 0, table_count: 0, faq_count: 0, image_count: 0, link_count: 0, download_count: 0 },
  };
}

export default function ExtractedContentPanel({ analysisRunId }: { analysisRunId: string }) {
  const [content, setContent] = useState<ExtractedContent | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<Tab>("overview");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        setLoading(true);
        setError(null);
        const data = await apiRequest<ExtractedContent>(
          `/api/v1/analysis-runs/${analysisRunId}/extracted-content`
        );
        if (!cancelled) setContent(normalizeContent(data));
      } catch (err) {
        if (cancelled) return;
        const message = err instanceof Error ? err.message : "Failed to load content";
        if (message.includes("not available")) {
          setError("Content extraction is not available for this analysis run.");
        } else {
          setError(message);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => { cancelled = true; };
  }, [analysisRunId]);

  if (loading) {
    return (
      <div className="space-y-4 p-6">
        <div className="h-8 bg-slate-100 rounded-lg animate-pulse w-1/3" />
        <div className="grid grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-20 bg-slate-100 rounded-xl animate-pulse" />
          ))}
        </div>
        <div className="h-64 bg-slate-100 rounded-xl animate-pulse" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 text-amber-800 text-sm">
          {error}
        </div>
      </div>
    );
  }

  if (!content) return null;

  const tabs: { id: Tab; label: string; count?: number }[] = [
    { id: "overview", label: "Overview" },
    { id: "sections", label: "Sections", count: content.content_stats.heading_count },
    { id: "tables", label: "Tables", count: content.content_stats.table_count },
    { id: "faqs", label: "FAQs", count: content.content_stats.faq_count },
    { id: "images", label: "Images", count: content.content_stats.image_count },
    { id: "links", label: "Links", count: content.content_stats.link_count },
    { id: "downloads", label: "Downloads", count: content.content_stats.download_count },
    { id: "structured", label: "Structured Data" },
    { id: "raw", label: "Full Text" },
  ];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-xl font-semibold text-slate-900">Extracted Content</h2>
          <p className="text-sm text-slate-500 mt-1">
            Clean, structured content extracted from the analyzed page
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant={content.extraction_status === "completed" ? "success" : "muted"}>
            {content.extraction_status}
          </Badge>
          <Badge variant="info">{content.page_type_hint}</Badge>
        </div>
      </div>

      {/* Title & Summary */}
      {content.title && (
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5">
          <h3 className="text-lg font-semibold text-slate-900">{content.title}</h3>
          {content.summary && (
            <p className="text-sm text-slate-600 mt-2 leading-relaxed">{content.summary}</p>
          )}
          <div className="flex flex-wrap gap-3 mt-3 text-xs text-slate-500">
            {content.metadata.author ? <span>By {String(content.metadata.author)}</span> : null}
            {content.metadata.date ? <span>{String(content.metadata.date)}</span> : null}
            {content.metadata.sitename ? <span>{String(content.metadata.sitename)}</span> : null}
          </div>
        </div>
      )}

      {/* Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-3">
        <StatCard label="Words" value={content.content_stats.word_count} />
        <StatCard label="Paragraphs" value={content.content_stats.paragraph_count} />
        <StatCard label="Headings" value={content.content_stats.heading_count} />
        <StatCard label="Tables" value={content.content_stats.table_count} />
        <StatCard label="FAQs" value={content.content_stats.faq_count} />
        <StatCard label="Images" value={content.content_stats.image_count} />
        <StatCard label="Links" value={content.content_stats.link_count} />
        <StatCard label="Downloads" value={content.content_stats.download_count} />
      </div>

      {/* Tabs */}
      <div className="border-b border-slate-200">
        <nav className="flex gap-1 overflow-x-auto" role="tablist">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              role="tab"
              aria-selected={activeTab === tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-3 py-2 text-sm font-medium rounded-t-lg whitespace-nowrap transition-colors ${
                activeTab === tab.id
                  ? "bg-white text-slate-900 border border-b-0 border-slate-200"
                  : "text-slate-500 hover:text-slate-700 hover:bg-slate-50"
              }`}
            >
              {tab.label}
              {tab.count !== undefined && tab.count > 0 && (
                <span className="ml-1.5 text-xs bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded-full">
                  {tab.count}
                </span>
              )}
            </button>
          ))}
        </nav>
      </div>

      {/* Tab Content */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm">
        {activeTab === "overview" && <OverviewTab content={content} />}
        {activeTab === "sections" && <SectionsTab content={content} />}
        {activeTab === "tables" && <TablesTab content={content} />}
        {activeTab === "faqs" && <FAQsTab content={content} />}
        {activeTab === "images" && <ImagesTab content={content} />}
        {activeTab === "links" && <LinksTab content={content} />}
        {activeTab === "downloads" && <DownloadsTab content={content} />}
        {activeTab === "structured" && <StructuredDataTab content={content} />}
        {activeTab === "raw" && <RawTextTab content={content} />}
      </div>
    </div>
  );
}

function OverviewTab({ content }: { content: ExtractedContent }) {
  return (
    <div className="p-5 space-y-6">
      {content.paragraphs.length > 0 ? (
        <div>
          <SectionHeading>Key Content</SectionHeading>
          <div className="space-y-3">
            {content.paragraphs.slice(0, 5).map((para, i) => (
              <p key={i} className="text-sm text-slate-700 leading-relaxed">{para}</p>
            ))}
            {content.paragraphs.length > 5 && (
              <p className="text-xs text-slate-400">
                + {content.paragraphs.length - 5} more paragraphs
              </p>
            )}
          </div>
        </div>
      ) : (
        <EmptyState title="No content paragraphs extracted" />
      )}

      {content.headings.length > 0 && (
        <div>
          <SectionHeading>Page Structure</SectionHeading>
          <div className="space-y-1">
            {content.headings.slice(0, 15).map((h, i) => (
              <div
                key={i}
                className="flex items-center gap-2 text-sm"
                style={{ paddingLeft: `${(h.level - 1) * 16}px` }}
              >
                <span className="text-xs font-mono text-slate-400 w-5 shrink-0">H{h.level}</span>
                <span className="text-slate-700">{h.text}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {content.metadata && Object.keys(content.metadata).length > 0 && (
        <div>
          <SectionHeading>Metadata</SectionHeading>
          <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2">
            {Object.entries(content.metadata).map(([key, value]) => (
              <div key={key} className="flex gap-2 text-sm">
                <dt className="text-slate-500 font-medium capitalize shrink-0">{key}:</dt>
                <dd className="text-slate-700 truncate">{String(value)}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </div>
  );
}

function SectionsTab({ content }: { content: ExtractedContent }) {
  if (content.sections.length === 0) return <EmptyState title="No sections extracted" />;
  return (
    <div className="p-5">
      <div className="space-y-1">
        {content.sections.map((section, i) => (
          <div
            key={i}
            className="flex items-center gap-3 py-2 px-3 rounded-lg hover:bg-slate-50"
            style={{ paddingLeft: `${(section.level - 1) * 20 + 12}px` }}
          >
            <Badge variant="muted">H{section.level}</Badge>
            <span className="text-sm text-slate-800">{section.heading}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function TablesTab({ content }: { content: ExtractedContent }) {
  if (content.tables.length === 0) return <EmptyState title="No tables found on this page" />;
  return (
    <div className="p-5 space-y-6">
      {content.tables.map((table, ti) => (
        <div key={ti} className="border border-slate-200 rounded-lg overflow-hidden">
          {table.caption && (
            <div className="bg-slate-50 px-4 py-2 text-sm font-medium text-slate-700 border-b border-slate-200">
              {table.caption}
            </div>
          )}
          <div className="overflow-x-auto" tabIndex={0} role="region" aria-label={table.caption || `Table ${ti + 1}`}>
            <table className="w-full text-sm">
              {Array.isArray(table.headers) && table.headers.length > 0 && (
                <thead>
                  <tr className="bg-slate-50">
                    {table.headers.map((h, hi) => (
                      <th key={hi} className="px-4 py-2 text-left font-medium text-slate-600 border-b border-slate-200">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
              )}
              <tbody>
                {(Array.isArray(table.rows) ? table.rows : []).slice(0, 20).map((row, ri) => (
                  <tr key={ri} className="border-b border-slate-100 last:border-0">
                    {(Array.isArray(row) ? row : []).map((cell, ci) => (
                      <td key={ci} className="px-4 py-2 text-slate-700">{cell}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {table.row_count > 20 && (
            <div className="px-4 py-2 text-xs text-slate-400 bg-slate-50 border-t border-slate-200">
              Showing 20 of {table.row_count} rows
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function FAQsTab({ content }: { content: ExtractedContent }) {
  if (content.faqs.length === 0) return <EmptyState title="No FAQs found on this page" />;
  return (
    <div className="p-5 space-y-3">
      {content.faqs.map((faq, i) => (
        <details key={i} className="group border border-slate-200 rounded-lg">
          <summary className="flex items-center justify-between px-4 py-3 cursor-pointer text-sm font-medium text-slate-800 hover:bg-slate-50 rounded-lg">
            <span>{faq.question}</span>
            <Badge variant="muted">{faq.source.replace("_", " ")}</Badge>
          </summary>
          <div className="px-4 pb-4 text-sm text-slate-600 leading-relaxed border-t border-slate-100 pt-3">
            {faq.answer}
          </div>
        </details>
      ))}
    </div>
  );
}

function ImagesTab({ content }: { content: ExtractedContent }) {
  if (content.images.length === 0) return <EmptyState title="No meaningful images found" />;
  return (
    <div className="p-5">
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {content.images.map((img, i) => (
          <div key={i} className="border border-slate-200 rounded-lg overflow-hidden">
            <div className="bg-slate-50 aspect-video flex items-center justify-center overflow-hidden">
              <img
                src={img.src}
                alt={img.alt || ""}
                className="max-w-full max-h-full object-contain"
                loading="lazy"
                referrerPolicy="no-referrer"
              />
            </div>
            <div className="p-3 space-y-1">
              {img.alt && <p className="text-xs text-slate-600 line-clamp-2">{img.alt}</p>}
              {img.width && img.height && (
                <p className="text-xs text-slate-400">{img.width} × {img.height}</p>
              )}
              <p className="text-xs text-slate-400 truncate">{img.src}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function LinksTab({ content }: { content: ExtractedContent }) {
  if (content.important_links.length === 0) return <EmptyState title="No important links found" />;
  const internal = content.important_links.filter((l) => l.is_internal);
  const external = content.important_links.filter((l) => !l.is_internal);
  return (
    <div className="p-5 space-y-6">
      {internal.length > 0 && (
        <div>
          <SectionHeading>Internal Links ({internal.length})</SectionHeading>
          <div className="space-y-1">
            {internal.map((link, i) => (
              <div key={i} className="flex items-center gap-3 py-1.5 text-sm">
                <span className="text-slate-700 font-medium">{link.text}</span>
                <span className="text-slate-400 truncate text-xs">{link.url}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      {external.length > 0 && (
        <div>
          <SectionHeading>External Links ({external.length})</SectionHeading>
          <div className="space-y-1">
            {external.map((link, i) => (
              <div key={i} className="flex items-center gap-3 py-1.5 text-sm">
                <span className="text-slate-700 font-medium">{link.text}</span>
                <span className="text-slate-400 truncate text-xs">{link.url}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function DownloadsTab({ content }: { content: ExtractedContent }) {
  if (content.downloadable_files.length === 0) return <EmptyState title="No downloadable files found" />;
  return (
    <div className="p-5">
      <div className="space-y-2">
        {content.downloadable_files.map((file, i) => (
          <div key={i} className="flex items-center gap-3 p-3 border border-slate-200 rounded-lg hover:bg-slate-50">
            <div className="w-10 h-10 bg-slate-100 rounded-lg flex items-center justify-center text-xs font-bold text-slate-500 uppercase">
              {file.file_type || "?"}
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-slate-800 truncate">{file.text || file.url}</p>
              <p className="text-xs text-slate-400 truncate">{file.url}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function StructuredDataTab({ content }: { content: ExtractedContent }) {
  const { structured_data } = content;
  const hasData = Object.keys(structured_data).length > 0;
  if (!hasData) return <EmptyState title="No structured data (JSON-LD, Open Graph, Microdata) found" />;
  return (
    <div className="p-5 space-y-4">
      {Object.entries(structured_data).map(([key, value]) => (
        <div key={key}>
          <SectionHeading>{key.replace("_", "-").toUpperCase()}</SectionHeading>
          <pre className="bg-slate-50 border border-slate-200 rounded-lg p-4 text-xs text-slate-700 overflow-x-auto max-h-96">
            {JSON.stringify(value, null, 2)}
          </pre>
        </div>
      ))}
    </div>
  );
}

function RawTextTab({ content }: { content: ExtractedContent }) {
  if (!content.main_content) return <EmptyState title="No text content extracted" />;
  return (
    <div className="p-5">
      <div className="bg-slate-50 border border-slate-200 rounded-lg p-5 max-h-[600px] overflow-y-auto">
        <div className="text-sm text-slate-700 leading-relaxed whitespace-pre-wrap">
          {content.main_content}
        </div>
      </div>
    </div>
  );
}
