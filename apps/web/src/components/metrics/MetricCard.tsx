import React from "react";
import { MetricInfoButton } from "./MetricInfoButton";
import { MetricValue } from "./MetricValue";
import { ConfidenceBadge } from "./ConfidenceBadge";

interface MetricCardProps {
  metricId: string;
  value: number | string | boolean | null;
  confidence?: string | null;
  titleOverride?: string;
  className?: string;
}

export function MetricCard({
  metricId,
  value,
  confidence,
  titleOverride,
  className = "",
}: MetricCardProps) {
  return (
    <div className={`bg-white border rounded-lg shadow-sm p-4 ${className}`}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center space-x-2">
          <h3 className="text-sm font-medium text-gray-700">
            {titleOverride || metricId.replace(/_/g, " ").replace(/\b\w/g, (l) => l.toUpperCase())}
          </h3>
          <MetricInfoButton metricId={metricId} />
        </div>
        {confidence !== undefined && (
          <ConfidenceBadge confidence={confidence} />
        )}
      </div>
      <div className="text-2xl">
        <MetricValue metricId={metricId} value={value} />
      </div>
    </div>
  );
}
