import json

from worker_app.ai.prompt_builder import build_prompt
from worker_app.ai.service import generate_interpretation
from worker_app.config import WorkerSettings


def verified_data() -> dict[str, object]:
    return {
        "website": {
            "name": "Example",
            "requested_url": "https://example.com/",
            "final_url": "https://example.com/",
            "analysis_date": "2026-07-18T00:00:00Z",
        },
        "scores": {
            "overall_score": 88,
            "performance_score": 90,
            "confidence_percent": 100,
            "formula_version": "1.0.0",
        },
        "deductions": [],
        "lighthouse_metrics": {"largest_contentful_paint_ms": 1200.0},
        "playwright_measurements": {"http_status_code": 200, "h1_count": 0},
        "findings": [
            {
                "finding_code": "MISSING_H1",
                "title": "Missing H1",
                "description": "The homepage has no H1 heading.",
                "severity": "medium",
                "source": "playwright",
                "evidence": {"h1_count": 0},
                "confidence_percent": 100,
            }
        ],
    }


def settings() -> WorkerSettings:
    return WorkerSettings(
        redis_url="redis://localhost:6379/0",
        postgres_password="test-password",
        ai_provider="disabled",
    )


class StaticProvider:
    name = "test-provider"
    model = "test-model"

    def __init__(self, output: str) -> None:
        self.output = output

    def generate(self, prompt: str) -> str:
        del prompt
        return self.output


def valid_output(code: str = "MISSING_H1") -> str:
    return json.dumps(
        {
            "executive_summary": "Verified summary.",
            "overall_assessment": "Verified assessment.",
            "strengths": [],
            "weaknesses": [{"text": "Missing heading.", "related_finding_codes": [code]}],
            "priority_recommendations": [
                {
                    "recommendation_id": "REC-1",
                    "title": "Add an H1",
                    "explanation": "Address the verified finding.",
                    "related_finding_codes": [code],
                    "priority": "medium",
                    "business_impact": "Improves page structure.",
                    "recommended_fix": "Add one descriptive H1.",
                    "estimated_effort": "Small",
                    "responsible_role": "Frontend developer",
                    "expected_improvement": "Resolves the finding.",
                    "confidence_percent": 100,
                }
            ],
            "action_plan": [{"timeframe": "short_term", "recommendation_ids": ["REC-1"]}],
            "limitations": ["Homepage evidence only."],
        }
    )


def test_prompt_contains_only_normalized_evidence_and_codes() -> None:
    prompt = build_prompt(verified_data())

    assert "MISSING_H1" in prompt
    assert "largest_contentful_paint_ms" in prompt
    assert "test-password" not in prompt
    assert "celery" not in prompt.lower()
    assert "raw exception" not in prompt.lower()


def test_valid_structured_output_uses_ai_mode() -> None:
    result = generate_interpretation(verified_data(), settings(), StaticProvider(valid_output()))

    assert result["generation_mode"] == "ai"
    assert result["provider"] == "test-provider"
    assert result["priority_recommendations"][0]["related_finding_codes"] == ["MISSING_H1"]


def test_unknown_code_and_invalid_output_trigger_grounded_fallback() -> None:
    unknown = generate_interpretation(
        verified_data(), settings(), StaticProvider(valid_output("INVENTED_FINDING"))
    )
    invalid = generate_interpretation(verified_data(), settings(), StaticProvider("not-json"))

    assert unknown["generation_mode"] == "deterministic_fallback"
    assert unknown["fallback_reason"] == "invalid_provider_output"
    assert invalid["generation_mode"] == "deterministic_fallback"
    assert all(
        recommendation["related_finding_codes"] == ["MISSING_H1"]
        for recommendation in invalid["priority_recommendations"]
    )


def test_timeout_and_disabled_provider_trigger_fallback() -> None:
    class TimeoutProvider:
        name = "timeout"
        model = "timeout"

        def generate(self, prompt: str) -> str:
            del prompt
            raise TimeoutError

    timed_out = generate_interpretation(verified_data(), settings(), TimeoutProvider())
    disabled = generate_interpretation(verified_data(), settings())

    assert timed_out["fallback_reason"] == "provider_unavailable"
    assert disabled["generation_mode"] == "deterministic_fallback"
    assert disabled["provider"] == "disabled"
