import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.analysis_run import AnalysisRun
from app.models.performance import PerformanceSnapshot
from app.models.website import Website
from app.services.crux_provider import get_crux_provider


def collect_performance_evidence(
    db: Session, execution_id: uuid.UUID, website: Website, analysis_run: AnalysisRun | None = None
) -> dict:
    """Collect performance evidence from CrUX and persist snapshots."""
    crux = get_crux_provider()

    # Try URL first
    url = website.url
    form_factors = ["PHONE", "DESKTOP"]
    snapshots_created = 0
    errors = []

    for ff in form_factors:
        result = _fetch_and_store_crux(
            db, crux, execution_id, website, url, "url", ff, analysis_run
        )
        if result["status"] == "success":
            snapshots_created += result["count"]
        elif result["status"] == "no_record":
            # Fallback to origin
            origin = _get_origin(url)
            if origin != url:
                fallback_result = _fetch_and_store_crux(
                    db, crux, execution_id, website, origin, "origin", ff, analysis_run
                )
                if fallback_result["status"] == "success":
                    snapshots_created += fallback_result["count"]
                elif fallback_result["status"] == "error":
                    errors.append(fallback_result["reason"])
        elif result["status"] == "error":
            errors.append(result["reason"])

    # Here we would also integrate Lighthouse metrics if we had them available in this context,
    # or the caller (e.g. celery worker) passes them in.

    return {
        "status": "partial"
        if errors and snapshots_created > 0
        else "success"
        if snapshots_created > 0
        else "failed",
        "snapshots_created": snapshots_created,
        "errors": errors,
    }


def _get_origin(url: str) -> str:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _fetch_and_store_crux(
    db: Session,
    crux,
    execution_id: uuid.UUID,
    website: Website,
    url_or_origin: str,
    scope: str,
    form_factor: str,
    analysis_run: AnalysisRun | None = None,
) -> dict:
    import asyncio

    # In a real sync context, we'd use a synchronous client or run in event loop.
    # We will assume this is run from an async worker, or we run it synchronously here.
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    if scope == "url":
        result = loop.run_until_complete(
            crux.fetch_record(url=url_or_origin, form_factor=form_factor)
        )
    else:
        result = loop.run_until_complete(
            crux.fetch_record(origin=url_or_origin, form_factor=form_factor)
        )

    if result["status"] != "success":
        return result

    record = result["data"].get("record", {})
    metrics = record.get("metrics", {})
    collection_period = record.get("collectionPeriod", {})

    # map crux metrics to our metric registry IDs
    crux_mapping = {
        "largest_contentful_paint": "field_lcp",
        "interaction_to_next_paint": "field_inp",
        "cumulative_layout_shift": "field_cls",
        "first_contentful_paint": "field_fcp",
    }

    count = 0
    now = datetime.now(UTC)
    for crux_key, our_id in crux_mapping.items():
        if crux_key in metrics:
            metric_data = metrics[crux_key]
            p75 = metric_data.get("percentiles", {}).get("p75")
            histogram = metric_data.get("histogram")

            # Check if exists
            existing = db.scalar(
                select(PerformanceSnapshot)
                .where(PerformanceSnapshot.execution_id == execution_id)
                .where(PerformanceSnapshot.website_id == website.id)
                .where(PerformanceSnapshot.url_or_origin == url_or_origin)
                .where(PerformanceSnapshot.evidence_type == "field")
                .where(PerformanceSnapshot.metric_id == our_id)
                .where(PerformanceSnapshot.form_factor == form_factor.lower())
            )

            if not existing:
                snap = PerformanceSnapshot(
                    execution_id=execution_id,
                    website_id=website.id,
                    analysis_run_id=analysis_run.id if analysis_run else None,
                    url_or_origin=url_or_origin,
                    evidence_source="crux",
                    evidence_type="field",
                    scope=scope,
                    form_factor=form_factor.lower(),
                    metric_id=our_id,
                    raw_value=float(p75) if p75 is not None else None,
                    percentile=75.0,
                    histogram_bins=histogram,
                    availability_status="available",
                    created_at=now,
                )

                # Assign collection period if available
                if "firstDate" in collection_period and "lastDate" in collection_period:
                    try:
                        fd = collection_period["firstDate"]
                        ld = collection_period["lastDate"]
                        snap.collection_period_start = datetime(
                            fd["year"], fd["month"], fd["day"], tzinfo=UTC
                        )
                        snap.collection_period_end = datetime(
                            ld["year"], ld["month"], ld["day"], tzinfo=UTC
                        )
                    except (KeyError, ValueError):
                        pass

                db.add(snap)
                count += 1

    if count > 0:
        db.commit()

    return {"status": "success", "count": count}


def collect_lighthouse_evidence(
    db: Session,
    execution_id: uuid.UUID,
    website_id: uuid.UUID,
    url: str,
    metrics: dict,
    analysis_run_id: uuid.UUID | None = None,
) -> None:
    now = datetime.now(UTC)

    mapping = {
        "first_contentful_paint_ms": "lab_fcp",
        "largest_contentful_paint_ms": "lab_lcp",
        "cumulative_layout_shift": "lab_cls",
        "total_blocking_time_ms": "lab_tbt",
        "speed_index_ms": "lab_speed_index",
    }

    context = metrics.get("lighthouse_context", {})
    form_factor = (context.get("form_factor") or "desktop").lower()

    for key, metric_id in mapping.items():
        val = metrics.get(key)
        if val is not None:
            snap = PerformanceSnapshot(
                execution_id=execution_id,
                website_id=website_id,
                analysis_run_id=analysis_run_id,
                url_or_origin=url,
                evidence_source="lighthouse",
                evidence_type="lab",
                scope="url",
                form_factor=form_factor,
                metric_id=metric_id,
                raw_value=float(val),
                availability_status="available",
                created_at=now,
                provider="lighthouse",
                provider_metadata={"lighthouse_version": metrics.get("lighthouse_version")},
            )
            db.add(snap)
    db.commit()


def collect_browser_timing_evidence(
    db: Session,
    execution_id: uuid.UUID,
    website_id: uuid.UUID,
    url: str,
    timing_data: dict,
    analysis_run_id: uuid.UUID | None = None,
) -> None:
    now = datetime.now(UTC)

    for metric_id, val in timing_data.items():
        if val is not None and isinstance(val, (int, float)):
            snap = PerformanceSnapshot(
                execution_id=execution_id,
                website_id=website_id,
                analysis_run_id=analysis_run_id,
                url_or_origin=url,
                evidence_source="browser_timing",
                evidence_type="diagnostic",
                scope="url",
                form_factor="desktop",  # Default playwright
                metric_id=metric_id,
                raw_value=float(val),
                availability_status="available",
                created_at=now,
                provider="playwright",
            )
            db.add(snap)
    db.commit()


def compare_performance(db: Session, website_id: uuid.UUID) -> dict:
    """
    Compare the latest field and lab performance evidence for a website to
    detect discrepancies.
    """
    # Fetch all latest snapshots for this website
    snapshots = db.scalars(
        select(PerformanceSnapshot)
        .where(PerformanceSnapshot.website_id == website_id)
        .order_by(PerformanceSnapshot.created_at.desc())
    ).all()

    # Get the most recent execution ID for field and lab
    field_execution_id = next(
        (s.execution_id for s in snapshots if s.evidence_type == "field"), None
    )
    lab_execution_id = next((s.execution_id for s in snapshots if s.evidence_type == "lab"), None)

    latest_field = (
        [s for s in snapshots if s.execution_id == field_execution_id] if field_execution_id else []
    )
    latest_lab = (
        [s for s in snapshots if s.execution_id == lab_execution_id] if lab_execution_id else []
    )

    field_dict = {s.metric_id: s.raw_value for s in latest_field if s.raw_value is not None}
    lab_dict = {s.metric_id: s.raw_value for s in latest_lab if s.raw_value is not None}

    disagreements = []

    # Compare LCP (field_lcp vs lab_lcp)
    field_lcp = field_dict.get("field_lcp")
    lab_lcp = lab_dict.get("lab_lcp")
    if field_lcp is not None and lab_lcp is not None:
        max_lcp = max(field_lcp, lab_lcp)
        rel_diff = abs(field_lcp - lab_lcp) / max_lcp if max_lcp > 0 else 0.0
        abs_diff = abs(field_lcp - lab_lcp)

        if rel_diff > 0.2 and abs_diff > 500:
            if field_lcp > lab_lcp:
                disagreements.append(
                    "Field LCP is significantly slower than Lab LCP "
                    "(real users experience worse performance)."
                )
            else:
                disagreements.append(
                    "Field LCP is significantly faster than Lab LCP "
                    "(real users experience better performance)."
                )

    # Compare CLS (field_cls vs lab_cls)
    field_cls = field_dict.get("field_cls")
    lab_cls = lab_dict.get("lab_cls")
    if field_cls is not None and lab_cls is not None:
        max_cls = max(field_cls, lab_cls)
        rel_diff = abs(field_cls - lab_cls) / max_cls if max_cls > 0 else 0.0
        abs_diff = abs(field_cls - lab_cls)

        if rel_diff > 0.2 and abs_diff > 0.05:
            if field_cls > lab_cls:
                disagreements.append(
                    "Field CLS is much higher than Lab CLS (more layout shifts in real usage)."
                )
            else:
                disagreements.append("Lab CLS is much higher than Field CLS.")

    has_disagreement = len(disagreements) > 0
    explanation = " ".join(disagreements) if has_disagreement else "Field and Lab conditions align."

    return {
        "disagreement": has_disagreement,
        "explanation": explanation,
        "field_evidence": [
            {c.name: getattr(s, c.name) for c in s.__table__.columns} for s in latest_field
        ],
        "lab_evidence": [
            {c.name: getattr(s, c.name) for c in s.__table__.columns} for s in latest_lab
        ],
        "snapshots": [{c.name: getattr(s, c.name) for c in s.__table__.columns} for s in snapshots],
    }
