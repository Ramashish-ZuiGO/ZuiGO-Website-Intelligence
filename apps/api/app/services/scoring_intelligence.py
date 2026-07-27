import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    AnalysisRun,
    CategoryScore,
    MetricContribution,
    ScoreExecution,
    ScoreExplanation,
    ScoreSnapshot,
)
from app.services import profiles_registry
from app.services.scoring_formula import CATEGORY_WEIGHTS, FORMULA_ID, FORMULA_VERSION, round_score

METRIC_REGISTRY_VERSION = "1.0.0"
PROFILE_FALLBACK_ID = "global_general"
CATEGORY_METRICS = {
    "performance": "performance_score",
    "accessibility": "accessibility_score",
    "best_practices": "best_practices_score",
    "seo": "seo_score",
    "technical_quality": "technical_quality_score",
}
CONFIDENCE_BANDS = ((90, "high"), (70, "medium"), (1, "low"))
FORMULA_LIMITATIONS = [
    "Unavailable categories are excluded and remaining weights are normalized.",
    "Lighthouse category values are laboratory evidence, not field measurements.",
    "Automated accessibility scores do not establish complete accessibility compliance.",
    "Bands describe approved internal profile thresholds, not competitors or rankings.",
]


class ScoringIntelligenceError(Exception):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message
        self.status_code = status_code


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def confidence_classification(score: int | None) -> str:
    if score is None:
        return "unavailable"
    for minimum, label in CONFIDENCE_BANDS:
        if score >= minimum:
            return label
    return "unavailable"


def _profile_thresholds(profile_id: str, metric_id: str) -> dict[str, Any]:
    profile = profiles_registry.get_profile(profile_id)
    rule = next(
        (
            item
            for item in (profile.threshold_rules if profile else [])
            if item.metric_id == metric_id
        ),
        None,
    )
    needs = (
        float(rule.needs_improvement_threshold)
        if rule and rule.needs_improvement_threshold is not None
        else 50.0
    )
    good = float(rule.good_threshold) if rule and rule.good_threshold is not None else 90.0
    return {
        "critical_below": needs / 2,
        "poor_below": needs,
        "needs_improvement_below": good,
        "good_below": (good + 100) / 2,
        "excellent_at_or_above": (good + 100) / 2,
        "derivation": "registered profile thresholds with transparent outer-band split",
    }


def score_band(value: int | None, profile_id: str, metric_id: str) -> tuple[str, dict[str, Any]]:
    thresholds = _profile_thresholds(profile_id, metric_id)
    if value is None:
        return "unavailable", thresholds
    if value < thresholds["critical_below"]:
        return "critical", thresholds
    if value < thresholds["poor_below"]:
        return "poor", thresholds
    if value < thresholds["needs_improvement_below"]:
        return "needs_improvement", thresholds
    if value < thresholds["good_below"]:
        return "good", thresholds
    return "excellent", thresholds


def _loaded_run(db: Session, run_id: uuid.UUID) -> AnalysisRun:
    run = db.scalar(
        select(AnalysisRun)
        .options(
            selectinload(AnalysisRun.website),
            selectinload(AnalysisRun.score),
            selectinload(AnalysisRun.result),
            selectinload(AnalysisRun.findings),
        )
        .where(AnalysisRun.id == run_id)
    )
    if run is None:
        raise ScoringIntelligenceError("ANALYSIS_RUN_NOT_FOUND", "Analysis run not found.", 404)
    if run.score is None:
        raise ScoringIntelligenceError(
            "SCORING_EVIDENCE_UNAVAILABLE",
            "The analysis run has no persisted score evidence.",
            409,
        )
    return run


def _category_values(run: AnalysisRun) -> dict[str, int | None]:
    assert run.score is not None
    return {
        "performance": run.score.performance_score,
        "accessibility": run.score.accessibility_score,
        "best_practices": run.score.best_practices_score,
        "seo": run.score.seo_score,
        "technical_quality": run.score.technical_quality_score,
    }


def calculate_score_execution(
    db: Session,
    run_id: uuid.UUID,
    *,
    idempotency_key: str,
) -> tuple[ScoreExecution, bool]:
    normalized_key = idempotency_key.strip()
    if not normalized_key:
        raise ScoringIntelligenceError(
            "INVALID_IDEMPOTENCY_KEY", "Idempotency key cannot be empty.", 422
        )
    run = _loaded_run(db, run_id)
    assert run.score is not None
    profile_id = run.profile_id or run.website.profile_id or PROFILE_FALLBACK_ID
    profile = profiles_registry.get_profile(profile_id) or profiles_registry.get_profile(
        PROFILE_FALLBACK_ID
    )
    assert profile is not None
    categories = _category_values(run)
    evidence_input = {
        "analysis_run_id": str(run.id),
        "analysis_score_id": str(run.score.id),
        "formula_version": run.score.formula_version,
        "profile_id": profile.profile_id,
        "profile_version": profile.version,
        "categories": categories,
        "deductions": run.score.deductions,
        "confidence_percent": run.score.confidence_percent,
    }
    input_fingerprint = fingerprint(evidence_input)
    existing = db.scalar(
        select(ScoreExecution).where(
            ScoreExecution.analysis_run_id == run.id,
            ScoreExecution.formula_id == FORMULA_ID,
            ScoreExecution.formula_version == FORMULA_VERSION,
            ScoreExecution.idempotency_key == normalized_key,
        )
    )
    if existing is not None:
        if existing.input_fingerprint != input_fingerprint:
            raise ScoringIntelligenceError(
                "SCORING_IDEMPOTENCY_CONFLICT",
                "The idempotency key is already associated with different scoring evidence.",
                409,
            )
        return existing, False

    available = [name for name, value in categories.items() if value is not None]
    unavailable = [CATEGORY_METRICS[name] for name, value in categories.items() if value is None]
    available_weight = sum(CATEGORY_WEIGHTS[name] for name in available)
    raw_total = (
        sum(int(categories[name]) * CATEGORY_WEIGHTS[name] for name in available) / available_weight
        if available_weight
        else None
    )
    overall = round_score(raw_total) if raw_total is not None else None
    coverage_numerator = len(available)
    coverage_denominator = len(CATEGORY_WEIGHTS)
    coverage = round(coverage_numerator / coverage_denominator * 100, 4)
    completed_at = datetime.now(UTC)
    execution = ScoreExecution(
        project_id=run.website.project_id,
        website_id=run.website_id,
        analysis_run_id=run.id,
        formula_id=FORMULA_ID,
        formula_version=FORMULA_VERSION,
        scoring_profile_id=profile.profile_id,
        scoring_profile_version=profile.version,
        metric_registry_version=METRIC_REGISTRY_VERSION,
        input_fingerprint=input_fingerprint,
        idempotency_key=normalized_key,
        status="completed" if overall is not None else "unavailable",
        overall_score=overall,
        confidence_percent=run.score.confidence_percent,
        confidence_classification=confidence_classification(run.score.confidence_percent),
        evidence_coverage_numerator=coverage_numerator,
        evidence_coverage_denominator=coverage_denominator,
        evidence_coverage_percentage=coverage,
        unavailable_metrics=unavailable,
        excluded_metrics=[
            {
                "metric_id": metric_id,
                "reason": "source evidence unavailable; excluded from normalized weights",
            }
            for metric_id in unavailable
        ],
        failure_details={},
        partial_completion_details=({"unavailable_metrics": unavailable} if unavailable else {}),
        completed_at=completed_at,
    )
    db.add(execution)
    db.flush()

    evidence_references = [
        {"evidence_type": "analysis_score", "evidence_id": str(run.score.id)},
        *(
            [{"evidence_type": "analysis_result", "evidence_id": str(run.result.id)}]
            if run.result
            else []
        ),
    ]
    category_rows: list[CategoryScore] = []
    contribution_rows: list[MetricContribution] = []
    for category_id, configured_weight in CATEGORY_WEIGHTS.items():
        value = categories[category_id]
        metric_id = CATEGORY_METRICS[category_id]
        normalized_weight = (
            configured_weight / available_weight if value is not None and available_weight else None
        )
        contribution = (
            value * normalized_weight if value is not None and normalized_weight else None
        )
        band, thresholds = score_band(value, profile.profile_id, metric_id)
        category_evidence = [
            *evidence_references,
            *(
                [
                    {
                        "evidence_type": "analysis_finding",
                        "evidence_id": str(item.id),
                    }
                    for item in run.findings
                    if category_id == "technical_quality"
                    and item.source.value in {"playwright", "http"}
                ]
            ),
        ]
        deductions = run.score.deductions if category_id == "technical_quality" else []
        category_row = CategoryScore(
            score_execution_id=execution.id,
            category_id=category_id,
            raw_score=value,
            final_score=value,
            configured_weight=configured_weight / 100,
            normalized_weight=normalized_weight,
            contribution=contribution,
            band=band,
            included=value is not None,
            exclusion_reason=(None if value is not None else "Source evidence unavailable."),
            thresholds=thresholds,
            deductions=deductions,
            adjustments=[],
            evidence_references=category_evidence,
        )
        db.add(category_row)
        db.flush()
        category_rows.append(category_row)
        contribution_rows.append(
            MetricContribution(
                score_execution_id=execution.id,
                category_score_id=category_row.id,
                metric_id=metric_id,
                raw_value={"value": value, "unit": "score"},
                normalized_value=value,
                configured_weight=configured_weight / 100,
                normalized_weight=normalized_weight,
                contribution=contribution,
                inclusion_status="included" if value is not None else "excluded",
                exclusion_reason=category_row.exclusion_reason,
                threshold_decision={"band": band, **thresholds},
                deduction_or_adjustment={"deductions": deductions, "adjustments": []},
                evidence_references=category_evidence,
            )
        )
    db.add_all(contribution_rows)
    snapshot = ScoreSnapshot(
        score_execution_id=execution.id,
        overall_score=overall,
        category_scores=categories,
        confidence_percent=run.score.confidence_percent,
        evidence_coverage_percentage=coverage,
        unavailable_metrics=unavailable,
        excluded_metrics=execution.excluded_metrics,
        evidence_references=evidence_references,
        calculation_details={
            "configured_weights": CATEGORY_WEIGHTS,
            "available_weight_total": available_weight,
            "raw_weighted_total": raw_total,
            "rounding": "round-half-up to nearest integer",
            "normalization": {
                name: CATEGORY_WEIGHTS[name] / available_weight for name in available
            },
        },
    )
    explanation = ScoreExplanation(
        score_execution_id=execution.id,
        formula_summary=(
            "Overall Score Formula v1.0.0: weighted category mean with unavailable "
            "weights normalized, then round-half-up."
        ),
        profile_summary=(
            f"{profile.name} v{profile.version}; profile thresholds interpret scores "
            "but do not alter formula mathematics."
        ),
        normalization_decisions=[
            {
                "metric_id": CATEGORY_METRICS[name],
                "configured_weight": CATEGORY_WEIGHTS[name] / 100,
                "normalized_weight": CATEGORY_WEIGHTS[name] / available_weight,
            }
            for name in available
        ],
        caps_floors_deductions=[
            {"technical_quality_floor": 0, "technical_quality_cap": 100},
            *run.score.deductions,
        ],
        limitations=FORMULA_LIMITATIONS,
        reproducibility_payload=evidence_input,
    )
    db.add_all([snapshot, explanation])
    db.commit()
    return load_score_execution(db, execution.execution_id), True


def load_score_execution(db: Session, execution_id: uuid.UUID) -> ScoreExecution:
    execution = db.scalar(
        select(ScoreExecution)
        .options(
            selectinload(ScoreExecution.snapshot),
            selectinload(ScoreExecution.categories),
            selectinload(ScoreExecution.contributions),
            selectinload(ScoreExecution.explanation),
        )
        .where(ScoreExecution.execution_id == execution_id)
    )
    if execution is None:
        raise ScoringIntelligenceError(
            "SCORE_EXECUTION_NOT_FOUND", "Score execution not found.", 404
        )
    return execution


def score_trend(db: Session, execution: ScoreExecution) -> dict[str, Any]:
    previous = db.scalar(
        select(ScoreExecution)
        .options(selectinload(ScoreExecution.categories))
        .where(
            ScoreExecution.website_id == execution.website_id,
            ScoreExecution.id != execution.id,
            ScoreExecution.created_at <= execution.created_at,
            ScoreExecution.status.in_(("completed", "partial")),
        )
        .order_by(ScoreExecution.created_at.desc(), ScoreExecution.id.desc())
    )
    if previous is None:
        return {"state": "unavailable", "reason": "No previous scoring execution."}
    compatible = (
        previous.formula_id == execution.formula_id
        and previous.formula_version == execution.formula_version
        and previous.scoring_profile_id == execution.scoring_profile_id
        and previous.scoring_profile_version == execution.scoring_profile_version
    )
    if not compatible:
        return {
            "state": "incompatible",
            "reason": "Formula or profile version differs.",
            "previous_execution_id": str(previous.execution_id),
        }
    if previous.overall_score is None or execution.overall_score is None:
        state = "unavailable"
        delta = None
    else:
        delta = execution.overall_score - previous.overall_score
        state = "improved" if delta > 0 else "declined" if delta < 0 else "unchanged"
    previous_categories = {item.category_id: item.final_score for item in previous.categories}
    category_deltas = {
        item.category_id: (
            item.final_score - previous_categories[item.category_id]
            if item.final_score is not None
            and previous_categories.get(item.category_id) is not None
            else None
        )
        for item in execution.categories
    }
    coverage_delta = (
        execution.evidence_coverage_percentage - previous.evidence_coverage_percentage
        if execution.evidence_coverage_percentage is not None
        and previous.evidence_coverage_percentage is not None
        else None
    )
    return {
        "state": state,
        "score_delta": delta,
        "category_deltas": category_deltas,
        "evidence_coverage_delta": coverage_delta,
        "previous_execution_id": str(previous.execution_id),
        "compatible": True,
    }
