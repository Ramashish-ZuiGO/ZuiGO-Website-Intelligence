import pytest
from app.schemas.metadata import MetricCategoryEnum, MetricDefinition, MetricValueTypeEnum
from app.services import metrics_registry


def test_registry_contains_unique_ids():
    metrics = metrics_registry.get_all_metrics()
    metric_ids = [m.metric_id for m in metrics]
    assert len(metric_ids) == len(set(metric_ids)), "Duplicate metric IDs found in registry"


def test_registry_has_required_fields():
    metrics = metrics_registry.get_all_metrics()
    for metric in metrics:
        assert metric.metric_id, "Metric ID is required"
        assert metric.label, f"Label is required for {metric.metric_id}"
        assert metric.category, f"Category is required for {metric.metric_id}"
        assert metric.description, f"Description is required for {metric.metric_id}"
        assert metric.explanation, f"Explanation is required for {metric.metric_id}"
        assert metric.value_type, f"Value type is required for {metric.metric_id}"
        assert metric.evidence_source, f"Evidence source is required for {metric.metric_id}"
        assert metric.calculation_summary, f"Calculation summary is required for {metric.metric_id}"
        assert metric.interpretation_guidance, (
            f"Interpretation guidance is required for {metric.metric_id}"
        )
        assert metric.known_limitations, f"Known limitations is required for {metric.metric_id}"
        assert metric.confidence_applicability, (
            f"Confidence applicability is required for {metric.metric_id}"
        )


def test_registry_stable_ordering():
    metrics = metrics_registry.get_all_metrics()
    metric_ids = [m.metric_id for m in metrics]
    assert metric_ids == sorted(metric_ids), (
        "Metrics should be returned in deterministic sorted order"
    )


def test_registry_category_filter():
    metrics = metrics_registry.get_all_metrics(category=MetricCategoryEnum.CATEGORY_SCORE)
    assert len(metrics) > 0
    for metric in metrics:
        assert metric.category == MetricCategoryEnum.CATEGORY_SCORE


def test_registry_value_type_filter():
    metrics = metrics_registry.get_all_metrics(value_type=MetricValueTypeEnum.PERCENTAGE)
    assert len(metrics) > 0
    for metric in metrics:
        assert metric.value_type == MetricValueTypeEnum.PERCENTAGE


def test_registry_get_metric():
    metric = metrics_registry.get_metric("overall_score")
    assert metric is not None
    assert metric.metric_id == "overall_score"

    unknown = metrics_registry.get_metric("does_not_exist_metric_123")
    assert unknown is None


def test_duplicate_registration_raises():
    dummy_metric = MetricDefinition(
        metric_id="overall_score",  # Already exists
        label="Test",
        category=MetricCategoryEnum.OTHER,
        description="Test",
        explanation="Test",
        value_type=MetricValueTypeEnum.SCORE,
        evidence_source="Test",
        calculation_summary="Test",
        interpretation_guidance="Test",
        known_limitations="Test",
        confidence_applicability="Test",
    )
    with pytest.raises(ValueError):
        metrics_registry.register_metric(dummy_metric)


def test_value_type_validation_for_all_types():
    for val_type in MetricValueTypeEnum:
        dummy = MetricDefinition(
            metric_id=f"test_{val_type.value}",
            label="Test",
            category=MetricCategoryEnum.OTHER,
            description="Test",
            explanation="Test",
            value_type=val_type,
            evidence_source="Test",
            calculation_summary="Test",
            interpretation_guidance="Test",
            known_limitations="Test",
            confidence_applicability="Test",
        )
        assert dummy.value_type == val_type
