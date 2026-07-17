import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_db
from app.errors.exceptions import ApplicationError
from app.models import Project, Website
from app.schemas import ProjectCreate, ProjectDetail, ProjectRead, WebsiteCreate, WebsiteRead

router = APIRouter(prefix="/projects", tags=["projects"])
DatabaseSession = Annotated[Session, Depends(get_db)]


def get_project_or_raise(db: Session, project_id: uuid.UUID) -> Project:
    project = db.scalar(
        select(Project).options(selectinload(Project.websites)).where(Project.id == project_id)
    )
    if project is None:
        raise ApplicationError(
            code="PROJECT_NOT_FOUND",
            message="Project not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return project


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, db: DatabaseSession) -> Project:
    project = Project(name=payload.name, description=payload.description)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("", response_model=list[ProjectRead])
def list_projects(db: DatabaseSession) -> list[Project]:
    return list(db.scalars(select(Project).order_by(Project.created_at.desc())))


@router.get("/{project_id}", response_model=ProjectDetail)
def get_project(project_id: uuid.UUID, db: DatabaseSession) -> Project:
    return get_project_or_raise(db, project_id)


@router.post(
    "/{project_id}/websites",
    response_model=WebsiteRead,
    status_code=status.HTTP_201_CREATED,
)
def add_website(project_id: uuid.UUID, payload: WebsiteCreate, db: DatabaseSession) -> Website:
    get_project_or_raise(db, project_id)
    website = Website(project_id=project_id, url=str(payload.url), name=payload.name)
    db.add(website)
    try:
        db.commit()
    except IntegrityError as exception:
        db.rollback()
        raise ApplicationError(
            code="WEBSITE_URL_ALREADY_EXISTS",
            message="This website URL already exists in the project.",
            status_code=status.HTTP_409_CONFLICT,
        ) from exception
    db.refresh(website)
    return website


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: uuid.UUID, db: DatabaseSession) -> Response:
    project = get_project_or_raise(db, project_id)
    db.delete(project)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
