from app.schemas.profile import (
    ComparisonDirectionEnum,
    MetricInterpretation,
    ProfileDefinition,
    RatingEnum,
)


def evaluate_metric(
    metric_id: str, raw_value: float | str | None, profile: ProfileDefinition
) -> MetricInterpretation:
    # Find the threshold rule
    rule = next((r for r in profile.threshold_rules if r.metric_id == metric_id), None)

    if not rule:
        return MetricInterpretation(
            metric_id=metric_id,
            raw_value=raw_value,
            unit=None,
            rating=RatingEnum.NOT_APPLICABLE,
            selected_profile_id=profile.profile_id,
            selected_profile_version=profile.version,
            thresholds_used={},
            evidence_type=None,
            source_reference=None,
            explanation="Metric not supported in this profile.",
            limitations=[],
        )

    if raw_value is None or str(raw_value).strip() == "":
        return MetricInterpretation(
            metric_id=metric_id,
            raw_value=raw_value,
            unit=rule.unit,
            rating=RatingEnum.UNAVAILABLE,
            selected_profile_id=profile.profile_id,
            selected_profile_version=profile.version,
            thresholds_used={},
            evidence_type=rule.evidence_type,
            source_reference=rule.source_reference,
            explanation="Data unavailable.",
            limitations=rule.limitations,
        )

    rating = RatingEnum.UNAVAILABLE
    try:
        val = float(raw_value)
        if (
            rule.good_threshold is None
            and rule.needs_improvement_threshold is None
            and rule.poor_threshold is None
        ):
            rating = RatingEnum.NOT_APPLICABLE
        elif rule.comparison_direction == ComparisonDirectionEnum.HIGHER_IS_BETTER:
            if rule.good_threshold is not None and val >= rule.good_threshold:
                rating = RatingEnum.GOOD
            elif (
                rule.needs_improvement_threshold is not None
                and val >= rule.needs_improvement_threshold
            ):
                rating = RatingEnum.NEEDS_IMPROVEMENT
            else:
                rating = RatingEnum.POOR
        else:
            if rule.good_threshold is not None and val <= rule.good_threshold:
                rating = RatingEnum.GOOD
            elif (
                rule.needs_improvement_threshold is not None
                and val <= rule.needs_improvement_threshold
            ):
                rating = RatingEnum.NEEDS_IMPROVEMENT
            else:
                rating = RatingEnum.POOR
    except ValueError:
        # Cannot evaluate non-numeric
        rating = RatingEnum.UNAVAILABLE

    return MetricInterpretation(
        metric_id=metric_id,
        raw_value=raw_value,
        unit=rule.unit,
        rating=rating,
        selected_profile_id=profile.profile_id,
        selected_profile_version=profile.version,
        thresholds_used={
            "good": rule.good_threshold,
            "needs_improvement": rule.needs_improvement_threshold,
            "poor": rule.poor_threshold,
        },
        evidence_type=rule.evidence_type,
        source_reference=rule.source_reference,
        explanation=rule.interpretation_text,
        limitations=rule.limitations,
    )
