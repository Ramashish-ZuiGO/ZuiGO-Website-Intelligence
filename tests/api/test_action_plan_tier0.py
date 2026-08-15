"""M6: Tier 0 desktop-lane evidence -> Action Plan integration.

Uses the SAME real-Chrome-captured viewport shapes already proven live in
M3/M4 (see test_browser_uat_tier0_ingestion.py), not invented fixtures.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import (
    ActionGroup,
    ActionItem,
    AnalysisRun,
    BrowserUatTier0Execution,
    BrowserUatTier0PageResult,
    BrowserUatTier0ViewportResult,
    Project,
    Website,
    WebsitePage,
)
from app.services.action_generation import (
    _resolve_website_page,
    _tier0_recommendations,
    generate_tier0_actions,
)
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
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


def _seed_website(db: Session) -> Website:
    project = Project(name="Tier0ActionPlanTest")
    db.add(project)
    db.flush()
    website = Website(project_id=project.id, url="https://example.com/")
    db.add(website)
    db.commit()
    return website


def _seed_page(db: Session, website: Website, url: str) -> WebsitePage:
    now = datetime.now(UTC)
    page = WebsitePage(
        website_id=website.id,
        normalized_url=url,
        original_url=url,
        page_type="home",
        page_type_confidence=90,
        page_type_indicators=[],
        classification_version="1.0.0",
        discovery_source="sitemap",
        discovery_evidence=[],
        crawl_depth=0,
        origin_relation="same_origin",
        robots_status="allowed",
        eligibility_status="eligible",
        latest_analysis_status="pending",
        page_analysis_level_1_status="completed",
        first_discovered_at=now,
        last_discovered_at=now,
    )
    db.add(page)
    db.commit()
    return page


def _seed_tier0_execution(db: Session, website: Website) -> BrowserUatTier0Execution:
    analysis_run = AnalysisRun(website_id=website.id, status="completed", progress_percent=100)
    db.add(analysis_run)
    db.flush()
    execution = BrowserUatTier0Execution(
        website_id=website.id,
        analysis_run_id=analysis_run.id,
        lane="github_actions_chrome_edge",
        idempotency_key="tier0-action-key",
        correlation_id="tier0-abcd1234",
        status="completed",
        completed_at=datetime.now(UTC),
    )
    db.add(execution)
    db.commit()
    return execution


def _seed_page_result_with_overflow(
    db: Session, execution: BrowserUatTier0Execution, url: str
) -> BrowserUatTier0PageResult:
    page_result = BrowserUatTier0PageResult(
        execution_id=execution.id,
        browser_channel="chrome",
        platform="windows",
        browser_version="151.0.7922.137",
        url=url,
        http_status=200,
        status="fail",
    )
    db.add(page_result)
    db.flush()
    # Real shape captured live 2026-08-14 against a crafted overflow fixture.
    for name, width, height in (("Desktop", 1440, 900), ("Mobile", 390, 844)):
        db.add(
            BrowserUatTier0ViewportResult(
                page_result_id=page_result.id,
                viewport_name=name,
                viewport_width=width,
                viewport_height=height,
                status="passed",
                horizontal_overflow=True,
                critical_elements_outside_viewport=0,
                overlapping_elements=0,
                small_tap_targets=0,
                responsive_navigation=False,
                viewport_problems=[
                    "Page content overflows the viewport horizontally, "
                    "requiring horizontal scrolling."
                ],
                tap_target_samples=[],
            )
        )
    db.commit()
    return page_result


class TestResolveWebsitePage:
    def test_matches_by_normalized_url(self, db_session: Session) -> None:
        website = _seed_website(db_session)
        page = _seed_page(db_session, website, "https://example.com/")

        resolved = _resolve_website_page(db_session, website.id, "https://example.com/")

        assert resolved is not None
        assert resolved.id == page.id

    def test_returns_none_when_no_page_matches(self, db_session: Session) -> None:
        website = _seed_website(db_session)
        _seed_page(db_session, website, "https://example.com/")

        resolved = _resolve_website_page(db_session, website.id, "https://example.com/unknown")

        assert resolved is None


class TestTier0Recommendations:
    def test_horizontal_overflow_produces_one_recommendation_not_two(self) -> None:
        # The SAME problem was observed at both Desktop and Mobile viewports
        # on one page -- must become one action, not two.
        page_result = BrowserUatTier0PageResult(url="https://example.com/", status="fail")
        viewports = [
            BrowserUatTier0ViewportResult(
                viewport_name="Desktop",
                viewport_width=1440,
                viewport_height=900,
                status="passed",
                horizontal_overflow=True,
                critical_elements_outside_viewport=0,
                overlapping_elements=0,
                small_tap_targets=0,
                viewport_problems=["overflow at desktop"],
                tap_target_samples=[],
            ),
            BrowserUatTier0ViewportResult(
                viewport_name="Mobile",
                viewport_width=390,
                viewport_height=844,
                status="passed",
                horizontal_overflow=True,
                critical_elements_outside_viewport=0,
                overlapping_elements=0,
                small_tap_targets=0,
                viewport_problems=["overflow at mobile"],
                tap_target_samples=[],
            ),
        ]

        recommendations = _tier0_recommendations(page_result, viewports)

        assert len(recommendations) == 1
        assert recommendations[0]["finding_code"] == "TIER0_HORIZONTAL_OVERFLOW"

    def test_multiple_distinct_problems_produce_multiple_recommendations(self) -> None:
        page_result = BrowserUatTier0PageResult(url="https://example.com/", status="fail")
        viewport = BrowserUatTier0ViewportResult(
            viewport_name="Mobile",
            viewport_width=390,
            viewport_height=844,
            status="passed",
            horizontal_overflow=True,
            critical_elements_outside_viewport=2,
            overlapping_elements=1,
            small_tap_targets=3,
            viewport_problems=["overflow", "clipped", "overlap", "tap targets"],
            tap_target_samples=[{"element_type": "button", "width": 10, "height": 10}],
        )

        recommendations = _tier0_recommendations(page_result, [viewport])

        codes = {rec["finding_code"] for rec in recommendations}
        assert codes == {
            "TIER0_HORIZONTAL_OVERFLOW",
            "TIER0_CLIPPED_ELEMENTS",
            "TIER0_OVERLAPPING_ELEMENTS",
            "TIER0_SMALL_TAP_TARGETS",
        }

    def test_a_clean_viewport_produces_no_recommendations(self) -> None:
        page_result = BrowserUatTier0PageResult(url="https://example.com/", status="pass")
        viewport = BrowserUatTier0ViewportResult(
            viewport_name="Desktop",
            viewport_width=1440,
            viewport_height=900,
            status="passed",
            horizontal_overflow=False,
            critical_elements_outside_viewport=0,
            overlapping_elements=0,
            small_tap_targets=0,
            viewport_problems=[],
            tap_target_samples=[],
        )

        assert _tier0_recommendations(page_result, [viewport]) == []


class TestGenerateTier0Actions:
    def test_creates_an_action_group_and_item_for_a_matched_page(self, db_session: Session) -> None:
        website = _seed_website(db_session)
        _seed_page(db_session, website, "https://example.com/")
        execution = _seed_tier0_execution(db_session, website)
        _seed_page_result_with_overflow(db_session, execution, "https://example.com/")

        result = generate_tier0_actions(
            db_session, website_id=website.id, browser_uat_tier0_execution_id=execution.id
        )

        assert result.status == "completed"
        assert result.total_actions_generated == 1
        assert result.unsupported_finding_count == 0
        assert result.insufficient_evidence_count == 0

        groups = db_session.execute(select(ActionGroup)).scalars().all()
        assert len(groups) == 1
        assert groups[0].grouping_key == "tier0_horizontal_overflow"
        assert groups[0].responsible_area == "frontend"
        assert groups[0].source_audit == "browser_uat_tier0"

        items = db_session.execute(select(ActionItem)).scalars().all()
        assert len(items) == 1
        assert items[0].source_audit == "browser_uat_tier0"
        assert items[0].requested_url == "https://example.com/"

    def test_is_idempotent_on_the_same_generation_execution_id(self, db_session: Session) -> None:
        website = _seed_website(db_session)
        _seed_page(db_session, website, "https://example.com/")
        execution = _seed_tier0_execution(db_session, website)
        _seed_page_result_with_overflow(db_session, execution, "https://example.com/")
        generation_id = uuid.uuid4()

        first = generate_tier0_actions(
            db_session,
            website_id=website.id,
            browser_uat_tier0_execution_id=execution.id,
            generation_execution_id=generation_id,
        )
        second = generate_tier0_actions(
            db_session,
            website_id=website.id,
            browser_uat_tier0_execution_id=execution.id,
            generation_execution_id=generation_id,
        )

        assert first.id == second.id
        items = db_session.execute(select(ActionItem)).scalars().all()
        assert len(items) == 1  # not duplicated

    def test_an_unmatched_page_counts_as_insufficient_evidence_not_fabricated(
        self, db_session: Session
    ) -> None:
        # No WebsitePage exists for this URL at all -- must never fabricate
        # a page link just to create an action item.
        website = _seed_website(db_session)
        execution = _seed_tier0_execution(db_session, website)
        _seed_page_result_with_overflow(db_session, execution, "https://example.com/unmatched")

        result = generate_tier0_actions(
            db_session, website_id=website.id, browser_uat_tier0_execution_id=execution.id
        )

        assert result.total_actions_generated == 0
        assert result.insufficient_evidence_count == 1
        assert db_session.execute(select(ActionItem)).scalars().all() == []

    def test_unavailable_tier0_execution_raises(self, db_session: Session) -> None:
        website = _seed_website(db_session)

        with pytest.raises(ValueError, match="unavailable"):
            generate_tier0_actions(
                db_session, website_id=website.id, browser_uat_tier0_execution_id=uuid.uuid4()
            )

    def test_a_page_with_no_problems_generates_no_actions(self, db_session: Session) -> None:
        website = _seed_website(db_session)
        _seed_page(db_session, website, "https://example.com/")
        execution = _seed_tier0_execution(db_session, website)
        page_result = BrowserUatTier0PageResult(
            execution_id=execution.id,
            browser_channel="msedge",
            platform="windows",
            url="https://example.com/",
            http_status=200,
            status="pass",
        )
        db_session.add(page_result)
        db_session.commit()

        result = generate_tier0_actions(
            db_session, website_id=website.id, browser_uat_tier0_execution_id=execution.id
        )

        assert result.total_actions_generated == 0
        assert result.total_findings_processed == 0


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    def override() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


class TestGenerateTier0Route:
    def test_generates_actions_via_the_route(self, client: TestClient, db_session: Session) -> None:
        website = _seed_website(db_session)
        _seed_page(db_session, website, "https://example.com/")
        execution = _seed_tier0_execution(db_session, website)
        _seed_page_result_with_overflow(db_session, execution, "https://example.com/")

        response = client.post(
            f"/api/v1/websites/{website.id}/action-plan/generate-tier0",
            params={"browser_uat_tier0_execution_id": str(execution.id)},
        )

        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "completed"
        assert body["browser_uat_tier0_execution_id"] == str(execution.id)

    def test_unknown_tier0_execution_returns_404(
        self, client: TestClient, db_session: Session
    ) -> None:
        website = _seed_website(db_session)

        response = client.post(
            f"/api/v1/websites/{website.id}/action-plan/generate-tier0",
            params={"browser_uat_tier0_execution_id": str(uuid.uuid4())},
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "BROWSER_UAT_TIER0_EXECUTION_NOT_FOUND"
