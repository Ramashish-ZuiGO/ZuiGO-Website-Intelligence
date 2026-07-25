import React from "react";

interface ConfidenceBadgeProps {
  confidence: string | null;
  className?: string;
}

export function ConfidenceBadge({ confidence, className = "" }: ConfidenceBadgeProps) {
  if (!confidence || confidence.toLowerCase() === "unavailable") {
    return <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-800 ${className}`}>Unavailable</span>;
  }

  const normalized = confidence.toLowerCase();

  if (normalized === "high") {
    return <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-green-100 text-green-800 ${className}`}>High</span>;
  }

  if (normalized === "medium") {
    return <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-yellow-100 text-yellow-800 ${className}`}>Medium</span>;
  }

  if (normalized === "low") {
    return <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-red-100 text-red-800 ${className}`}>Low</span>;
  }

  return <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-800 ${className}`}>{confidence}</span>;
}
