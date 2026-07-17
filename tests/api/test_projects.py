from collections.abc import Iterator

import pytest
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Project, Website
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
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
    def enable_foreign_keys(dbapi_connection: object, connection_record: object) -> None:
        del connection_record
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    def override_get_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def create_project(client: TestClient, name: str = "Acme") -> dict[str, object]:
    response = client.post(
        "/api/v1/projects",
        json={"name": name, "description": "Public websites"},
    )
    assert response.status_code == 201
    return response.json()


def test_create_project(client: TestClient) -> None:
    project = create_project(client)

    assert project["name"] == "Acme"
    assert project["description"] == "Public websites"
    assert project["id"]
    assert project["created_at"]


def test_list_and_retrieve_projects(client: TestClient) -> None:
    created = create_project(client)

    list_response = client.get("/api/v1/projects")
    detail_response = client.get(f"/api/v1/projects/{created['id']}")

    assert list_response.status_code == 200
    assert [project["id"] for project in list_response.json()] == [created["id"]]
    assert detail_response.status_code == 200
    assert detail_response.json()["websites"] == []


def test_add_website(client: TestClient) -> None:
    project = create_project(client)

    response = client.post(
        f"/api/v1/projects/{project['id']}/websites",
        json={"url": "https://example.com", "name": "Main site"},
    )

    assert response.status_code == 201
    assert response.json()["url"] == "https://example.com/"
    detail = client.get(f"/api/v1/projects/{project['id']}").json()
    assert len(detail["websites"]) == 1


def test_invalid_website_url_returns_validation_error(client: TestClient) -> None:
    project = create_project(client)

    response = client.post(
        f"/api/v1/projects/{project['id']}/websites",
        json={"url": "not-a-url"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_duplicate_website_url_in_project_is_rejected(client: TestClient) -> None:
    project = create_project(client)
    path = f"/api/v1/projects/{project['id']}/websites"
    assert client.post(path, json={"url": "https://example.com"}).status_code == 201

    response = client.post(path, json={"url": "https://example.com/"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "WEBSITE_URL_ALREADY_EXISTS"


def test_missing_project_returns_standard_error(client: TestClient) -> None:
    response = client.get("/api/v1/projects/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PROJECT_NOT_FOUND"


def test_delete_project_cascades_to_websites(client: TestClient, db_session: Session) -> None:
    project = create_project(client)
    client.post(
        f"/api/v1/projects/{project['id']}/websites",
        json={"url": "https://example.com"},
    )

    response = client.delete(f"/api/v1/projects/{project['id']}")

    assert response.status_code == 204
    assert db_session.scalar(select(func.count()).select_from(Project)) == 0
    assert db_session.scalar(select(func.count()).select_from(Website)) == 0
