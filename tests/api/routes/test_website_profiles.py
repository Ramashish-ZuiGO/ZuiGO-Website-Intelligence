import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import app.db.base  # noqa: F401
import pytest
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import AnalysisResult, AnalysisRun, AnalysisStatus, Project
from app.models.website import Website
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def db_session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection: object, record: object) -> None:
        del record
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield session


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    def override() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def test_project(db_session: Session) -> dict:
    project = Project(name="Test Project")
    db_session.add(project)
    db_session.commit()
    return {"id": project.id, "name": project.name}


def test_get_website_profile(client: TestClient, db_session: Session, test_project: dict):
    # Create website
    website_id = uuid.uuid4()
    website = Website(
        id=website_id,
        project_id=test_project["id"],
        url="https://example.com",
        profile_id="global_general",
    )
    db_session.add(website)
    db_session.commit()

    response = client.get(f"/api/v1/websites/{website_id}/profile")
    assert response.status_code == 200
    data = response.json()
    assert data["profile_id"] == "global_general"


def test_update_website_profile(client: TestClient, db_session: Session, test_project: dict):
    website_id = uuid.uuid4()
    website = Website(
        id=website_id,
        project_id=test_project["id"],
        url="https://example.org",
        profile_id="global_general",
    )
    db_session.add(website)
    db_session.commit()

    response = client.put(f"/api/v1/websites/{website_id}/profile?profile_id=india_government")
    assert response.status_code == 200
    data = response.json()
    assert data["profile_id"] == "india_government"

    # Verify DB update
    db_session.refresh(website)
    assert website.profile_id == "india_government"


def test_update_website_profile_invalid(
    client: TestClient, db_session: Session, test_project: dict
):
    website_id = uuid.uuid4()
    website = Website(
        id=website_id,
        project_id=test_project["id"],
        url="https://example.net",
        profile_id="global_general",
    )
    db_session.add(website)
    db_session.commit()

    response = client.put(f"/api/v1/websites/{website_id}/profile?profile_id=invalid_profile")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "BAD_REQUEST"


def test_get_website_metric_interpretations_empty(
    client: TestClient, db_session: Session, test_project: dict
):
    website_id = uuid.uuid4()
    website = Website(
        id=website_id,
        project_id=test_project["id"],
        url="https://example.io",
        profile_id="global_general",
    )
    db_session.add(website)
    db_session.commit()

    response = client.get(f"/api/v1/websites/{website_id}/metric-interpretations")
    assert response.status_code == 200
    assert response.json() == []


def test_get_website_metric_interpretations_uses_persisted_lighthouse_data(
    client: TestClient, db_session: Session, test_project: dict
) -> None:
    website = Website(
        project_id=test_project["id"],
        url="https://metrics.example",
        profile_id="global_general",
    )
    run = AnalysisRun(
        website=website,
        status=AnalysisStatus.COMPLETED,
        profile_id="global_general",
    )
    now = datetime.now(UTC)
    run.result = AnalysisResult(
        requested_url=website.url,
        final_url=website.url,
        http_status_code=200,
        analysis_started_at=now,
        analysis_completed_at=now,
        raw_lighthouse_data={
            "audits": {
                "largest-contentful-paint": {"numericValue": 1800},
            }
        },
        raw_playwright_data={},
    )
    db_session.add(run)
    db_session.commit()

    response = client.get(f"/api/v1/websites/{website.id}/metric-interpretations")

    assert response.status_code == 200
    assert "lighthouse_lcp" in {item["metric_id"] for item in response.json()}
