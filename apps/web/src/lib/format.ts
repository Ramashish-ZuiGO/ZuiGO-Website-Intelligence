// Shared formatting helpers (FE-7 dedup). Conventions match the metric
// registry's formatMetricValue (components/metrics/MetricValue.tsx): scores
// round/clamp to 0-100, percentages show at most 1 decimal, ms durations
// switch to seconds at the 1s boundary.

export function formatScore(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "Unavailable";
  const clamped = Math.max(0, Math.min(100, Math.round(value)));
  return `${clamped}/100`;
}

export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "Unavailable";
  const rounded = Math.round(value * 10) / 10;
  return `${Number.isInteger(rounded) ? rounded.toFixed(0) : rounded.toFixed(1)}%`;
}

export function formatDurationMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || Number.isNaN(ms)) return "Unavailable";
  if (ms >= 60000) {
    const mins = Math.floor(ms / 60000);
    const secs = Math.floor((ms % 60000) / 1000);
    return `${mins} min ${secs} s`;
  }
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)} s`;
  return `${Math.round(ms)} ms`;
}

// snake_case/SCREAMING_SNAKE -> "Title Case" (replaceAll, not replace --
// a single-underscore replace silently mangles multi-word values).
export function formatLabel(value: string | null | undefined): string {
  if (!value) return "Unknown";
  return value
    .toLowerCase()
    .replaceAll("_", " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "Unavailable";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "Unavailable";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleDateString();
}
