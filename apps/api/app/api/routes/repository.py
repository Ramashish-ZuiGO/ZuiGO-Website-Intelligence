import math
import subprocess
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.errors.exceptions import ApplicationError
from app.models import (
    ActionMatchingExecution,
    ActionRepositoryMatch,
    DetectedTechnology,
    Project,
    RepositoryConnection,
    RepositoryFileIndex,
    RepositoryScanExecution,
)
from app.schemas.repository import (
    ActionMatchingExecutionRead,
    ActionMatchingStartRequest,
    ActionRepositoryMatchRead,
    DetectedTechnologyRead,
    PaginatedResponse,
    RepositoryConnectionCreate,
    RepositoryConnectionRead,
    RepositoryConnectionUpdate,
    RepositoryConnectionValidate,
    RepositoryFileDetailRead,
    RepositoryFileIndexRead,
    RepositoryScanExecutionRead,
    RepositoryScanStartRequest,
    RepositoryScanSummaryRead,
)


class ValidatePathInput(BaseModel):
    local_root: str


router = APIRouter(prefix="/projects/{project_id}/repository", tags=["repository"])
DatabaseSession = Annotated[Session, Depends(get_db)]


def project_or_raise(db: Session, project_id: uuid.UUID) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise ApplicationError(
            code="PROJECT_NOT_FOUND",
            message="Project not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return project


def connection_or_raise(
    db: Session, connection_id: uuid.UUID, project_id: uuid.UUID
) -> RepositoryConnection:
    conn = db.get(RepositoryConnection, connection_id)
    if conn is None or conn.project_id != project_id:
        raise ApplicationError(
            code="CONNECTION_NOT_FOUND",
            message="Repository connection not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return conn


def scan_or_raise(
    db: Session, scan_id: uuid.UUID, project_id: uuid.UUID
) -> RepositoryScanExecution:
    scan = db.get(RepositoryScanExecution, scan_id)
    if scan is None:
        raise ApplicationError(
            code="SCAN_NOT_FOUND",
            message="Scan execution not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    conn = db.get(RepositoryConnection, scan.connection_id)
    if conn is None or conn.project_id != project_id:
        raise ApplicationError(
            code="SCAN_NOT_FOUND",
            message="Scan execution not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return scan


# ---------------------------------------------------------------------------
# Route 1: POST /connections
# ---------------------------------------------------------------------------
@router.post(
    "/connections",
    response_model=RepositoryConnectionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_connection(
    project_id: uuid.UUID,
    body: RepositoryConnectionCreate,
    db: DatabaseSession,
) -> RepositoryConnectionRead:
    project_or_raise(db, project_id)

    existing = db.scalar(
        select(RepositoryConnection).where(RepositoryConnection.project_id == project_id).limit(1)
    )
    if existing is not None:
        raise ApplicationError(
            code="CONNECTION_ALREADY_EXISTS",
            message="A repository connection already exists for this project.",
            status_code=status.HTTP_409_CONFLICT,
        )

    provider = body.provider
    local_root = body.local_root
    remote_url = body.remote_url

    default_branch: str | None = None
    current_branch: str | None = None
    current_commit_sha: str | None = None

    resolved_root = local_root

    if provider == "local":
        from app.services.repository.path_safety import validate_repository_path

        resolved_root = validate_repository_path(local_root)

        is_git = False
        try:
            git_result = subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                cwd=resolved_root,
                capture_output=True,
                text=True,
                timeout=30,
            )
            is_git = git_result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            is_git = False

        if is_git:
            connection_status = "active"
            try:
                branch_result = subprocess.run(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    cwd=resolved_root,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if branch_result.returncode == 0:
                    current_branch = branch_result.stdout.strip()
                    default_branch = current_branch

                commit_result = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=resolved_root,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if commit_result.returncode == 0:
                    current_commit_sha = commit_result.stdout.strip()
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass
        else:
            connection_status = "unlinked"
    else:
        connection_status = "pending"

    conn = RepositoryConnection(
        project_id=project_id,
        provider=provider,
        display_name=body.display_name,
        local_root=resolved_root,
        remote_url=remote_url,
        default_branch=default_branch,
        current_branch=current_branch,
        current_commit_sha=current_commit_sha,
        status=connection_status,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)

    return RepositoryConnectionRead.model_validate(conn)


# ---------------------------------------------------------------------------
# Route 2: GET /connections
# ---------------------------------------------------------------------------
@router.get("/connections", response_model=list[RepositoryConnectionRead])
def list_connections(
    project_id: uuid.UUID,
    db: DatabaseSession,
) -> list[RepositoryConnectionRead]:
    project_or_raise(db, project_id)

    rows = list(
        db.scalars(
            select(RepositoryConnection)
            .where(RepositoryConnection.project_id == project_id)
            .order_by(RepositoryConnection.created_at.desc())
        )
    )
    return [RepositoryConnectionRead.model_validate(r) for r in rows]


# ---------------------------------------------------------------------------
# Route 3: GET /connections/{connection_id}
# ---------------------------------------------------------------------------
@router.get("/connections/{connection_id}", response_model=RepositoryConnectionRead)
def get_connection(
    project_id: uuid.UUID,
    connection_id: uuid.UUID,
    db: DatabaseSession,
) -> RepositoryConnectionRead:
    conn = connection_or_raise(db, connection_id, project_id)
    return RepositoryConnectionRead.model_validate(conn)


# ---------------------------------------------------------------------------
# Route 4: PATCH /connections/{connection_id}
# ---------------------------------------------------------------------------
@router.patch("/connections/{connection_id}", response_model=RepositoryConnectionRead)
def update_connection(
    project_id: uuid.UUID,
    connection_id: uuid.UUID,
    body: RepositoryConnectionUpdate,
    db: DatabaseSession,
) -> RepositoryConnectionRead:
    conn = connection_or_raise(db, connection_id, project_id)

    if body.display_name is not None:
        conn.display_name = body.display_name
    if body.remote_url is not None:
        conn.remote_url = body.remote_url
    if body.status is not None:
        conn.status = body.status
    if body.local_root is not None:
        from app.services.repository.path_safety import validate_repository_path

        resolved = validate_repository_path(body.local_root)
        conn.local_root = resolved

    db.commit()
    db.refresh(conn)

    return RepositoryConnectionRead.model_validate(conn)


# ---------------------------------------------------------------------------
# Route 5: DELETE /connections/{connection_id}
# ---------------------------------------------------------------------------
@router.delete("/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_connection(
    project_id: uuid.UUID,
    connection_id: uuid.UUID,
    db: DatabaseSession,
) -> Response:
    conn = connection_or_raise(db, connection_id, project_id)
    db.delete(conn)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Route 6: POST /connections/{connection_id}/validate
# ---------------------------------------------------------------------------
@router.post(
    "/connections/{connection_id}/validate",
    response_model=RepositoryConnectionValidate,
)
def validate_connection_path(
    project_id: uuid.UUID,
    connection_id: uuid.UUID,
    body: ValidatePathInput,
    db: DatabaseSession,
) -> RepositoryConnectionValidate:
    project_or_raise(db, project_id)

    local_root = body.local_root
    error_message: str | None = None
    is_git = False

    try:
        from app.services.repository.path_safety import validate_repository_path

        resolved = validate_repository_path(local_root)

        git_result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=resolved,
            capture_output=True,
            text=True,
            timeout=30,
        )
        is_git = git_result.returncode == 0
    except ApplicationError:
        raise
    except Exception as exc:
        error_message = str(exc)

    return RepositoryConnectionValidate(
        local_root=local_root,
        is_git=is_git,
        error_message=error_message,
    )


# ---------------------------------------------------------------------------
# Route 7: POST /connections/{connection_id}/scans
# ---------------------------------------------------------------------------
@router.post(
    "/connections/{connection_id}/scans",
    response_model=RepositoryScanExecutionRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_scan(
    project_id: uuid.UUID,
    connection_id: uuid.UUID,
    body: RepositoryScanStartRequest,
    db: DatabaseSession,
) -> RepositoryScanExecutionRead:
    conn = connection_or_raise(db, connection_id, project_id)

    if conn.status in ("pending", "unlinked"):
        raise ApplicationError(
            code="CONNECTION_NOT_ACTIVE",
            message="Repository connection is not active. Cannot start a scan.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    execution_id = uuid.uuid4()
    now = datetime.now(UTC)

    execution = RepositoryScanExecution(
        id=execution_id,
        connection_id=connection_id,
        requested_commit_sha=body.commit_sha,
        branch=body.branch,
        status="running",
        started_at=now,
    )
    db.add(execution)
    db.commit()

    try:
        from app.services.repository.git_scanner import RepositoryScannerService

        scanner = RepositoryScannerService(db=db)
        scanner.scan_repository(
            connection_id=connection_id,
            execution_id=execution_id,
            commit_sha=body.commit_sha,
            branch=body.branch,
        )

        db.refresh(execution)

        from app.services.repository.framework_detector import FrameworkDetectionService

        detector = FrameworkDetectionService(db=db)
        detector.detect_frameworks(scan_execution_id=execution_id)

        execution.status = "completed"
        execution.completed_at = datetime.now(UTC)
    except Exception as exc:
        execution.status = "failed"
        execution.failure_explanation = str(exc)
        execution.completed_at = datetime.now(UTC)

    conn.last_scan_execution_id = execution_id
    db.commit()
    db.refresh(execution)

    return RepositoryScanExecutionRead.model_validate(execution)


# ---------------------------------------------------------------------------
# Route 8: GET /connections/{connection_id}/scans
# ---------------------------------------------------------------------------
@router.get("/connections/{connection_id}/scans", response_model=PaginatedResponse)
def list_scans(
    project_id: uuid.UUID,
    connection_id: uuid.UUID,
    db: DatabaseSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> PaginatedResponse:
    connection_or_raise(db, connection_id, project_id)

    filters = [RepositoryScanExecution.connection_id == connection_id]
    total = (
        db.scalar(select(func.count()).select_from(RepositoryScanExecution).where(*filters)) or 0
    )

    rows = list(
        db.scalars(
            select(RepositoryScanExecution)
            .where(*filters)
            .order_by(RepositoryScanExecution.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )

    items = [RepositoryScanExecutionRead.model_validate(r) for r in rows]

    return PaginatedResponse(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        total_pages=math.ceil(total / page_size) if total else 0,
    )


# ---------------------------------------------------------------------------
# Route 9: GET /scans/{scan_id}
# ---------------------------------------------------------------------------
@router.get("/scans/{scan_id}", response_model=RepositoryScanExecutionRead)
def get_scan(
    project_id: uuid.UUID,
    scan_id: uuid.UUID,
    db: DatabaseSession,
) -> RepositoryScanExecutionRead:
    scan = scan_or_raise(db, scan_id, project_id)
    return RepositoryScanExecutionRead.model_validate(scan)


# ---------------------------------------------------------------------------
# Route 10: GET /scans/{scan_id}/files
# ---------------------------------------------------------------------------
@router.get("/scans/{scan_id}/files", response_model=PaginatedResponse)
def list_scan_files(
    project_id: uuid.UUID,
    scan_id: uuid.UUID,
    db: DatabaseSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    extension: str | None = Query(default=None, max_length=50),
    scan_status: str | None = Query(default=None, max_length=30),
    language: str | None = Query(default=None, max_length=100),
    search: str | None = Query(default=None, max_length=300),
) -> PaginatedResponse:
    scan_or_raise(db, scan_id, project_id)

    filters = [RepositoryFileIndex.scan_execution_id == scan_id]

    if extension:
        filters.append(RepositoryFileIndex.extension == extension)
    if scan_status:
        filters.append(RepositoryFileIndex.scan_status == scan_status)
    if language:
        filters.append(RepositoryFileIndex.detected_language == language)
    if search:
        filters.append(RepositoryFileIndex.relative_path.ilike(f"%{search}%"))

    total = db.scalar(select(func.count()).select_from(RepositoryFileIndex).where(*filters)) or 0

    rows = list(
        db.scalars(
            select(RepositoryFileIndex)
            .where(*filters)
            .order_by(RepositoryFileIndex.relative_path.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )

    items = [RepositoryFileIndexRead.model_validate(r) for r in rows]

    return PaginatedResponse(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        total_pages=math.ceil(total / page_size) if total else 0,
    )


# ---------------------------------------------------------------------------
# Route 11: GET /scans/{scan_id}/files/{file_id}
# ---------------------------------------------------------------------------
@router.get("/scans/{scan_id}/files/{file_id}", response_model=RepositoryFileDetailRead)
def get_scan_file_detail(
    project_id: uuid.UUID,
    scan_id: uuid.UUID,
    file_id: uuid.UUID,
    db: DatabaseSession,
) -> RepositoryFileDetailRead:
    scan_or_raise(db, scan_id, project_id)

    file_row = db.scalar(
        select(RepositoryFileIndex).where(
            RepositoryFileIndex.id == file_id,
            RepositoryFileIndex.scan_execution_id == scan_id,
        )
    )
    if file_row is None:
        raise ApplicationError(
            code="FILE_NOT_FOUND",
            message="File not found in this scan execution.",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return RepositoryFileDetailRead.model_validate(file_row)


# ---------------------------------------------------------------------------
# Route 12: GET /scans/{scan_id}/technologies
# ---------------------------------------------------------------------------
@router.get("/scans/{scan_id}/technologies", response_model=list[DetectedTechnologyRead])
def list_scan_technologies(
    project_id: uuid.UUID,
    scan_id: uuid.UUID,
    db: DatabaseSession,
) -> list[DetectedTechnologyRead]:
    scan_or_raise(db, scan_id, project_id)

    rows = list(
        db.scalars(
            select(DetectedTechnology)
            .where(DetectedTechnology.scan_execution_id == scan_id)
            .order_by(DetectedTechnology.created_at.desc())
        )
    )
    return [DetectedTechnologyRead.model_validate(r) for r in rows]


# ---------------------------------------------------------------------------
# Route 13: POST /connections/{connection_id}/match-actions
# ---------------------------------------------------------------------------
@router.post(
    "/connections/{connection_id}/match-actions",
    response_model=ActionMatchingExecutionRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_action_matching(
    project_id: uuid.UUID,
    connection_id: uuid.UUID,
    body: ActionMatchingStartRequest,
    db: DatabaseSession,
) -> ActionMatchingExecutionRead:
    connection_or_raise(db, connection_id, project_id)

    matching_id = uuid.uuid4()
    now = datetime.now(UTC)

    matching = ActionMatchingExecution(
        id=matching_id,
        connection_id=connection_id,
        scan_execution_id=body.scan_execution_id,
        generation_execution_id=body.generation_execution_id,
        status="running",
        started_at=now,
    )
    db.add(matching)
    db.commit()

    try:
        from app.services.repository.action_matcher import ActionToCodeMatcherService

        matcher = ActionToCodeMatcherService(db=db)
        matcher.match_actions(
            matching_execution_id=matching_id,
            connection_id=connection_id,
            scan_execution_id=body.scan_execution_id,
            generation_execution_id=body.generation_execution_id,
        )

        db.refresh(matching)
        matching.status = "completed"
        matching.completed_at = datetime.now(UTC)
    except Exception:
        matching.status = "failed"
        matching.completed_at = datetime.now(UTC)

    db.commit()
    db.refresh(matching)

    return ActionMatchingExecutionRead.model_validate(matching)


# ---------------------------------------------------------------------------
# Route 14: GET /connections/{connection_id}/match-results
# ---------------------------------------------------------------------------
@router.get(
    "/connections/{connection_id}/match-results",
    response_model=list[ActionRepositoryMatchRead],
)
def get_match_results(
    project_id: uuid.UUID,
    connection_id: uuid.UUID,
    db: DatabaseSession,
    matching_execution_id: Annotated[uuid.UUID | None, Query()] = None,
) -> list[ActionRepositoryMatchRead]:
    connection_or_raise(db, connection_id, project_id)

    if matching_execution_id is not None:
        exec_row = db.get(ActionMatchingExecution, matching_execution_id)
        if exec_row is None or exec_row.connection_id != connection_id:
            raise ApplicationError(
                code="MATCHING_EXECUTION_NOT_FOUND",
                message="Matching execution not found for this connection.",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        match_exec_id = matching_execution_id
    else:
        latest = db.scalar(
            select(ActionMatchingExecution)
            .where(ActionMatchingExecution.connection_id == connection_id)
            .order_by(ActionMatchingExecution.created_at.desc())
            .limit(1)
        )
        if latest is None:
            return []
        match_exec_id = latest.id

    rows = list(
        db.scalars(
            select(ActionRepositoryMatch)
            .where(ActionRepositoryMatch.matching_execution_id == match_exec_id)
            .order_by(ActionRepositoryMatch.created_at.desc())
        )
    )
    return [ActionRepositoryMatchRead.model_validate(r) for r in rows]


# ---------------------------------------------------------------------------
# Route 15: GET /scans/{scan_id}/summary
# ---------------------------------------------------------------------------
@router.get("/scans/{scan_id}/summary", response_model=RepositoryScanSummaryRead)
def get_scan_summary(
    project_id: uuid.UUID,
    scan_id: uuid.UUID,
    db: DatabaseSession,
) -> RepositoryScanSummaryRead:
    scan = scan_or_raise(db, scan_id, project_id)

    total_technologies = (
        db.scalar(
            select(func.count())
            .select_from(DetectedTechnology)
            .where(DetectedTechnology.scan_execution_id == scan_id)
        )
        or 0
    )

    matching_exec = db.scalar(
        select(ActionMatchingExecution)
        .where(ActionMatchingExecution.scan_execution_id == scan_id)
        .order_by(ActionMatchingExecution.created_at.desc())
        .limit(1)
    )

    total_actions_matched = 0
    located_actions = 0
    unlocated_actions = 0

    if matching_exec is not None:
        total_actions_matched = matching_exec.total_actions
        located_actions = matching_exec.located_actions
        unlocated_actions = matching_exec.unlocated_actions

    return RepositoryScanSummaryRead(
        total_files_discovered=scan.total_files_discovered,
        eligible_files=scan.eligible_files,
        scanned_files=scan.scanned_files,
        skipped_files=scan.skipped_files,
        failed_files=scan.failed_files,
        total_technologies=total_technologies,
        total_actions_matched=total_actions_matched,
        located_actions=located_actions,
        unlocated_actions=unlocated_actions,
    )
