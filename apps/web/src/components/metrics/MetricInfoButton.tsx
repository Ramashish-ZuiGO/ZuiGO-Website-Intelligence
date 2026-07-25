"use client";

import React from "react";
import { getMetricDefinition } from "./registry";
import { AccessibleExplanation } from "./AccessibleExplanation";

interface MetricInfoButtonProps {
  metricId: string;
  className?: string;
}

export function MetricInfoButton({ metricId, className = "" }: MetricInfoButtonProps) {
  const metric = getMetricDefinition(metricId);

  if (!metric) return null;

  return (
    <AccessibleExplanation
      title={metric.label}
      explanation={metric.explanation}
      className={className}
    >
      <div>
        <h3 className="font-medium text-gray-900 mb-1">Value Type & Unit</h3>
        <p className="capitalize">
          {metric.value_type} {metric.unit ? `(${metric.unit})` : ""}
        </p>
      </div>

      <div>
        <h3 className="font-medium text-gray-900 mb-1">Evidence Source</h3>
        <p>{metric.evidence_source}</p>
      </div>

      <div>
        <h3 className="font-medium text-gray-900 mb-1">Calculation</h3>
        <p>{metric.calculation_summary}</p>
      </div>

      <div>
        <h3 className="font-medium text-gray-900 mb-1">Interpretation</h3>
        <p>
          {metric.interpretation_guidance}{" "}
          {metric.higher_is_better === true && "Generally, a higher value is better."}
          {metric.higher_is_better === false && "Generally, a lower value is better."}
        </p>
      </div>

      {metric.methodology_version && (
        <div>
          <h3 className="font-medium text-gray-900 mb-1">Methodology Version</h3>
          <p>{metric.methodology_version}</p>
        </div>
      )}

      {metric.known_limitations && (
        <div className="bg-amber-50 p-3 rounded text-amber-800">
          <h3 className="font-medium mb-1">Limitations</h3>
          <p>{metric.known_limitations}</p>
        </div>
      )}
    </AccessibleExplanation>
  );
}
