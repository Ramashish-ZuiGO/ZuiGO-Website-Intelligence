"""M4: ingest_browser_uat_tier0_job_result.

Fixture payloads are the EXACT JSON shapes captured from live runs of
.github/scripts/browser_uat_tier0_check.mjs against real Chrome 151 and real
Edge 151 (see docs/DEVICE_OS_BROWSER_QA_PLAN.md M2/M3/M4 decision log,
2026-08-14), not invented -- so these tests prove the ingestion function
against what the script actually produces.
"""

import uuid
from collections.abc import Iterator

import pytest
from app.db.base import Base
from app.models import (
    AnalysisRun,
    BrowserUatTier0Execution,
    BrowserUatTier0PageResult,
    BrowserUatTier0ViewportResult,
    Project,
    Website,
)
from app.services.browser_uat_tier0 import ingest_browser_uat_tier0_job_result
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# Captured live 2026-08-14 against a crafted fixture with a 3000px-wide div.
OVERFLOW_JOB_RESULT = {
    "channel": "chrome",
    "platform": "windows",
    "browser_version": "151.0.7922.137",
    "overall_status": "fail",
    "pages": [
        {
            "url": "file:///fixture.html",
            "status": "fail",
            "http_status": 200,
            "console_error_count": 0,
            "viewport_results": [
                {
                    "name": "Desktop",
                    "width": 1440,
                    "height": 900,
                    "status": "passed",
                    "horizontal_overflow": True,
                    "critical_elements_outside_viewport": 0,
                    "overlapping_elements": 0,
                    "responsive_navigation": False,
                    "small_tap_targets": 0,
                    "tap_target_samples": [],
                    "viewport_problems": [
                        "Page content overflows the viewport horizontally, "
                        "requiring horizontal scrolling."
                    ],
                },
                {
                    "name": "Mobile",
                    "width": 390,
                    "height": 844,
                    "status": "passed",
                    "horizontal_overflow": True,
                    "critical_elements_outside_viewport": 0,
                    "overlapping_elements": 0,
                    "responsive_navigation": False,
                    "small_tap_targets": 0,
                    "tap_target_samples": [],
                    "viewport_problems": [
                        "Page content overflows the viewport horizontally, "
                        "requiring horizontal scrolling."
                    ],
                },
            ],
        }
    ],
}

# Captured live 2026-08-14, real Edge, clean fixture.
CLEAN_JOB_RESULT = {
    "channel": "msedge",
    "platform": "windows",
    "browser_version": "151.0.4129.78",
    "overall_status": "pass",
    "pages": [
        {
            "url": "file:///clean.html",
            "status": "pass",
            "http_status": 200,
            "console_error_count": 0,
            "viewport_results": [
                {
                    "name": "Desktop",
                    "width": 1440,
                    "height": 900,
                    "status": "passed",
                    "horizontal_overflow": False,
                    "critical_elements_outside_viewport": 0,
                    "overlapping_elements": 0,
                    "responsive_navigation": True,
                    "small_tap_targets": 0,
                    "tap_target_samples": [],
                    "viewport_problems": [],
                },
                {
                    "name": "Mobile",
                    "width": 390,
                    "height": 844,
                    "status": "passed",
                    "horizontal_overflow": False,
                    "critical_elements_outside_viewport": 0,
                    "overlapping_elements": 0,
                    "responsive_navigation": True,
                    "small_tap_targets": 0,
                    "tap_target_samples": [],
                    "viewport_problems": [],
                },
            ],
        }
    ],
}


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


def _seed_execution(db: Session) -> uuid.UUID:
    project = Project(name="Tier0IngestionTest")
    db.add(project)
    db.flush()
    website = Website(project_id=project.id, url="https://ingestion-fixture.test/")
    db.add(website)
    db.flush()
    analysis_run = AnalysisRun(website_id=website.id, status="completed", progress_percent=100)
    db.add(analysis_run)
    db.flush()
    execution = BrowserUatTier0Execution(
        website_id=website.id,
        analysis_run_id=analysis_run.id,
        lane="github_actions_chrome_edge",
        idempotency_key="ingestion-key-1",
        correlation_id="tier0-abcd1234",
    )
    db.add(execution)
    db.commit()
    return execution.id


class TestFreshIngestion:
    def test_creates_one_page_result_per_page(self, db_session: Session) -> None:
        execution_id = _seed_execution(db_session)

        page_results = ingest_browser_uat_tier0_job_result(
            db_session, execution_id=execution_id, job_result=OVERFLOW_JOB_RESULT
        )

        assert len(page_results) == 1
        assert page_results[0].url == "file:///fixture.html"
        assert page_results[0].browser_channel == "chrome"
        assert page_results[0].platform == "windows"
        assert page_results[0].browser_version == "151.0.7922.137"
        assert page_results[0].status == "fail"
        assert page_results[0].http_status == 200

    def test_creates_one_viewport_result_per_viewport(self, db_session: Session) -> None:
        execution_id = _seed_execution(db_session)

        page_results = ingest_browser_uat_tier0_job_result(
            db_session, execution_id=execution_id, job_result=OVERFLOW_JOB_RESULT
        )

        viewport_results = (
            db_session.execute(
                select(BrowserUatTier0ViewportResult).where(
                    BrowserUatTier0ViewportResult.page_result_id == page_results[0].id
                )
            )
            .scalars()
            .all()
        )
        assert len(viewport_results) == 2
        names = {result.viewport_name for result in viewport_results}
        assert names == {"Desktop", "Mobile"}
        for result in viewport_results:
            assert result.horizontal_overflow is True
            assert "horizontal scrolling" in result.viewport_problems[0]

    def test_clean_result_has_no_problems_and_status_passed(self, db_session: Session) -> None:
        execution_id = _seed_execution(db_session)

        ingest_browser_uat_tier0_job_result(
            db_session, execution_id=execution_id, job_result=CLEAN_JOB_RESULT
        )

        viewport_results = db_session.execute(select(BrowserUatTier0ViewportResult)).scalars().all()
        assert len(viewport_results) == 2
        for result in viewport_results:
            assert result.status == "passed"
            assert result.horizontal_overflow is False
            assert result.responsive_navigation is True
            assert result.viewport_problems == []


class TestMultipleJobsPerExecution:
    def test_different_browser_channel_platform_pairs_do_not_collide(
        self, db_session: Session
    ) -> None:
        # One execution, two of the workflow's three real jobs.
        execution_id = _seed_execution(db_session)

        ingest_browser_uat_tier0_job_result(
            db_session, execution_id=execution_id, job_result=OVERFLOW_JOB_RESULT
        )
        ingest_browser_uat_tier0_job_result(
            db_session, execution_id=execution_id, job_result=CLEAN_JOB_RESULT
        )

        page_results = (
            db_session.execute(
                select(BrowserUatTier0PageResult).where(
                    BrowserUatTier0PageResult.execution_id == execution_id
                )
            )
            .scalars()
            .all()
        )
        assert len(page_results) == 2
        channels = {(result.browser_channel, result.platform) for result in page_results}
        assert channels == {("chrome", "windows"), ("msedge", "windows")}


class TestIdempotentReingestion:
    def test_reingesting_the_same_job_updates_in_place_without_duplicating(
        self, db_session: Session
    ) -> None:
        execution_id = _seed_execution(db_session)

        ingest_browser_uat_tier0_job_result(
            db_session, execution_id=execution_id, job_result=OVERFLOW_JOB_RESULT
        )
        ingest_browser_uat_tier0_job_result(
            db_session, execution_id=execution_id, job_result=OVERFLOW_JOB_RESULT
        )

        page_results = db_session.execute(select(BrowserUatTier0PageResult)).scalars().all()
        assert len(page_results) == 1

        viewport_results = db_session.execute(select(BrowserUatTier0ViewportResult)).scalars().all()
        assert len(viewport_results) == 2  # not 4

    def test_reingesting_with_updated_data_replaces_stale_findings(
        self, db_session: Session
    ) -> None:
        # A page that failed on the first check and passes on a re-check
        # (e.g. after a fix) must reflect the LATEST result, not accumulate
        # stale rows alongside fresh ones.
        execution_id = _seed_execution(db_session)
        ingest_browser_uat_tier0_job_result(
            db_session, execution_id=execution_id, job_result=OVERFLOW_JOB_RESULT
        )

        fixed_result = {
            **OVERFLOW_JOB_RESULT,
            "overall_status": "pass",
            "pages": [
                {**OVERFLOW_JOB_RESULT["pages"][0], "status": "pass", "viewport_results": []}
            ],
        }
        ingest_browser_uat_tier0_job_result(
            db_session, execution_id=execution_id, job_result=fixed_result
        )

        page_results = db_session.execute(select(BrowserUatTier0PageResult)).scalars().all()
        assert len(page_results) == 1
        assert page_results[0].status == "pass"
        viewport_results = db_session.execute(select(BrowserUatTier0ViewportResult)).scalars().all()
        assert viewport_results == []


class TestCascadeDelete:
    def test_deleting_the_execution_removes_page_and_viewport_results(
        self, db_session: Session
    ) -> None:
        execution_id = _seed_execution(db_session)
        ingest_browser_uat_tier0_job_result(
            db_session, execution_id=execution_id, job_result=OVERFLOW_JOB_RESULT
        )

        execution = db_session.get(BrowserUatTier0Execution, execution_id)
        db_session.delete(execution)
        db_session.commit()

        assert db_session.execute(select(BrowserUatTier0PageResult)).scalars().all() == []
        assert db_session.execute(select(BrowserUatTier0ViewportResult)).scalars().all() == []
