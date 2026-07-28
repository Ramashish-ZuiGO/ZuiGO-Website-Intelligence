from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
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
