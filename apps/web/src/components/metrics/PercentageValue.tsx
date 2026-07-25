import React from "react";
import { MetricValue } from "./MetricValue";

interface PercentageValueProps {
  metricId: string;
  value: number | null | "Partial";
  className?: string;
}

export function PercentageValue({ metricId, value, className }: PercentageValueProps) {
  return <MetricValue metricId={metricId} value={value} className={className} />;
}
