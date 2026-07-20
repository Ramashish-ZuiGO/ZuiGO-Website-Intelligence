import json
from typing import Any

PROMPT_VERSION = "1.0.0"


def build_prompt(normalized_data: dict[str, Any]) -> str:
    evidence = json.dumps(normalized_data, ensure_ascii=True, sort_keys=True)
    return f"""You are generating an evidence-grounded website interpretation.
Prompt version: {PROMPT_VERSION}

Safety requirements:
- Use only the normalized verified evidence supplied below.
- Do not create or infer technical findings.
- Do not change finding severity or stored scores.
- Every recommendation must cite one or more supplied finding codes.
- Do not claim legal, certification, or vulnerability status unless explicitly present.
- If evidence is insufficient, use the required safe insufficient-evidence statement.
- Return only one JSON object matching the required schema. Do not use markdown.

Required JSON keys:
executive_summary, overall_assessment, strengths, weaknesses,
priority_recommendations, action_plan, limitations.
Strengths and weaknesses contain text and related_finding_codes.
Recommendations contain recommendation_id, title, explanation,
related_finding_codes, priority (critical/high/medium/low), business_impact,
recommended_fix, estimated_effort, responsible_role, expected_improvement,
and confidence_percent (0-100).
Action-plan entries contain timeframe (immediate/short_term/medium_term) and
recommendation_ids.

NORMALIZED VERIFIED EVIDENCE:
{evidence}
"""
