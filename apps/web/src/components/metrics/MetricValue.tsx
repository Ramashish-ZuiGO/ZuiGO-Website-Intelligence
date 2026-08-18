import React from "react";
import { getMetricDefinition } from "./registry";
import { MetricValueType } from "./types";

interface MetricValueProps {
  metricId: string;
  value: number | string | boolean | null;
  className?: string;
  fallback?: React.ReactNode;
}

export function formatMetricValue(
  value: number | string | boolean | null,
  valueType: MetricValueType,
  unit?: string | null,
  displayScale?: string | null
): React.ReactNode {
  if (value === null || value === undefined) {
    return <span className="text-gray-400 italic">Not available</span>;
  }

  if (value === "Partial" || value === "partial") {
    return <span className="text-amber-600">Partial</span>;
  }

  if (valueType === "score") {
    const numValue = Number(value);
    if (isNaN(numValue)) return String(value);
    const clamped = Math.max(0, Math.min(100, Math.round(numValue)));
    return <>{clamped}{displayScale || "/100"}</>;
  }

  if (valueType === "percentage") {
    const numValue = Number(value);
    if (isNaN(numValue)) return String(value);
    // M17: raw float percentages (86.20689655172413%) rendered verbatim.
    // One decimal is plenty for a customer-facing coverage figure.
    const rounded = Math.round(numValue * 10) / 10;
    return <>{Number.isInteger(rounded) ? rounded.toFixed(0) : rounded.toFixed(1)}%</>;
  }

  if (valueType === "count") {
    const numValue = Number(value);
    if (isNaN(numValue)) return String(value);
    const safeUnit = unit || "";
    // Extremely basic pluralization
    const formattedUnit = numValue === 1 && safeUnit.endsWith("s") ? safeUnit.slice(0, -1) : safeUnit;
    return <>{new Intl.NumberFormat().format(numValue)} {formattedUnit}</>;
  }

  if (valueType === "duration") {
    const numValue = Number(value);
    if (isNaN(numValue)) return String(value);
    if (unit === "ms") {
      if (numValue >= 60000) {
        const mins = Math.floor(numValue / 60000);
        const secs = Math.floor((numValue % 60000) / 1000);
        return <>{mins} min {secs} s</>;
      }
      if (numValue >= 1000) {
        return <>{(numValue / 1000).toFixed(1)} s</>;
      }
      return <>{numValue} ms</>;
    }
    return <>{numValue} {unit}</>;
  }

  if (valueType === "bytes") {
    const numValue = Number(value);
    if (isNaN(numValue)) return String(value);
    if (numValue < 1024) return <>{numValue} B</>;
    if (numValue < 1024 * 1024) return <>{(numValue / 1024).toFixed(1)} KB</>;
    if (numValue < 1024 * 1024 * 1024) return <>{(numValue / (1024 * 1024)).toFixed(1)} MB</>;
    return <>{(numValue / (1024 * 1024 * 1024)).toFixed(1)} GB</>;
  }

  if (valueType === "boolean") {
    return value ? "Yes" : "No";
  }

  return <>{String(value)}</>;
}

export function MetricValue({ metricId, value, className = "", fallback = "Not available" }: MetricValueProps) {
  const metric = getMetricDefinition(metricId);

  if (!metric) {
    if (value === null || value === undefined) return <span className="text-gray-400 italic">{fallback}</span>;
    return <span className={className}>{String(value)}</span>;
  }

  return (
    <span className={`font-medium ${className}`}>
      {formatMetricValue(value, metric.value_type, metric.unit, metric.display_scale)}
    </span>
  );
}
