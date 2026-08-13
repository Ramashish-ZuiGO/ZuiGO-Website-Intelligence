import React from 'react';
import { ConceptInfoButton } from "@/components/metrics/ConceptInfoButton";
import { MetricInfoButton } from "@/components/metrics/MetricInfoButton";

export interface AccessibilityNodeData {
  html_snippet: string;
}

export interface AccessibilityFindingData {
  id: string;
  finding_type: string;
  description: string;
  rule_id: string;
  impact: string;
  nodes?: AccessibilityNodeData[];
}

export interface AccessibilityAuditData {
  violations_count: number;
  passes_count: number;
  incomplete_count: number;
  inapplicable_count: number;
}

export interface ChecklistItem {
  status: string;
  requirement: string;
  description: string;
  notes?: string;
}

export interface AccessibilityData {
  audit: AccessibilityAuditData;
  findings: AccessibilityFindingData[];
  checklist: { items: ChecklistItem[] } | null;
}

export function AccessibilityIntelligence({ accessibilityData }: { accessibilityData: AccessibilityData | null }) {
  if (!accessibilityData || !accessibilityData.audit) {
    return (
      <section className="mt-5 rounded-lg border border-slate-200 bg-white shadow-sm overflow-hidden">
        <div className="bg-slate-50 px-4 py-3 border-b border-slate-200">
          <h3 className="font-semibold text-slate-900 flex items-center gap-2">
            Accessibility Intelligence
          </h3>
        </div>
        <div className="p-8 text-center text-slate-500">
          No accessibility data available yet. Run an analysis to generate an audit.
        </div>
      </section>
    );
  }

  const { audit, checklist } = accessibilityData;
  const safeFindings = Array.isArray(accessibilityData.findings) ? accessibilityData.findings : [];
  const violations = safeFindings.filter((f) => f.finding_type === 'violation');
  const incomplete = safeFindings.filter((f) => f.finding_type === 'incomplete');

  return (
    <section className="mt-5 rounded-lg border border-slate-200 bg-white shadow-sm overflow-hidden">
      <div className="bg-slate-50 px-4 py-3 border-b border-slate-200">
        <h3 className="font-semibold text-slate-900 flex items-center gap-2">
          Accessibility Intelligence <MetricInfoButton metricId="accessibility_score" />
        </h3>
        <p className="text-sm text-slate-500 mt-1">
          Automated accessibility evidence based on WCAG standards. This does not guarantee complete WCAG, GIGW or legal compliance.
        </p>
      </div>

      <div className="p-4 grid gap-4 grid-cols-1 md:grid-cols-2 lg:grid-cols-4">
        <div className="bg-red-50 p-4 rounded-lg border border-red-100">
          <p className="text-sm font-medium text-red-800">Violations</p>
          <p className="text-2xl font-bold text-red-600 mt-1">{audit.violations_count}</p>
        </div>
        <div className="bg-emerald-50 p-4 rounded-lg border border-emerald-100">
          <p className="text-sm font-medium text-emerald-800">Passes</p>
          <p className="text-2xl font-bold text-emerald-600 mt-1">{audit.passes_count}</p>
        </div>
        <div className="bg-amber-50 p-4 rounded-lg border border-amber-100">
          <p className="text-sm font-medium text-amber-800">Incomplete (Manual Review Required)</p>
          <p className="text-2xl font-bold text-amber-600 mt-1">{audit.incomplete_count}</p>
        </div>
        <div className="bg-slate-50 p-4 rounded-lg border border-slate-100">
          <p className="flex items-center gap-1 text-sm font-medium text-slate-800">
            Inapplicable
            <ConceptInfoButton
              conceptId="accessibility_inapplicable_rules"
              title="Inapplicable accessibility rules"
            />
          </p>
          <p className="text-2xl font-bold text-slate-600 mt-1">{audit.inapplicable_count}</p>
        </div>
      </div>

      <div className="px-4 py-3 bg-white">
        <details className="mt-2 group">
          <summary className="cursor-pointer text-sm font-semibold text-slate-700 hover:text-slate-900 p-2 bg-slate-50 rounded border border-slate-200">
            Automated Violations ({violations.length})
          </summary>
          <ul className="mt-3 grid gap-3 pl-2">
            {violations.map((f: AccessibilityFindingData) => (
              <li key={f.id} className="text-sm border-l-2 border-red-400 pl-3 py-1">
                <p className="font-semibold text-slate-900">{f.description}</p>
                <p className="text-slate-600 mt-1 text-xs">Rule: {f.rule_id} · Impact: {f.impact}</p>
                {f.nodes && f.nodes.length > 0 && (
                  <div className="mt-2">
                    <p className="text-xs font-semibold text-slate-500">Affected Elements:</p>
                    <ul className="list-disc pl-4 mt-1 text-xs text-slate-600">
                      {f.nodes.slice(0, 3).map((n: AccessibilityNodeData, idx: number) => (
                        <li key={idx} className="truncate" title={n.html_snippet}>
                          <code>{n.html_snippet.substring(0, 80)}{n.html_snippet.length > 80 ? '...' : ''}</code>
                        </li>
                      ))}
                      {f.nodes.length > 3 && <li>...and {f.nodes.length - 3} more</li>}
                    </ul>
                  </div>
                )}
              </li>
            ))}
            {violations.length === 0 && <p className="text-sm text-slate-500">No automated violations found.</p>}
          </ul>
        </details>

        <details className="mt-2 group">
          <summary className="cursor-pointer text-sm font-semibold text-slate-700 hover:text-slate-900 p-2 bg-slate-50 rounded border border-slate-200">
            Incomplete (Needs Manual Review) ({incomplete.length})
          </summary>
          <ul className="mt-3 grid gap-3 pl-2">
            {incomplete.map((f: AccessibilityFindingData) => (
              <li key={f.id} className="text-sm border-l-2 border-amber-400 pl-3 py-1">
                <p className="font-semibold text-slate-900">{f.description}</p>
                <p className="text-slate-600 mt-1 text-xs">Rule: {f.rule_id}</p>
              </li>
            ))}
            {incomplete.length === 0 && <p className="text-sm text-slate-500">No incomplete items.</p>}
          </ul>
        </details>

        {checklist && Array.isArray(checklist.items) && checklist.items.length > 0 && (
          <details className="mt-2 group">
            <summary className="cursor-pointer text-sm font-semibold text-slate-700 hover:text-slate-900 p-2 bg-slate-50 rounded border border-slate-200">
              Manual Review Checklist ({checklist.items.filter((i) => i.status === 'fail').length} issues)
            </summary>
            <div className="mt-3 grid gap-3 pl-2">
              <p className="text-xs text-slate-500 mb-2">Automated tools cannot verify these requirements. Please review manually.</p>
              <ul className="space-y-2">
                {checklist.items.map((item: ChecklistItem, idx: number) => (
                  <li key={idx} className="text-sm flex items-start gap-2">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${item.status === 'pass' ? 'bg-emerald-100 text-emerald-800' : item.status === 'fail' ? 'bg-red-100 text-red-800' : 'bg-slate-100 text-slate-800'}`}>
                      {(item.status ?? "unknown").toUpperCase()}
                    </span>
                    <div>
                      <p className="font-medium text-slate-900">{item.requirement}</p>
                      {item.notes && <p className="text-slate-600 text-xs mt-1">{item.notes}</p>}
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          </details>
        )}
      </div>
    </section>
  );
}
