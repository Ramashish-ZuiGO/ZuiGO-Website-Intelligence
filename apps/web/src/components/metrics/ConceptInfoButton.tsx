"use client";

import { AccessibleExplanation } from "./AccessibleExplanation";
import { getSafeConceptExplanation } from "./explanations";

interface ConceptInfoButtonProps {
  conceptId: string;
  title: string;
  className?: string;
}

export function ConceptInfoButton({
  conceptId,
  title,
  className = "",
}: ConceptInfoButtonProps) {
  const content = getSafeConceptExplanation(conceptId, title);
  if (!content) return null;
  return (
    <AccessibleExplanation
      className={className}
      content={content}
      shortTooltip={content.shortTooltip}
      title={title}
    />
  );
}
