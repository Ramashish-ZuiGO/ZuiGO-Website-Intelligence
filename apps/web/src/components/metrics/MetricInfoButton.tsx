"use client";

import React from "react";
import { getSafeMetricExplanation } from "./explanations";
import { getMetricDefinition } from "./registry";
import { AccessibleExplanation } from "./AccessibleExplanation";

interface MetricInfoButtonProps {
  metricId: string;
  className?: string;
}

export function MetricInfoButton({ metricId, className = "" }: MetricInfoButtonProps) {
  const metric = getMetricDefinition(metricId);

  if (!metric) return null;
  const content = getSafeMetricExplanation(metric);
  if (!content) return null;

  return (
    <AccessibleExplanation
      title={metric.label}
      content={content}
      shortTooltip={content.shortTooltip}
      className={className}
    />
  );
}
