import importlib.util
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from app.api.routes import discovery as discovery_routes
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import (
    AnalysisFinding,
    AnalysisRun,
    AnalysisStatus,
    DiscoveryRun,
    DiscoveryStatus,
    FindingSeverity,
    FindingSource,
    Project,
    Website,
    WebsitePage,
)
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
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


def create_website(db: Session) -> Website:
    project = Project(name="Discovery")
    db.add(project)
    db.flush()
    website = Website(project_id=project.id, url="https://example.com/", name="Example")
    db.add(website)
    db.commit()
    return website


def create_page(
    db: Session,
    website: Website,
    run: DiscoveryRun,
    path: str,
    *,
    eligibility: str = "eligible",
    page_type: str = "unknown",
    robots: str = "allowed",
    analysis_status: str = "pending",
    analysis_run_id: uuid.UUID | None = None,
) -> WebsitePage:
    now = datetime.now(UTC)
    page = WebsitePage(
        website_id=website.id,
        normalized_url=f"https://example.com/{path}",
        original_url=f"https://example.com/{path}",
        page_type=page_type,
        page_type_confidence=80,
        page_type_indicators=[],
        discovery_source="sitemap",
        discovery_evidence=[],
        crawl_depth=0,
        origin_relation="same_origin",
        robots_status=robots,
        eligibility_status=eligibility,
        last_discovery_run_id=run.id,
        latest_analysis_run_id=analysis_run_id,
        latest_analysis_status=analysis_status,
        first_discovered_at=now,
        last_discovered_at=now,
    )
    db.add(page)
    return page


def test_discovery_run_lifecycle_and_existing_project_compatibility(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    website = create_website(db_session)
    monkeypatch.setattr(discovery_routes, "enqueue_discovery", lambda run_id: f"task-{run_id}")
    response = client.post(f"/api/v1/websites/{website.id}/discovery-runs")
    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["progress_percent"] == 0
    status_response = client.get(f"/api/v1/discovery-runs/{payload['id']}")
    assert status_response.status_code == 200
    project_response = client.get(f"/api/v1/projects/{website.project_id}")
    assert project_response.status_code == 200
    assert project_response.json()["websites"][0]["id"] == str(website.id)


def test_page_uniqueness_pagination_filters_and_safe_query_redaction(
    client: TestClient, db_session: Session
) -> None:
    website = create_website(db_session)
    run = DiscoveryRun(
        website_id=website.id,
        status=DiscoveryStatus.COMPLETED,
        progress_percent=100,
        current_stage="completed",
        created_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    db_session.add(run)
    db_session.flush()
    create_page(db_session, website, run, "contact?token=secret", page_type="contact")
    create_page(
        db_session,
        website,
        run,
        "private",
        eligibility="excluded",
        robots="disallowed",
    )
    db_session.commit()

    first = client.get(
        f"/api/v1/websites/{website.id}/pages?page=1&page_size=1&eligibility=eligible"
    )
    assert first.status_code == 200
    assert first.json()["total"] == 1
    assert first.json()["total_pages"] == 1
    assert "secret" not in first.json()["items"][0]["normalized_url"]
    assert "%5Bredacted%5D" in first.json()["items"][0]["normalized_url"]
    filtered = client.get(f"/api/v1/websites/{website.id}/pages?robots_status=disallowed")
    assert filtered.json()["items"][0]["eligibility_status"] == "excluded"

    duplicate = create_page(db_session, website, run, "private")
    db_session.add(duplicate)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_coverage_formula_and_zero_eligible_behavior(
    client: TestClient, db_session: Session
) -> None:
    website = create_website(db_session)
    empty_run = DiscoveryRun(
        website_id=website.id,
        status=DiscoveryStatus.COMPLETED,
        progress_percent=100,
        current_stage="completed",
    )
    db_session.add(empty_run)
    db_session.commit()
    empty = client.get(f"/api/v1/websites/{website.id}/coverage").json()
    assert empty["analyzed_coverage_denominator"] == 0
    assert empty["analyzed_coverage_percent"] is None

    analysis = AnalysisRun(
        website_id=website.id,
        status=AnalysisStatus.COMPLETED,
        progress_percent=100,
    )
    run = DiscoveryRun(
        website_id=website.id,
        status=DiscoveryStatus.PARTIAL,
        progress_percent=100,
        current_stage="completed",
        urls_discovered=4,
        crawl_limit_reached=True,
        created_at=datetime.now(UTC),
    )
    db_session.add_all([analysis, run])
    db_session.flush()
    create_page(
        db_session,
        website,
        run,
        "analyzed",
        analysis_status="completed",
        analysis_run_id=analysis.id,
    )
    create_page(db_session, website, run, "pending")
    create_page(db_session, website, run, "blocked", eligibility="excluded", robots="disallowed")
    db_session.add(
        AnalysisFinding(
            analysis_run_id=analysis.id,
            finding_code="TEST",
            category="technical",
            title="Test",
            description="Test",
            severity=FindingSeverity.LOW,
            affected_url="https://example.com/analyzed",
            evidence={},
            source=FindingSource.PLAYWRIGHT,
            confidence_percent=100,
        )
    )
    db_session.commit()
    coverage = client.get(f"/api/v1/websites/{website.id}/coverage").json()
    assert coverage["analyzed_coverage_numerator"] == 1
    assert coverage["analyzed_coverage_denominator"] == 2
    assert coverage["analyzed_coverage_percent"] == 50.0
    assert coverage["pages_requiring_action"] == 1
    assert coverage["robots_disallowed_pages"] == 1
    assert coverage["crawl_limit_reached"] is True


def test_migration_upgrade_and_downgrade_are_reversible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = importlib.util.spec_from_file_location(
        "discovery_migration",
        "apps/api/alembic/versions/20260723_0008_website_discovery.py",
    )
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    class Operations:
        def __init__(self) -> None:
            self.created: list[str] = []
            self.dropped: list[str] = []

        def create_table(self, name: str, *args: object, **kwargs: object) -> None:
            self.created.append(name)

        def create_index(self, *args: object, **kwargs: object) -> None:
            return None

        def drop_index(self, *args: object, **kwargs: object) -> None:
            return None

        def drop_table(self, name: str) -> None:
            self.dropped.append(name)

    operations = Operations()
    monkeypatch.setattr(migration, "op", operations)
    migration.upgrade()
    migration.downgrade()
    assert operations.created == ["discovery_runs", "website_pages"]
    assert operations.dropped == ["website_pages", "discovery_runs"]
