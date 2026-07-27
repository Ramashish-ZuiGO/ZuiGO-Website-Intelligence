import type { ReactNode } from "react";

const PRIVATE_KEYS = new Set([
  "chainofthought",
  "hiddenreasoning",
  "internalmonologue",
  "privatereasoning",
  "reasoning",
  "scratchpad",
  "secret",
  "password",
  "apikey",
  "authorization",
  "credential",
  "accesstoken",
  "refreshtoken",
]);
const MAX_ITEMS = 50;
const MAX_DEPTH = 5;

function safeEntries(value: Record<string, unknown>): Array<[string, unknown]> {
  return Object.entries(value)
    .filter(([key]) => !PRIVATE_KEYS.has(key.toLowerCase().replaceAll(/[^a-z0-9]/g, "")))
    .slice(0, MAX_ITEMS);
}

function renderValue(value: unknown, depth: number): ReactNode {
  if (value === null || value === undefined || value === "") {
    return <span className="text-slate-500">Unavailable</span>;
  }
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "Unavailable";
  if (typeof value === "string") {
    return <span className="break-all whitespace-pre-wrap">{value}</span>;
  }
  if (depth >= MAX_DEPTH) {
    return <span className="text-slate-500">Additional structured detail retained</span>;
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="text-slate-500">None</span>;
    return (
      <ul className="grid gap-1 pl-4">
        {value.slice(0, MAX_ITEMS).map((item, index) => (
          <li className="list-disc" key={index}>
            {renderValue(item, depth + 1)}
          </li>
        ))}
      </ul>
    );
  }
  if (typeof value === "object") {
    const entries = safeEntries(value as Record<string, unknown>);
    if (entries.length === 0) return <span className="text-slate-500">None</span>;
    return (
      <dl className="grid gap-2">
        {entries.map(([key, item]) => (
          <div className="rounded-lg bg-slate-50 p-2" key={key}>
            <dt className="text-xs font-semibold text-slate-500">
              {key.replaceAll("_", " ")}
            </dt>
            <dd className="mt-1">{renderValue(item, depth + 1)}</dd>
          </div>
        ))}
      </dl>
    );
  }
  return String(value);
}

export function SafeStructuredValue({ value }: { value: unknown }) {
  return <div className="text-sm text-slate-700">{renderValue(value, 0)}</div>;
}
