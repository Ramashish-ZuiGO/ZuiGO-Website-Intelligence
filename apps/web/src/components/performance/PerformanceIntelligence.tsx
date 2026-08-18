'use client';

import React, { useState } from 'react';

interface PerformanceSnapshot {
  id: string;
  metric_id: string;
  evidence_type: string;
  raw_value: number;
  url_or_origin?: string;
  form_factor?: string;
  evidence_source?: string;
}

// M16: metric ids are internal identifiers (lab_fcp, connectStart) and raw
// values are unrounded milliseconds or absolute epoch timestamps. Customers
// see human labels and formatted values; unknown ids fall back to a cleaned
// version of the id rather than hiding data.
const METRIC_LABELS: Record<string, string> = {
  lab_fcp: 'First Contentful Paint',
  lab_lcp: 'Largest Contentful Paint',
  lab_cls: 'Cumulative Layout Shift',
  lab_tbt: 'Total Blocking Time',
  lab_speed_index: 'Speed Index',
  navigationStart: 'Navigation start',
  fetchStart: 'Fetch start',
  domainLookupStart: 'DNS lookup start',
  domainLookupEnd: 'DNS lookup end',
  connectStart: 'Connection start',
  secureConnectionStart: 'TLS handshake start',
  connectEnd: 'Connection established',
  requestStart: 'Request sent',
  responseStart: 'First response byte',
  responseEnd: 'Response complete',
  domLoading: 'DOM loading',
  domInteractive: 'DOM interactive',
  domContentLoadedEventStart: 'DOMContentLoaded start',
  domContentLoadedEventEnd: 'DOMContentLoaded end',
  domComplete: 'DOM complete',
  loadEventStart: 'Load event start',
  loadEventEnd: 'Load event end',
  redirectStart: 'Redirect start',
  redirectEnd: 'Redirect end',
  unloadEventStart: 'Unload start',
  unloadEventEnd: 'Unload end',
};

function metricLabel(metricId: string): string {
  return (
    METRIC_LABELS[metricId] ??
    metricId.replace(/^lab_/, '').replace(/_/g, ' ').replace(/([a-z])([A-Z])/g, '$1 $2')
  );
}

function formatLabValue(metricId: string, value: number): string {
  if (metricId === 'lab_cls') {
    return value.toFixed(3);
  }
  if (value >= 1000) {
    return `${(value / 1000).toFixed(2)} s`;
  }
  return `${Math.round(value)} ms`;
}

function formatOffset(deltaMs: number): string {
  if (deltaMs >= 1000) {
    return `+${(deltaMs / 1000).toFixed(2)} s`;
  }
  return `+${Math.round(deltaMs)} ms`;
}

function pagePath(url: string): string {
  try {
    const parsed = new URL(url);
    return parsed.pathname === '/' ? `${parsed.hostname}` : parsed.pathname;
  } catch {
    return url;
  }
}

function groupKey(s: PerformanceSnapshot): string {
  return `${s.url_or_origin ?? 'unknown'}|${s.form_factor ?? ''}`;
}

export function PerformanceIntelligence({
  data,
  disagreement,
  explanation,
  error
}: {
  data: PerformanceSnapshot[],
  disagreement?: boolean,
  explanation?: string,
  error?: string | null
}) {
  const [activeTab, setActiveTab] = useState<'field' | 'lab' | 'diagnostic'>('lab');

  if (error) {
    return (
      <section className="mt-5 rounded-lg border border-red-200 bg-red-50 p-4 shadow-sm" role="alert">
        <h3 className="font-semibold text-slate-900">Performance Intelligence</h3>
        <p className="mt-2 text-sm text-red-800">Unable to load performance evidence: {error}</p>
      </section>
    );
  }

  if (!data || data.length === 0) {
    return (
      <section className="mt-5 rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <h3 className="font-semibold text-slate-900">Performance Intelligence</h3>
        <p className="mt-2 text-sm text-slate-500">No performance evidence available.</p>
      </section>
    );
  }

  const fieldData = data.filter(s => s.evidence_type === 'field');
  const labData = data.filter(s => s.evidence_type === 'lab');
  const diagData = data.filter(s => s.evidence_type === 'diagnostic');

  const labByPage = new Map<string, PerformanceSnapshot[]>();
  for (const s of labData) {
    const key = groupKey(s);
    labByPage.set(key, [...(labByPage.get(key) ?? []), s]);
  }

  const diagByPage = new Map<string, PerformanceSnapshot[]>();
  for (const s of diagData) {
    const key = groupKey(s);
    diagByPage.set(key, [...(diagByPage.get(key) ?? []), s]);
  }

  const tabClass = (tab: 'field' | 'lab' | 'diagnostic') =>
    `whitespace-nowrap border-b-2 py-2 px-1 text-sm font-semibold transition-colors ${
      activeTab === tab
        ? 'border-emerald-500 text-emerald-600'
        : 'border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-700'
    }`;

  return (
    <section className="mt-5 rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
      <h3 className="text-xl font-bold text-slate-900">Performance Intelligence</h3>

      {explanation && (
        <div className={`mt-4 rounded-xl p-4 ${disagreement ? 'bg-amber-50 border border-amber-300' : 'bg-emerald-50 border border-emerald-300'}`}>
          <p className={`font-semibold ${disagreement ? 'text-amber-800' : 'text-emerald-800'}`}>
            {disagreement ? 'Field/Lab Discrepancy Detected' : 'Field/Lab Alignment'}
          </p>
          <p className={`mt-1 text-sm ${disagreement ? 'text-amber-900' : 'text-emerald-900'}`}>{explanation}</p>
        </div>
      )}

      <div className="mt-6 border-b border-slate-200">
        <nav className="-mb-px flex space-x-6" aria-label="Tabs">
          <button onClick={() => setActiveTab('lab')} className={tabClass('lab')}>
            Lab Evidence (Lighthouse)
          </button>
          <button onClick={() => setActiveTab('diagnostic')} className={tabClass('diagnostic')}>
            Browser Timing
          </button>
          <button onClick={() => setActiveTab('field')} className={tabClass('field')}>
            Field Evidence (CrUX)
          </button>
        </nav>
      </div>

      <div className="mt-6">
        {activeTab === 'field' && (
          <div>
            {fieldData.length > 0 ? (
              <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {fieldData.map(s => (
                  <li key={s.id} className="rounded-xl border border-slate-200 bg-slate-50 p-4 transition-shadow hover:shadow-md">
                    <dt className="text-xs font-semibold uppercase tracking-wider text-slate-500">{metricLabel(s.metric_id)}</dt>
                    <dd className="mt-2 flex items-baseline gap-2">
                      <span className="text-3xl font-bold text-slate-900">{s.raw_value}</span>
                    </dd>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-slate-500 italic">Insufficient field evidence available. The site might not have enough traffic for CrUX data.</p>
            )}
          </div>
        )}

        {activeTab === 'lab' && (
          <div className="space-y-6">
            {labByPage.size > 0 ? (
              [...labByPage.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([key, snapshots]) => {
                const [url] = key.split('|');
                return (
                  <div key={key}>
                    <h4 className="text-sm font-semibold text-slate-700" title={url}>
                      {pagePath(url)}
                    </h4>
                    <ul className="mt-2 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                      {snapshots.sort((a, b) => a.metric_id.localeCompare(b.metric_id)).map(s => (
                        <li key={s.id} className="rounded-xl border border-slate-200 bg-slate-50 p-4 transition-shadow hover:shadow-md">
                          <dt className="text-xs font-semibold uppercase tracking-wider text-slate-500">{metricLabel(s.metric_id)}</dt>
                          <dd className="mt-2 flex items-baseline gap-2">
                            <span className="text-3xl font-bold text-slate-900">{formatLabValue(s.metric_id, s.raw_value)}</span>
                          </dd>
                        </li>
                      ))}
                    </ul>
                  </div>
                );
              })
            ) : (
              <p className="text-sm text-slate-500 italic">No lab evidence available.</p>
            )}
          </div>
        )}

        {activeTab === 'diagnostic' && (
          <div className="space-y-6">
            {diagByPage.size > 0 ? (
              [...diagByPage.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([key, snapshots]) => {
                const [url, formFactor] = key.split('|');
                const navigationStart = snapshots.find(s => s.metric_id === 'navigationStart')?.raw_value;
                const rows = snapshots
                  .filter(s => s.metric_id !== 'navigationStart')
                  .map(s => ({
                    snapshot: s,
                    // Navigation-timing values are absolute epoch milliseconds;
                    // 0 means the event did not occur on this navigation.
                    offset:
                      s.raw_value > 0 && navigationStart
                        ? s.raw_value - navigationStart
                        : null,
                  }))
                  .sort((a, b) => (a.offset ?? Number.MAX_VALUE) - (b.offset ?? Number.MAX_VALUE));
                return (
                  <div key={key}>
                    <h4 className="text-sm font-semibold text-slate-700" title={url}>
                      {pagePath(url)}
                      {formFactor && <span className="ml-2 font-normal text-slate-400">({formFactor})</span>}
                    </h4>
                    <p className="mt-1 text-xs text-slate-500">Times are relative to navigation start.</p>
                    <ul className="mt-2 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                      {rows.map(({ snapshot, offset }) => (
                        <li key={snapshot.id} className="rounded-xl border border-slate-200 bg-slate-50 p-3 transition-shadow hover:shadow-md">
                          <dt className="text-xs font-semibold uppercase tracking-wider text-slate-500">{metricLabel(snapshot.metric_id)}</dt>
                          <dd className="mt-1 flex items-baseline gap-2">
                            <span className="text-xl font-bold text-slate-900">
                              {offset === null ? 'Not recorded' : formatOffset(offset)}
                            </span>
                          </dd>
                        </li>
                      ))}
                    </ul>
                  </div>
                );
              })
            ) : (
              <p className="text-sm text-slate-500 italic">No diagnostic evidence available.</p>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
