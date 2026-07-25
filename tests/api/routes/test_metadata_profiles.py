from collections.abc import Iterator

import app.db.base  # noqa: F401
import pytest
from app.db.base import Base
from app.db.session import get_db
from app.main import app
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


def test_get_metadata_profiles(client: TestClient):
    response = client.get("/api/v1/metadata/profiles")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 4
    profile_ids = [p["profile_id"] for p in data]
    assert "global_general" in profile_ids


def test_get_metadata_profile_by_id(client: TestClient):
    response = client.get("/api/v1/metadata/profiles/global_general")
    assert response.status_code == 200
    data = response.json()
    assert data["profile_id"] == "global_general"


def test_get_metadata_profile_invalid(client: TestClient):
    response = client.get("/api/v1/metadata/profiles/non_existent_profile")
    assert response.status_code == 404
