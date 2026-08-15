"""Lane C manual ingestion CLI (scripts/ingest_manual_tier0_result.py).

scripts/ isn't on pythonpath (pyproject.toml only covers apps/api and
apps/worker) and the module imports app.db.session.SessionLocal directly
(no dependency-injection seam like the FastAPI app has) -- so these tests add
scripts/ to sys.path and monkeypatch the imported SessionLocal binding to
point at an in-memory SQLite engine, the same substitution the API's own
tests get for free via app.dependency_overrides[get_db].
"""

import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from app.db.base import Base
from app.models import (
    AnalysisRun,
    BrowserUatTier0Execution,
    BrowserUatTier0PageResult,
    Project,
    Website,
)
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

SCRIPTS_DIR = str(Path(__file__).resolve().parents[1] / "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import ingest_manual_tier0_result as cli  # noqa: E402

ANDROID_JOB_RESULT = {
    "channel": "chrome",
    "platform": "android",
    "browser_version": "151.0.7922.137",
    "overall_status": "pass",
    "pages": [
        {
            "url": "https://example.test/",
            "status": "pass",
            "http_status": None,
            "console_error_count": 0,
            "viewport_results": [
                {
                    "name": "Mobile (real device)",
                    "width": 412,
                    "height": 915,
                    "status": "passed",
                    "horizontal_overflow": False,
                    "critical_elements_outside_viewport": 0,
                    "overlapping_elements": 0,
                    "responsive_navigation": True,
                    "small_tap_targets": 0,
                    "tap_target_samples": [],
                    "viewport_problems": [],
                }
            ],
        }
    ],
}


@pytest.fixture
def db_session(monkeypatch: pytest.MonkeyPatch) -> Iterator[Session]:
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
    monkeypatch.setattr(cli, "SessionLocal", factory)
    with factory() as session:
        yield session


def _seed_analysis_run(db: Session) -> uuid.UUID:
    project = Project(name="Tier0ManualIngestTest")
    db.add(project)
    db.flush()
    website = Website(project_id=project.id, url="https://manual-android-fixture.test/")
    db.add(website)
    db.flush()
    analysis_run = AnalysisRun(website_id=website.id, status="completed", progress_percent=100)
    db.add(analysis_run)
    db.commit()
    return analysis_run.id


class TestIngestManualTier0Result:
    def test_creates_a_completed_execution_with_page_results(self, db_session: Session) -> None:
        analysis_run_id = _seed_analysis_run(db_session)

        execution_id = cli.ingest_manual_tier0_result(
            analysis_run_id=analysis_run_id,
            job_result=ANDROID_JOB_RESULT,
            idempotency_key="manual-android-test-1",
        )

        execution = (
            db_session.query(BrowserUatTier0Execution)
            .filter(BrowserUatTier0Execution.execution_id == execution_id)
            .one()
        )
        assert execution.status == "completed"
        assert execution.completed_at is not None
        assert execution.analysis_run_id == analysis_run_id

        page_results = (
            db_session.query(BrowserUatTier0PageResult)
            .filter(BrowserUatTier0PageResult.execution_id == execution.id)
            .all()
        )
        assert len(page_results) == 1
        assert page_results[0].browser_channel == "chrome"
        assert page_results[0].platform == "android"
        assert page_results[0].status == "pass"

    def test_a_failed_overall_status_finalizes_as_partial_not_failed(
        self, db_session: Session
    ) -> None:
        # Real per-page evidence WAS produced even when some pages fail --
        # mirrors worker_app/tasks/browser_uat_tier0.py's _finalize exactly
        # (COMPLETED only on full success, else PARTIAL, never FAILED here).
        analysis_run_id = _seed_analysis_run(db_session)
        failing_result = {**ANDROID_JOB_RESULT, "overall_status": "fail"}

        execution_id = cli.ingest_manual_tier0_result(
            analysis_run_id=analysis_run_id,
            job_result=failing_result,
            idempotency_key="manual-android-test-2",
        )

        execution = (
            db_session.query(BrowserUatTier0Execution)
            .filter(BrowserUatTier0Execution.execution_id == execution_id)
            .one()
        )
        assert execution.status == "partial"

    def test_replaying_the_same_idempotency_key_reuses_the_execution(
        self, db_session: Session
    ) -> None:
        analysis_run_id = _seed_analysis_run(db_session)

        first_id = cli.ingest_manual_tier0_result(
            analysis_run_id=analysis_run_id,
            job_result=ANDROID_JOB_RESULT,
            idempotency_key="manual-android-replay",
        )
        second_id = cli.ingest_manual_tier0_result(
            analysis_run_id=analysis_run_id,
            job_result=ANDROID_JOB_RESULT,
            idempotency_key="manual-android-replay",
        )

        assert first_id == second_id
        count = (
            db_session.query(BrowserUatTier0Execution)
            .filter(BrowserUatTier0Execution.analysis_run_id == analysis_run_id)
            .count()
        )
        assert count == 1

    def test_unknown_analysis_run_raises(self, db_session: Session) -> None:
        with pytest.raises(ValueError, match="does not exist"):
            cli.ingest_manual_tier0_result(
                analysis_run_id=uuid.uuid4(),
                job_result=ANDROID_JOB_RESULT,
                idempotency_key="manual-android-missing",
            )
