import json
from typing import Any

from pydantic import ValidationError

from worker_app.ai.base import AIProvider, ProviderUnavailableError
from worker_app.ai.prompt_builder import PROMPT_VERSION, build_prompt
from worker_app.ai.provider_factory import create_provider
from worker_app.ai.schemas import (
    INSUFFICIENT_EVIDENCE,
    ActionPlanItem,
    GroundedObservation,
    InterpretationContent,
    Recommendation,
    validate_grounding,
)
from worker_app.config import WorkerSettings


def _deterministic_recommendation(finding: dict[str, Any]) -> tuple[str, str]:
    code = finding["finding_code"]
    evidence = finding.get("evidence", {})
    if code == "HIGH_LCP":
        value = evidence.get("value")
        threshold = evidence.get("threshold")
        element = evidence.get("lcp_element")
        element_label = (
            element.get("nodeLabel") or element.get("selector") or element.get("snippet")
            if isinstance(element, dict)
            else None
        )
        blockers = evidence.get("render_blocking_resources") or []
        explanation = (
            f"Largest Contentful Paint measured {value} ms against the {threshold} ms "
            f"needs-improvement threshold."
        )
        if element_label:
            explanation += f" Lighthouse identified the bounded LCP element as {element_label}."
        fix = "Prioritize delivery and rendering of the identified LCP element" + (
            " and review the recorded render-blocking resources." if blockers else "."
        )
        return explanation, fix
    if code == "HIGH_TOTAL_BLOCKING_TIME":
        value = evidence.get("value")
        threshold = evidence.get("threshold")
        scripts = evidence.get("script_execution") or []
        tasks = evidence.get("long_tasks") or evidence.get("main_thread_work") or []
        explanation = (
            f"Total Blocking Time measured {value} ms against the {threshold} ms "
            "needs-improvement threshold."
        )
        if scripts or tasks:
            explanation += " Lighthouse supplied bounded script or main-thread task evidence."
        fix = "Reduce the recorded long tasks" + (
            " and defer, split, or shorten only the scripts identified in the evidence."
            if scripts
            else " by splitting synchronous work where the recorded task groups support it."
        )
        return explanation, fix
    if code == "CSS_MIME_TYPE_FAILURE":
        requests = evidence.get("requests") or []
        resource = requests[0].get("url") if requests else "the affected stylesheet"
        return (
            f"Chromium rejected the first-party stylesheet {resource} because console evidence "
            "reported an invalid MIME type.",
            "Configure the affected CSS response to return a valid text/css Content-Type and "
            "verify that redirects or error pages are not being served at that URL.",
        )
    return (
        finding["description"],
        "Review the recorded evidence and implement the correction indicated by the "
        "verified finding.",
    )


def deterministic_fallback(data: dict[str, Any]) -> InterpretationContent:
    findings = data["findings"]
    scores = data["scores"]
    strengths = [
        GroundedObservation(
            text=f"The verified {name.replace('_', ' ')} score is {score} out of 100.",
            related_finding_codes=[],
        )
        for name, score in scores.items()
        if name.endswith("_score") and isinstance(score, int) and score >= 90
    ]
    weaknesses = [
        GroundedObservation(
            text=f"{finding['title']}: {finding['description']}",
            related_finding_codes=[finding["finding_code"]],
        )
        for finding in findings
    ]
    recommendations: list[Recommendation] = []
    for index, finding in enumerate(findings, start=1):
        severity = finding["severity"]
        priority = severity if severity in {"critical", "high", "medium", "low"} else "low"
        explanation, recommended_fix = _deterministic_recommendation(finding)
        recommendations.append(
            Recommendation(
                recommendation_id=f"REC-{index:03d}",
                title=f"Address {finding['title']}",
                explanation=explanation,
                related_finding_codes=[finding["finding_code"]],
                priority=priority,
                business_impact=(
                    "Resolving this verified issue can reduce the user or search impact "
                    "identified by the deterministic audit."
                ),
                recommended_fix=recommended_fix,
                estimated_effort="Requires engineering review",
                responsible_role="Web development team",
                expected_improvement="Removes or mitigates the referenced verified finding.",
                confidence_percent=finding["confidence_percent"],
            )
        )
    plans = [
        ActionPlanItem(
            timeframe=(
                "immediate"
                if item.priority in {"critical", "high"}
                else "short_term"
                if item.priority == "medium"
                else "medium_term"
            ),
            recommendation_ids=[item.recommendation_id],
        )
        for item in recommendations
    ]
    overall = scores.get("overall_score")
    summary = (
        f"The verified homepage analysis produced an overall score of {overall} out of 100 "
        f"with {len(findings)} deterministic finding(s)."
        if overall is not None
        else f"The verified homepage analysis produced {len(findings)} deterministic finding(s)."
    )
    limitations = [
        "This interpretation uses only the persisted single-homepage audit evidence.",
        "No legal, certification, or unverified vulnerability conclusions are included.",
    ]
    if not findings:
        limitations.append(INSUFFICIENT_EVIDENCE)
    return InterpretationContent(
        executive_summary=summary,
        overall_assessment=(
            "Prioritize the verified findings below while preserving areas with strong "
            "measured category scores."
            if findings
            else INSUFFICIENT_EVIDENCE
        ),
        strengths=strengths,
        weaknesses=weaknesses,
        priority_recommendations=recommendations,
        action_plan=plans,
        limitations=limitations,
    )


def generate_interpretation(
    normalized_data: dict[str, Any],
    settings: WorkerSettings,
    provider: AIProvider | None = None,
) -> dict[str, Any]:
    finding_codes = {item["finding_code"] for item in normalized_data["findings"]}
    for diagnostic in normalized_data.get("diagnostics", {}).values():
        finding_codes.update(
            item["code"]
            for item in diagnostic.get("evidence", [])
            if isinstance(item, dict) and isinstance(item.get("code"), str)
        )
        score = diagnostic.get("score")
        if isinstance(score, dict):
            finding_codes.update(
                item["code"]
                for item in score.get("deductions", [])
                if isinstance(item, dict) and isinstance(item.get("code"), str)
            )
    prompt = build_prompt(normalized_data)
    try:
        selected_provider = provider or create_provider(settings)
        raw_output = selected_provider.generate(prompt)
        content = InterpretationContent.model_validate(json.loads(raw_output))
        validate_grounding(content, finding_codes)
        mode = "ai"
        provider_name = selected_provider.name
        model = selected_provider.model
        fallback_reason = None
    except (
        ProviderUnavailableError,
        TimeoutError,
        OSError,
        json.JSONDecodeError,
        ValidationError,
        ValueError,
    ) as exception:
        content = deterministic_fallback(normalized_data)
        validate_grounding(content, finding_codes)
        mode = "deterministic_fallback"
        provider_name = settings.ai_provider.value
        model = settings.ai_model
        fallback_reason = (
            "provider_unavailable"
            if isinstance(exception, (ProviderUnavailableError, TimeoutError, OSError))
            else "invalid_provider_output"
        )
    return {
        "generation_mode": mode,
        "provider": provider_name,
        "model": model,
        "prompt_version": PROMPT_VERSION,
        **content.model_dump(mode="json"),
        "fallback_reason": fallback_reason,
    }
