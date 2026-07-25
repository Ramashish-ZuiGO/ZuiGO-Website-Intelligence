'use client';

import React, { useState } from 'react';

interface PerformanceSnapshot {
  id: string;
  metric_id: string;
  evidence_type: string;
  raw_value: number;
}

export function PerformanceIntelligence({
  data,
  disagreement,
  explanation
}: {
  data: PerformanceSnapshot[],
  disagreement?: boolean,
  explanation?: string
}) {
  const [activeTab, setActiveTab] = useState<'field' | 'lab' | 'diagnostic'>('field');

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
          <button
            onClick={() => setActiveTab('field')}
            className={`whitespace-nowrap border-b-2 py-2 px-1 text-sm font-semibold transition-colors ${
              activeTab === 'field'
                ? 'border-emerald-500 text-emerald-600'
                : 'border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-700'
            }`}
          >
            Field Evidence (CrUX)
          </button>
          <button
            onClick={() => setActiveTab('lab')}
            className={`whitespace-nowrap border-b-2 py-2 px-1 text-sm font-semibold transition-colors ${
              activeTab === 'lab'
                ? 'border-emerald-500 text-emerald-600'
                : 'border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-700'
            }`}
          >
            Lab Evidence (Lighthouse)
          </button>
          <button
            onClick={() => setActiveTab('diagnostic')}
            className={`whitespace-nowrap border-b-2 py-2 px-1 text-sm font-semibold transition-colors ${
              activeTab === 'diagnostic'
                ? 'border-emerald-500 text-emerald-600'
                : 'border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-700'
            }`}
          >
            Browser Timing
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
                    <dt className="text-xs font-semibold uppercase tracking-wider text-slate-500">{s.metric_id}</dt>
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
          <div>
            {labData.length > 0 ? (
              <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {labData.map(s => (
                  <li key={s.id} className="rounded-xl border border-slate-200 bg-slate-50 p-4 transition-shadow hover:shadow-md">
                    <dt className="text-xs font-semibold uppercase tracking-wider text-slate-500">{s.metric_id}</dt>
                    <dd className="mt-2 flex items-baseline gap-2">
                      <span className="text-3xl font-bold text-slate-900">{s.raw_value}</span>
                    </dd>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-slate-500 italic">No lab evidence available.</p>
            )}
          </div>
        )}

        {activeTab === 'diagnostic' && (
          <div>
            {diagData.length > 0 ? (
              <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {diagData.map(s => (
                  <li key={s.id} className="rounded-xl border border-slate-200 bg-slate-50 p-4 transition-shadow hover:shadow-md">
                    <dt className="text-xs font-semibold uppercase tracking-wider text-slate-500">{s.metric_id}</dt>
                    <dd className="mt-2 flex items-baseline gap-2">
                      <span className="text-3xl font-bold text-slate-900">{s.raw_value}</span>
                    </dd>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-slate-500 italic">No diagnostic evidence available.</p>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
