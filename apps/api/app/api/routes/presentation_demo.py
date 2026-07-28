import hashlib
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_db
from app.errors.exceptions import ApplicationError
from app.models.report_delivery import ReportExecution
from app.schemas.presentation_demo import (
    DemoResetRead,
    DemoRunRequest,
    PresentationDemoRead,
)
from app.services.presentation_demo import (
    demo_status,
    prepare_demo,
    reset_demo,
    run_demo,
)
from app.services.presentation_exports import render_demo_export

router = APIRouter(prefix="/demo", tags=["Presentation demo"])
DatabaseSession = Annotated[Session, Depends(get_db)]


@router.get("", response_model=PresentationDemoRead)
def get_demo_status(db: DatabaseSession) -> dict:
    return demo_status(db)


@router.post("/prepare", response_model=PresentationDemoRead)
def open_prepared_demo(db: DatabaseSession) -> dict:
    return prepare_demo(db)


@router.post("/run", response_model=PresentationDemoRead)
def start_demo(request: DemoRunRequest, db: DatabaseSession) -> dict:
    return run_demo(
        db,
        idempotency_key=request.idempotency_key,
        simulate_failure=request.simulate_failure,
    )


@router.post("/reset", response_model=DemoResetRead)
def clear_demo(db: DatabaseSession) -> DemoResetRead:
    count = reset_demo(db)
    return DemoResetRead(
        reset=True,
        deleted_project_count=count,
        status_message="Managed presentation demo data was reset.",
    )


@router.get("/reports/{report_id}/exports/{export_kind}")
def download_demo_export(
    report_id: uuid.UUID,
    export_kind: str,
    db: DatabaseSession,
) -> Response:
    report = db.scalar(
        select(ReportExecution)
        .options(selectinload(ReportExecution.snapshot))
        .where(
            ReportExecution.report_id == report_id,
            ReportExecution.report_type.in_(("presentation_prepared", "presentation_demo")),
        )
    )
    if report is None or report.snapshot is None:
        raise ApplicationError(
            code="DEMO_REPORT_NOT_FOUND",
            message="Prepared demo report not found.",
            status_code=404,
        )
    try:
        content, media_type, filename = render_demo_export(
            export_kind,
            report.snapshot.snapshot_payload,
        )
    except ValueError as exception:
        raise ApplicationError(
            code="DEMO_EXPORT_UNSUPPORTED",
            message="Supported demo exports are technical-appendix and page-inventory.",
            status_code=422,
        ) from exception
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Content-SHA256": hashlib.sha256(content).hexdigest(),
            "X-Content-Type-Options": "nosniff",
        },
    )
