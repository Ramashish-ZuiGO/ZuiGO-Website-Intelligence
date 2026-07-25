from fastapi import APIRouter, HTTPException, Query

from app.schemas.metadata import MetricCategoryEnum, MetricDefinition, MetricValueTypeEnum
from app.services import metrics_registry

router = APIRouter(prefix="/metadata", tags=["Metadata"])


@router.get(
    "/metrics",
    response_model=list[MetricDefinition],
    summary="List all metric definitions",
    description=(
        "Returns a list of all supported metric definitions. "
        "Can be filtered by category or value type."
    ),
)
def get_metrics(
    category: MetricCategoryEnum | None = Query(None, description="Filter by category"),  # noqa: B008
    value_type: MetricValueTypeEnum | None = Query(None, description="Filter by value type"),  # noqa: B008
) -> list[MetricDefinition]:
    return metrics_registry.get_all_metrics(category=category, value_type=value_type)


@router.get(
    "/metrics/{metric_id}",
    response_model=MetricDefinition,
    summary="Get metric definition by ID",
    description="Returns the detailed definition for a specific metric ID.",
)
def get_metric(metric_id: str) -> MetricDefinition:
    metric = metrics_registry.get_metric(metric_id)
    if not metric:
        raise HTTPException(status_code=404, detail="Metric not found")
    return metric
