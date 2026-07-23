import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import (
    DiscoveryRun,
    DiscoveryStatus,
    PageAnalysisRun,
    Project,
    Website,
    WebsitePage,
)
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


def create_website(db: Session) -> tuple[Project, Website]:
    project = Project(name="PageAnalysis")
    db.add(project)
    db.flush()
    website = Website(project_id=project.id, url="https://example.com/", name="Example")
    db.add(website)
    db.commit()
    return project, website


def create_discovery_run(db: Session, website: Website) -> DiscoveryRun:
    run = DiscoveryRun(
        website_id=website.id,
        status=DiscoveryStatus.COMPLETED,
        progress_percent=100,
        current_stage="completed",
        urls_discovered=5,
        urls_unique=5,
        urls_eligible=3,
        urls_excluded=1,
        urls_skipped=1,
        sitemap_count=1,
        crawl_limit_reached=False,
        maximum_depth_reached=2,
        created_at=datetime.now(UTC),
    )
    db.add(run)
    db.flush()
    return run


def create_page(
    db: Session,
    website: Website,
    run: DiscoveryRun,
    path: str,
    *,
    page_type: str = "unknown",
    eligibility: str = "eligible",
    robots: str = "allowed",
    l1_status: str = "pending",
    l2_status: str = "pending",
) -> WebsitePage:
    now = datetime.now(UTC)
    page = WebsitePage(
        website_id=website.id,
        normalized_url=f"https://example.com/{path}",
        original_url=f"https://example.com/{path}",
        page_type=page_type,
        page_type_confidence=80,
        page_type_indicators=[],
        classification_version="1.0.0",
        discovery_source="sitemap",
        discovery_evidence=[],
        crawl_depth=1,
        origin_relation="same_origin",
        robots_status=robots,
        eligibility_status=eligibility,
        last_discovery_run_id=run.id,
        latest_analysis_status="pending",
        page_analysis_level_1_status=l1_status,
        page_analysis_level_2_status=l2_status,
        first_discovered_at=now,
        last_discovered_at=now,
    )
    db.add(page)
    db.flush()
    return page


def test_page_analysis_summary_zero_state(client: TestClient, db_session: Session) -> None:
    website = create_website(db_session)[1]
    response = client.get(f"/api/v1/websites/{website.id}/page-analysis/summary")
    assert response.status_code == 200
    data = response.json()
    assert data["total_pages"] == 0
    assert data["eligible_pages"] == 0
    assert data["coverage_percent"] is None


def test_page_analysis_summary_with_data(client: TestClient, db_session: Session) -> None:
    website = create_website(db_session)[1]
    run = create_discovery_run(db_session, website)
    create_page(db_session, website, run, "page1", l1_status="completed")
    create_page(db_session, website, run, "page2", l1_status="failed")
    create_page(db_session, website, run, "page3", eligibility="excluded")
    db_session.commit()

    response = client.get(f"/api/v1/websites/{website.id}/page-analysis/summary")
    assert response.status_code == 200
    data = response.json()
    assert data["eligible_pages"] == 2
    assert data["level_1_completed"] == 1
    assert data["level_1_failed"] == 1
    assert data["level_1_pending"] == 0
    assert data["coverage_percent"] == 100.0


def test_page_analysis_coverage(client: TestClient, db_session: Session) -> None:
    website = create_website(db_session)[1]
    run = create_discovery_run(db_session, website)
    create_page(db_session, website, run, "ok", l1_status="completed")
    create_page(db_session, website, run, "fail", l1_status="failed")
    create_page(db_session, website, run, "skip", eligibility="excluded")
    db_session.commit()

    response = client.get(f"/api/v1/websites/{website.id}/page-analysis/coverage")
    assert response.status_code == 200
    data = response.json()
    assert data["discovered_page_count"] == 3
    assert data["eligible_page_count"] == 2
    assert data["level_1_attempted"] == 2
    assert data["level_1_successful"] == 1
    assert data["level_1_failed"] == 1
    assert data["coverage_percent"] == 100.0


def test_page_analysis_failed_pages(client: TestClient, db_session: Session) -> None:
    website = create_website(db_session)[1]
    run = create_discovery_run(db_session, website)
    page = create_page(db_session, website, run, "broken", l1_status="failed")
    db_session.commit()

    l1_run = PageAnalysisRun(
        website_page_id=page.id,
        page_analysis_execution_id=uuid.uuid4(),
        analysis_level=1,
        status="failed",
        failure_reason_code="http_error",
        failure_reason_text="HTTP error 500",
    )
    db_session.add(l1_run)
    db_session.flush()
    db_session.execute(
        WebsitePage.__table__.update()
        .where(WebsitePage.id == page.id)
        .values(page_analysis_level_1_run_id=l1_run.id)
    )
    db_session.commit()

    response = client.get(f"/api/v1/websites/{website.id}/page-analysis/failed-skipped")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["page_url"] == "https://example.com/broken"
    assert "level_1" in data[0]["statuses"]
    assert data[0]["statuses"]["level_1"]["reason_code"] == "http_error"


def test_page_analysis_recommendations(client: TestClient, db_session: Session) -> None:
    website = create_website(db_session)[1]
    run = create_discovery_run(db_session, website)
    now = datetime.now(UTC)
    page = WebsitePage(
        website_id=website.id,
        normalized_url="https://example.com/no-title",
        original_url="https://example.com/no-title",
        page_type="unknown",
        page_type_confidence=80,
        page_type_indicators=[],
        classification_version="1.0.0",
        discovery_source="sitemap",
        discovery_evidence=[],
        crawl_depth=1,
        origin_relation="same_origin",
        robots_status="allowed",
        eligibility_status="eligible",
        last_discovery_run_id=run.id,
        latest_analysis_status="pending",
        page_analysis_level_1_status="completed",
        first_discovered_at=now,
        last_discovered_at=now,
    )
    db_session.add(page)
    db_session.flush()

    l1_run = PageAnalysisRun(
        website_page_id=page.id,
        page_analysis_execution_id=uuid.uuid4(),
        analysis_level=1,
        status="completed",
        requested_url="https://example.com/no-title",
        final_url="https://example.com/no-title",
        page_title=None,
        basic_seo_signals={
            "has_title": False,
            "has_meta_description": False,
            "has_canonical": False,
            "h1_count": 0,
            "multiple_h1": False,
            "no_h1": True,
        },
        basic_accessibility_signals={
            "images_missing_alt": 3,
            "has_html_lang": False,
            "heading_count": 0,
            "heading_gaps": [1, 2, 3, 4, 5, 6],
        },
        security_observations={
            "https": True,
            "x_frame_options": "DENY",
            "x_content_type_options": None,
            "content_security_policy": None,
        },
    )
    db_session.add(l1_run)
    db_session.flush()
    db_session.execute(
        WebsitePage.__table__.update()
        .where(WebsitePage.id == page.id)
        .values(page_analysis_level_1_run_id=l1_run.id)
    )
    db_session.commit()

    response = client.get(f"/api/v1/websites/{website.id}/page-analysis/recommendations")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 5
    titles = {item["issue_title"] for item in data}
    assert "Missing H1 heading" in titles
    assert "Missing page title" in titles
    assert "Missing meta description" in titles
    assert "Missing canonical URL" in titles
    assert any("images missing alt text" in t for t in titles)
    assert all(item["page_url"] == "https://example.com/no-title" for item in data)


def test_page_analysis_scores_no_data(client: TestClient, db_session: Session) -> None:
    website = create_website(db_session)[1]
    response = client.get(f"/api/v1/websites/{website.id}/page-analysis/scores")
    assert response.status_code == 200
    assert response.json() == []


def test_page_analysis_backward_compatibility(client: TestClient, db_session: Session) -> None:
    project, website = create_website(db_session)
    project_resp = client.get(f"/api/v1/projects/{project.id}")
    assert project_resp.status_code == 200
    assert "websites" in project_resp.json()


def test_page_inventory_response(client: TestClient, db_session: Session) -> None:
    website = create_website(db_session)[1]
    run = create_discovery_run(db_session, website)
    create_page(db_session, website, run, "inventory-test")
    db_session.commit()
    response = client.get(f"/api/v1/websites/{website.id}/pages")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "page_analysis_level_1_status" in data["items"][0]
    assert "page_analysis_level_2_status" in data["items"][0]


def test_page_analysis_pagination(client: TestClient, db_session: Session) -> None:
    website = create_website(db_session)[1]
    run = create_discovery_run(db_session, website)
    for i in range(5):
        create_page(
            db_session,
            website,
            run,
            f"page-{i}",
            l1_status="completed" if i < 3 else "pending",
        )
    db_session.commit()

    response = client.get(f"/api/v1/websites/{website.id}/page-analysis/runs?page=1&page_size=2")
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) <= 2
    assert data["total"] == 5
    assert data["total_pages"] >= 2


def test_repeated_page_analysis_no_integrity_error(
    db_session: Session,
) -> None:
    website = create_website(db_session)[1]
    run1 = create_discovery_run(db_session, website)
    page = create_page(db_session, website, run1, "repeat-test")
    now = datetime.now(UTC)

    run_a = PageAnalysisRun(
        website_page_id=page.id,
        discovery_run_id=run1.id,
        page_analysis_execution_id=uuid.uuid4(),
        analysis_level=1,
        status="completed",
        requested_url="https://example.com/repeat-test",
        final_url="https://example.com/repeat-test",
        analysis_started_at=now,
        analysis_completed_at=now,
    )
    db_session.add(run_a)
    db_session.flush()

    page.page_analysis_level_1_run_id = run_a.id
    page.page_analysis_level_1_status = "completed"
    db_session.commit()

    run2 = DiscoveryRun(
        website_id=website.id,
        status=DiscoveryStatus.COMPLETED,
        progress_percent=100,
        current_stage="completed",
        urls_discovered=5,
        urls_unique=5,
        urls_eligible=1,
        urls_excluded=0,
        urls_skipped=0,
        sitemap_count=1,
        crawl_limit_reached=False,
        maximum_depth_reached=1,
        created_at=datetime.now(UTC),
    )
    db_session.add(run2)
    db_session.flush()

    run_b = PageAnalysisRun(
        website_page_id=page.id,
        discovery_run_id=run2.id,
        page_analysis_execution_id=uuid.uuid4(),
        analysis_level=1,
        status="completed",
        requested_url="https://example.com/repeat-test",
        final_url="https://example.com/repeat-test",
        analysis_started_at=now,
        analysis_completed_at=now,
    )
    db_session.add(run_b)
    db_session.flush()

    page.page_analysis_level_1_run_id = run_b.id
    db_session.commit()

    all_runs = list(
        db_session.query(PageAnalysisRun)
        .filter(PageAnalysisRun.website_page_id == page.id)
        .order_by(PageAnalysisRun.created_at.asc())
    )
    assert len(all_runs) == 2
    assert all_runs[0].id == run_a.id
    assert all_runs[1].id == run_b.id

    db_session.refresh(page)
    assert page.page_analysis_level_1_run_id == run_b.id


def test_same_discovery_double_run_no_integrity_error(
    db_session: Session,
) -> None:
    website = create_website(db_session)[1]
    run = create_discovery_run(db_session, website)
    page = create_page(db_session, website, run, "double-run-test")
    db_session.commit()

    page.page_analysis_level_1_status = "pending"
    db_session.commit()

    exec_id_a = uuid.uuid4()
    exec_id_b = uuid.uuid4()
    now = datetime.now(UTC)

    run_a = PageAnalysisRun(
        website_page_id=page.id,
        discovery_run_id=run.id,
        page_analysis_execution_id=exec_id_a,
        analysis_level=1,
        status="completed",
        requested_url="https://example.com/double",
        final_url="https://example.com/double",
        analysis_started_at=now,
        analysis_completed_at=now,
    )
    db_session.add(run_a)
    db_session.flush()
    page.page_analysis_level_1_run_id = run_a.id
    page.page_analysis_level_1_status = "completed"
    db_session.commit()

    run_b = PageAnalysisRun(
        website_page_id=page.id,
        discovery_run_id=run.id,
        page_analysis_execution_id=exec_id_b,
        analysis_level=1,
        status="completed",
        requested_url="https://example.com/double",
        final_url="https://example.com/double",
        analysis_started_at=now,
        analysis_completed_at=now,
    )
    db_session.add(run_b)
    db_session.flush()
    page.page_analysis_level_1_run_id = run_b.id
    db_session.commit()

    all_runs = list(
        db_session.query(PageAnalysisRun)
        .filter(PageAnalysisRun.website_page_id == page.id)
        .order_by(PageAnalysisRun.created_at.asc())
    )
    assert len(all_runs) == 2
    assert all_runs[0].page_analysis_execution_id == exec_id_a
    assert all_runs[1].page_analysis_execution_id == exec_id_b
    assert all_runs[0].discovery_run_id == run.id
    assert all_runs[1].discovery_run_id == run.id
    assert all_runs[0].analysis_level == 1
    assert all_runs[1].analysis_level == 1

    db_session.refresh(page)
    assert page.page_analysis_level_1_run_id == run_b.id


def test_same_execution_id_unique_constraint_enforced(
    db_session: Session,
) -> None:
    website = create_website(db_session)[1]
    run = create_discovery_run(db_session, website)
    page = create_page(db_session, website, run, "unique-test")
    db_session.commit()

    exec_id = uuid.uuid4()
    now = datetime.now(UTC)

    first = PageAnalysisRun(
        website_page_id=page.id,
        discovery_run_id=run.id,
        page_analysis_execution_id=exec_id,
        analysis_level=1,
        status="running",
        analysis_started_at=now,
    )
    db_session.add(first)
    db_session.commit()

    dup = PageAnalysisRun(
        website_page_id=page.id,
        discovery_run_id=run.id,
        page_analysis_execution_id=exec_id,
        analysis_level=1,
        status="running",
    )
    db_session.add(dup)
    import sqlalchemy.exc

    with pytest.raises(sqlalchemy.exc.IntegrityError):
        db_session.flush()
    db_session.rollback()
