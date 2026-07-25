import React from "react";
import { MetricValue } from "./MetricValue";

interface ScoreValueProps {
  metricId: string;
  value: number | null | "Partial";
  className?: string;
}

export function ScoreValue({ metricId, value, className }: ScoreValueProps) {
  return <MetricValue metricId={metricId} value={value} className={className} />;
}
