import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.analysis_run import AnalysisRun
from app.models.website import Website
from app.schemas.profile import MetricInterpretation
from app.services import interpretation_service, profiles_registry

router = APIRouter(prefix="/websites", tags=["websites"])
DatabaseSession = Annotated[Session, Depends(get_db)]


def get_website_or_raise(db: Session, website_id: uuid.UUID) -> Website:
    website = db.scalar(select(Website).where(Website.id == website_id))
    if not website:
        raise HTTPException(status_code=404, detail="Website not found")
    return website


@router.get("/{website_id}/profile")
def get_website_profile(website_id: uuid.UUID, db: DatabaseSession) -> dict:
    website = get_website_or_raise(db, website_id)
    profile = profiles_registry.get_profile(website.profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found in registry")
    return profile.model_dump()


@router.put("/{website_id}/profile", status_code=status.HTTP_200_OK)
def update_website_profile(website_id: uuid.UUID, profile_id: str, db: DatabaseSession) -> dict:
    website = get_website_or_raise(db, website_id)
    profile = profiles_registry.get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=400, detail="Invalid profile ID")

    website.profile_id = profile_id
    db.commit()
    return {"status": "success", "profile_id": profile_id}


@router.get("/{website_id}/metric-interpretations", response_model=list[MetricInterpretation])
def get_website_metric_interpretations(
    website_id: uuid.UUID, db: DatabaseSession
) -> list[MetricInterpretation]:
    website = get_website_or_raise(db, website_id)

    # Find latest completed run
    run = db.scalar(
        select(AnalysisRun)
        .where(AnalysisRun.website_id == website.id)
        .where(AnalysisRun.status == "completed")
        .order_by(AnalysisRun.created_at.desc())
        .limit(1)
    )

    if not run:
        return []

    profile_id = run.profile_id or "global_general"
    profile = profiles_registry.get_profile(profile_id)
    if not profile:
        profile = profiles_registry.get_profile("global_general")

    interpretations = []
    # To evaluate metrics, we'd pull from run.score, run.lighthouse_metrics, etc.
    # Since we need a generic evaluation, let's extract available scores
    metrics_to_eval = {}
    if run.score:
        metrics_to_eval["overall_score"] = run.score.overall_score
        metrics_to_eval["performance_score"] = run.score.performance_score
        metrics_to_eval["accessibility_score"] = run.score.accessibility_score
        metrics_to_eval["seo_score"] = run.score.seo_score
        metrics_to_eval["best_practices_score"] = run.score.best_practices_score
        metrics_to_eval["technical_quality_score"] = run.score.technical_quality_score

    # For CWV, they are part of result JSON but since we don't have the result model
    # loaded fully here, we can fetch them if needed. Actually AnalysisResult model
    # exists! Let's load it.

    from app.models.analysis_result import AnalysisResult

    result = db.scalar(select(AnalysisResult).where(AnalysisResult.analysis_run_id == run.id))
    if result:
        # result.result_data contains lighthouse_metrics
        lh_metrics = result.result_data.get("lighthouse_metrics", {})
        for k, v in lh_metrics.items():
            # lighthouse metrics have specific keys. E.g. "largest_contentful_paint_ms"
            # let's map them to our registry keys
            key_map = {
                "largest_contentful_paint_ms": "lighthouse_lcp",
                "interaction_to_next_paint_ms": "lighthouse_inp",
                "cumulative_layout_shift": "lighthouse_cls",
                "first_contentful_paint_ms": "lighthouse_fcp",
                "total_blocking_time_ms": "lighthouse_tbt",
                "speed_index_ms": "lighthouse_speed_index",
            }
            if k in key_map:
                metrics_to_eval[key_map[k]] = v

    for m_id, m_val in metrics_to_eval.items():
        interpretations.append(interpretation_service.evaluate_metric(m_id, m_val, profile))

    return interpretations
