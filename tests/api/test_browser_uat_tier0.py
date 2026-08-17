"""M2 Tier 0 desktop lane: API-side creation and route behavior.

The route enqueues a Celery task on success; enqueue_browser_uat_tier0 is
monkeypatched so these tests never require a live broker.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import app.api.routes.browser_uat_tier0 as browser_uat_tier0_route
import pytest
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import (
    AnalysisRun,
    BrowserUatTier0Execution,
    BrowserUatTier0PageResult,
    BrowserUatTier0ViewportResult,
    Project,
    Website,
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


@pytest.fixture
def client(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    def override() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = override

    enqueued: list[str] = []
    monkeypatch.setattr(
        browser_uat_tier0_route,
        "enqueue_browser_uat_tier0",
        lambda execution_id: enqueued.append(execution_id) or f"task-{execution_id}",
    )

    with TestClient(app) as test_client:
        test_client.enqueued = enqueued  # type: ignore[attr-defined]
        yield test_client
    app.dependency_overrides.clear()


def _seed_analysis_run(db: Session) -> uuid.UUID:
    project = Project(name="Tier0RouteTest")
    db.add(project)
    db.flush()
    website = Website(project_id=project.id, url="https://route-fixture.test/")
    db.add(website)
    db.flush()
    analysis_run = AnalysisRun(website_id=website.id, status="completed", progress_percent=100)
    db.add(analysis_run)
    db.commit()
    return analysis_run.id


class TestStartBrowserUatTier0Route:
    def test_creates_execution_and_enqueues_dispatch(
        self, client: TestClient, db_session: Session
    ) -> None:
        analysis_run_id = _seed_analysis_run(db_session)

        response = client.post(
            f"/api/v1/analysis-runs/{analysis_run_id}/browser-uat/tier0",
            json={"idempotency_key": "route-key-1"},
        )

        assert response.status_code == 202
        body = response.json()
        assert body["analysis_run_id"] == str(analysis_run_id)
        assert body["lane"] == "github_actions_chrome_edge"
        assert body["status"] == "pending"
        assert client.enqueued == [body["execution_id"]]  # type: ignore[attr-defined]

    def test_replaying_the_same_idempotency_key_does_not_duplicate_or_reenqueue(
        self, client: TestClient, db_session: Session
    ) -> None:
        analysis_run_id = _seed_analysis_run(db_session)
        payload = {"idempotency_key": "route-key-2"}

        first = client.post(
            f"/api/v1/analysis-runs/{analysis_run_id}/browser-uat/tier0", json=payload
        )
        second = client.post(
            f"/api/v1/analysis-runs/{analysis_run_id}/browser-uat/tier0", json=payload
        )

        assert first.status_code == 202
        assert second.status_code == 200
        assert first.json()["execution_id"] == second.json()["execution_id"]
        assert len(client.enqueued) == 1  # type: ignore[attr-defined]

        count = db_session.scalar(
            select(BrowserUatTier0Execution).where(
                BrowserUatTier0Execution.analysis_run_id == analysis_run_id
            )
        )
        assert count is not None

    def test_a_different_idempotency_key_creates_independent_history_once_the_first_finishes(
        self, client: TestClient, db_session: Session
    ) -> None:
        # M8 admission control (see TestAdmissionControl below) refuses a
        # second NEW request while one is still in flight for the same
        # website -- so this test proves different idempotency keys remain
        # independent (not deduplicated together) once the first is terminal,
        # rather than proving they can both be in flight simultaneously
        # (which is now the behavior explicitly under test elsewhere).
        analysis_run_id = _seed_analysis_run(db_session)

        first = client.post(
            f"/api/v1/analysis-runs/{analysis_run_id}/browser-uat/tier0",
            json={"idempotency_key": "route-key-3a"},
        )
        first_execution = db_session.scalar(
            select(BrowserUatTier0Execution).where(
                BrowserUatTier0Execution.execution_id == uuid.UUID(first.json()["execution_id"])
            )
        )
        first_execution.status = "completed"
        db_session.commit()

        second = client.post(
            f"/api/v1/analysis-runs/{analysis_run_id}/browser-uat/tier0",
            json={"idempotency_key": "route-key-3b"},
        )

        assert second.status_code == 202
        assert first.json()["execution_id"] != second.json()["execution_id"]
        assert len(client.enqueued) == 2  # type: ignore[attr-defined]

    def test_unknown_analysis_run_returns_404(self, client: TestClient) -> None:
        response = client.post(
            f"/api/v1/analysis-runs/{uuid.uuid4()}/browser-uat/tier0",
            json={"idempotency_key": "route-key-4"},
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "ANALYSIS_RUN_NOT_FOUND"

    def test_empty_idempotency_key_is_rejected(
        self, client: TestClient, db_session: Session
    ) -> None:
        analysis_run_id = _seed_analysis_run(db_session)

        response = client.post(
            f"/api/v1/analysis-runs/{analysis_run_id}/browser-uat/tier0",
            json={"idempotency_key": "   "},
        )

        assert response.status_code == 422


class TestAdmissionControl:
    """M8: at most one in-flight Tier 0 execution per website at a time --
    each execution dispatches 3 real GitHub Actions jobs, and nothing else
    in this pipeline bounds how many a website could accumulate."""

    def test_a_new_request_is_refused_while_one_is_in_flight_for_the_same_website(
        self, client: TestClient, db_session: Session
    ) -> None:
        analysis_run_id = _seed_analysis_run(db_session)
        first = client.post(
            f"/api/v1/analysis-runs/{analysis_run_id}/browser-uat/tier0",
            json={"idempotency_key": "admission-key-1"},
        )
        assert first.status_code == 202

        second = client.post(
            f"/api/v1/analysis-runs/{analysis_run_id}/browser-uat/tier0",
            json={"idempotency_key": "admission-key-2"},
        )

        assert second.status_code == 409
        body = second.json()
        assert body["error"]["code"] == "BROWSER_UAT_TIER0_ALREADY_IN_FLIGHT"
        assert body["error"]["details"]["in_flight_execution_id"] == first.json()["execution_id"]
        # Refused before dispatch -- no second Celery task enqueued.
        assert len(client.enqueued) == 1  # type: ignore[attr-defined]

    def test_a_different_website_is_never_blocked_by_another_websites_in_flight_check(
        self, client: TestClient, db_session: Session
    ) -> None:
        first_run_id = _seed_analysis_run(db_session)
        second_run_id = _seed_analysis_run(db_session)  # a distinct website

        first = client.post(
            f"/api/v1/analysis-runs/{first_run_id}/browser-uat/tier0",
            json={"idempotency_key": "admission-key-a"},
        )
        second = client.post(
            f"/api/v1/analysis-runs/{second_run_id}/browser-uat/tier0",
            json={"idempotency_key": "admission-key-b"},
        )

        assert first.status_code == 202
        assert second.status_code == 202

    def test_replaying_the_same_idempotency_key_still_succeeds_while_in_flight(
        self, client: TestClient, db_session: Session
    ) -> None:
        # Idempotent replay of the SAME request must not be treated as a new
        # in-flight conflict -- only a genuinely different request is refused.
        analysis_run_id = _seed_analysis_run(db_session)
        payload = {"idempotency_key": "admission-key-replay"}

        first = client.post(
            f"/api/v1/analysis-runs/{analysis_run_id}/browser-uat/tier0", json=payload
        )
        second = client.post(
            f"/api/v1/analysis-runs/{analysis_run_id}/browser-uat/tier0", json=payload
        )

        assert first.status_code == 202
        assert second.status_code == 200
        assert first.json()["execution_id"] == second.json()["execution_id"]

    def test_a_new_request_succeeds_once_the_in_flight_execution_is_terminal(
        self, client: TestClient, db_session: Session
    ) -> None:
        analysis_run_id = _seed_analysis_run(db_session)
        first = client.post(
            f"/api/v1/analysis-runs/{analysis_run_id}/browser-uat/tier0",
            json={"idempotency_key": "admission-key-terminal-1"},
        )
        execution = db_session.scalar(
            select(BrowserUatTier0Execution).where(
                BrowserUatTier0Execution.execution_id == uuid.UUID(first.json()["execution_id"])
            )
        )
        execution.status = "unavailable"
        db_session.commit()

        second = client.post(
            f"/api/v1/analysis-runs/{analysis_run_id}/browser-uat/tier0",
            json={"idempotency_key": "admission-key-terminal-2"},
        )

        assert second.status_code == 202


class TestGetBrowserUatTier0StatusRoute:
    """The read/poll side of the Tier 0 API -- built for the apps/web
    frontend handoff so a UI can show real-time status without reaching
    into the operator's machine (see
    docs/DEVICE_OS_BROWSER_QA_PLAN.md's frontend-handoff notes)."""

    def test_unknown_analysis_run_returns_404(self, client: TestClient) -> None:
        response = client.get(f"/api/v1/analysis-runs/{uuid.uuid4()}/browser-uat/tier0")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "ANALYSIS_RUN_NOT_FOUND"

    def test_a_real_analysis_run_with_no_check_ever_started_returns_404(
        self, client: TestClient, db_session: Session
    ) -> None:
        analysis_run_id = _seed_analysis_run(db_session)

        response = client.get(f"/api/v1/analysis-runs/{analysis_run_id}/browser-uat/tier0")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "BROWSER_UAT_TIER0_NOT_FOUND"

    def test_a_pending_execution_is_visible_for_polling(
        self, client: TestClient, db_session: Session
    ) -> None:
        # A frontend polling this route must see "pending"/"running" too --
        # not just terminal, evidence-bearing executions (that's a
        # different query, used by the Findings Register/M5 evidence
        # mapping, see fetch_latest_tier0_execution's own docstring).
        analysis_run_id = _seed_analysis_run(db_session)
        started = client.post(
            f"/api/v1/analysis-runs/{analysis_run_id}/browser-uat/tier0",
            json={"idempotency_key": "status-poll-key"},
        )
        assert started.json()["status"] == "pending"

        response = client.get(f"/api/v1/analysis-runs/{analysis_run_id}/browser-uat/tier0")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "pending"
        assert body["execution_id"] == started.json()["execution_id"]

    def test_returns_the_most_recently_requested_execution(
        self, client: TestClient, db_session: Session
    ) -> None:
        analysis_run_id = _seed_analysis_run(db_session)
        first = client.post(
            f"/api/v1/analysis-runs/{analysis_run_id}/browser-uat/tier0",
            json={"idempotency_key": "status-poll-key-a"},
        )
        first_execution = db_session.scalar(
            select(BrowserUatTier0Execution).where(
                BrowserUatTier0Execution.execution_id == uuid.UUID(first.json()["execution_id"])
            )
        )
        first_execution.status = "completed"
        db_session.commit()
        second = client.post(
            f"/api/v1/analysis-runs/{analysis_run_id}/browser-uat/tier0",
            json={"idempotency_key": "status-poll-key-b"},
        )

        response = client.get(f"/api/v1/analysis-runs/{analysis_run_id}/browser-uat/tier0")

        assert response.json()["execution_id"] == second.json()["execution_id"]


class TestGetBrowserUatTier0ResultsRoute:
    def test_unknown_analysis_run_returns_404(self, client: TestClient) -> None:
        response = client.get(f"/api/v1/analysis-runs/{uuid.uuid4()}/browser-uat/tier0/results")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "ANALYSIS_RUN_NOT_FOUND"

    def test_a_real_analysis_run_with_no_usable_evidence_yet_returns_an_empty_list_not_404(
        self, client: TestClient, db_session: Session
    ) -> None:
        # Distinct honest response from "analysis run doesn't exist" --
        # nothing to show yet is not the same as nothing valid to ask about.
        analysis_run_id = _seed_analysis_run(db_session)
        client.post(
            f"/api/v1/analysis-runs/{analysis_run_id}/browser-uat/tier0",
            json={"idempotency_key": "results-pending-key"},
        )  # still "pending" -- no usable (terminal) evidence yet

        response = client.get(f"/api/v1/analysis-runs/{analysis_run_id}/browser-uat/tier0/results")

        assert response.status_code == 200
        assert response.json() == {"page_results": []}

    def test_returns_real_structural_evidence_once_a_check_completes(
        self, client: TestClient, db_session: Session
    ) -> None:
        analysis_run_id = _seed_analysis_run(db_session)
        analysis_run = db_session.get(AnalysisRun, analysis_run_id)
        execution = BrowserUatTier0Execution(
            website_id=analysis_run.website_id,
            analysis_run_id=analysis_run_id,
            lane="github_actions_chrome_edge",
            idempotency_key="results-completed-key",
            correlation_id="results-completed-key",
            status="partial",
            completed_at=datetime.now(UTC),
        )
        db_session.add(execution)
        db_session.flush()
        page_result = BrowserUatTier0PageResult(
            execution_id=execution.id,
            browser_channel="chrome",
            platform="android",
            browser_version="151.0.7922.137",
            url="https://route-fixture.test/",
            status="fail",
        )
        db_session.add(page_result)
        db_session.flush()
        db_session.add(
            BrowserUatTier0ViewportResult(
                page_result_id=page_result.id,
                viewport_name="Mobile (real device)",
                viewport_width=360,
                viewport_height=690,
                status="failed",
                horizontal_overflow=True,
                small_tap_targets=5,
            )
        )
        db_session.commit()

        response = client.get(f"/api/v1/analysis-runs/{analysis_run_id}/browser-uat/tier0/results")

        assert response.status_code == 200
        body = response.json()
        assert len(body["page_results"]) == 1
        page = body["page_results"][0]
        assert page["url"] == "https://route-fixture.test/"
        assert page["status"] == "fail"
        assert page["browser_channel"] == "chrome"
        assert len(page["viewport_results"]) == 1
        assert page["viewport_results"][0]["horizontal_overflow"] is True
        assert page["viewport_results"][0]["small_tap_targets"] == 5
