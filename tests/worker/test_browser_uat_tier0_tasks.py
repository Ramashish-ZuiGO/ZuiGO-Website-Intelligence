"""M2 Tier 0 desktop lane: dispatch/poll/finalize orchestration.

Drives the real task functions against an in-memory database with a fake
dispatch client -- no network calls, deterministic.
"""

import uuid

import app.models  # noqa: F401 - registers every table on Base.metadata
import pytest
from app.db.base import Base
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from worker_app.integrations.browser_uat_tier0_dispatch import (
    DispatchUnavailableError,
    FakeTier0DispatchClient,
    Tier0PollResult,
)
from worker_app.tasks import browser_uat_tier0


@pytest.fixture
def db_session_factory(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(browser_uat_tier0, "SessionLocal", session_factory)
    return session_factory


def _seed(session_factory, *, status: str = "pending") -> tuple[str, str]:
    """Seed a website + analysis run + browser_uat_tier0 execution.
    Returns (execution_id, target_url)."""
    from app.models import AnalysisRun, BrowserUatTier0Execution, Project, Website

    website_id = uuid.uuid4()
    analysis_run_id = uuid.uuid4()
    execution_id = uuid.uuid4()
    project_id = uuid.uuid4()
    target_url = "https://example-customer-site.test/"

    with session_factory() as db:
        db.add(Project(id=project_id, name="Tier0 Fixture"))
        db.add(
            Website(
                id=website_id,
                project_id=project_id,
                url=target_url,
            )
        )
        db.add(
            AnalysisRun(
                id=analysis_run_id,
                website_id=website_id,
                status="completed",
                progress_percent=100,
            )
        )
        db.add(
            BrowserUatTier0Execution(
                execution_id=execution_id,
                website_id=website_id,
                analysis_run_id=analysis_run_id,
                lane="github_actions_chrome_edge",
                idempotency_key="key-1",
                correlation_id=f"tier0-{execution_id.hex[:8]}",
                status=status,
            )
        )
        db.commit()
    return str(execution_id), target_url


class TestDispatch:
    def test_dispatch_moves_pending_to_running_and_schedules_a_poll(
        self, db_session_factory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.models import BrowserUatTier0Execution

        execution_id, target_url = _seed(db_session_factory)
        fake_client = FakeTier0DispatchClient()
        monkeypatch.setattr(browser_uat_tier0, "_build_dispatch_client", lambda: fake_client)

        scheduled = []
        monkeypatch.setattr(
            browser_uat_tier0.poll_browser_uat_tier0,
            "apply_async",
            lambda args, countdown: scheduled.append((args, countdown)),
        )

        result = browser_uat_tier0.dispatch_browser_uat_tier0.run(execution_id)

        assert result == {"status": "dispatched"}
        assert fake_client.dispatched == [
            {
                "correlation_id": f"tier0-{execution_id.replace('-', '')[:8]}",
                "target_url": target_url,
                "pages": [target_url],
            }
        ]
        assert scheduled == [([execution_id], browser_uat_tier0.POLL_INTERVAL_SECONDS)]

        with db_session_factory() as db:
            execution = db.scalar(
                select(BrowserUatTier0Execution).where(
                    BrowserUatTier0Execution.execution_id == uuid.UUID(execution_id)
                )
            )
            assert execution.status == "running"
            assert execution.started_at is not None

    def test_dispatch_is_idempotent_against_redelivery(
        self, db_session_factory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A duplicate delivery of the SAME dispatch task must not re-trigger
        # a second GitHub Actions run for one execution.
        execution_id, _ = _seed(db_session_factory, status="running")
        fake_client = FakeTier0DispatchClient()
        monkeypatch.setattr(browser_uat_tier0, "_build_dispatch_client", lambda: fake_client)

        result = browser_uat_tier0.dispatch_browser_uat_tier0.run(execution_id)

        assert result == {"status": "running", "skipped": True}
        assert fake_client.dispatched == []

    def test_dispatch_unavailable_client_marks_execution_unavailable(
        self, db_session_factory, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        from app.models import BrowserUatTier0Execution

        execution_id, _ = _seed(db_session_factory)

        def explode():
            raise DispatchUnavailableError("GITHUB_ACTIONS_TOKEN is not configured.")

        monkeypatch.setattr(browser_uat_tier0, "_build_dispatch_client", explode)

        with caplog.at_level("WARNING", logger="worker_app.tasks.browser_uat_tier0"):
            result = browser_uat_tier0.dispatch_browser_uat_tier0.run(execution_id)

        assert result == {"status": "unavailable"}
        with db_session_factory() as db:
            execution = db.scalar(
                select(BrowserUatTier0Execution).where(
                    BrowserUatTier0Execution.execution_id == uuid.UUID(execution_id)
                )
            )
            assert execution.status == "unavailable"
            assert "not configured" in execution.structured_output["reason"]

        # M7: a genuine failure must produce a traceable log line, not just a
        # silent DB write -- an operator watching worker logs sees this
        # without needing to query the database first.
        assert "browser_uat_tier0_dispatch_unavailable" in caplog.text
        assert execution_id in caplog.text


class TestPoll:
    def test_poll_unavailable_client_marks_execution_unavailable_and_logs(
        self, db_session_factory, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Pre-existing gap closed by M7's traceability audit: this branch
        # (the dispatch client itself becomes unavailable mid-poll, e.g. the
        # GitHub token is revoked between dispatch and a later poll attempt)
        # had no test coverage at all before this.
        from app.models import BrowserUatTier0Execution

        execution_id, _ = _seed(db_session_factory, status="running")

        def explode():
            raise DispatchUnavailableError("GITHUB_ACTIONS_TOKEN is not configured.")

        monkeypatch.setattr(browser_uat_tier0, "_build_dispatch_client", explode)

        with caplog.at_level("WARNING", logger="worker_app.tasks.browser_uat_tier0"):
            result = browser_uat_tier0.poll_browser_uat_tier0.run(execution_id, 3)

        assert result == {"status": "unavailable"}
        with db_session_factory() as db:
            execution = db.scalar(
                select(BrowserUatTier0Execution).where(
                    BrowserUatTier0Execution.execution_id == uuid.UUID(execution_id)
                )
            )
            assert execution.status == "unavailable"
        assert "browser_uat_tier0_poll_unavailable" in caplog.text
        assert execution_id in caplog.text

    def test_poll_reschedules_itself_while_running(
        self, db_session_factory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        execution_id, _ = _seed(db_session_factory, status="running")
        fake_client = FakeTier0DispatchClient()
        fake_client.poll_sequence[f"tier0-{execution_id.replace('-', '')[:8]}"] = [
            Tier0PollResult(status="queued"),
        ]
        monkeypatch.setattr(browser_uat_tier0, "_build_dispatch_client", lambda: fake_client)

        scheduled = []
        monkeypatch.setattr(
            browser_uat_tier0.poll_browser_uat_tier0,
            "apply_async",
            lambda args, countdown: scheduled.append((args, countdown)),
        )

        result = browser_uat_tier0.poll_browser_uat_tier0.run(execution_id, 1)

        assert result == {"status": "running", "attempt": 1}
        assert scheduled == [([execution_id, 2], browser_uat_tier0.POLL_INTERVAL_SECONDS)]

    def test_poll_finalizes_as_completed_on_success_and_ingests_the_real_results(
        self, db_session_factory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Artifact-fetch wiring: a completed run's parsed results must
        # actually flow into the M4 BrowserUatTier0PageResult table, not
        # just get logged/dropped -- this is the whole point of wiring
        # GitHubActionsTier0DispatchClient's artifact fetch into this task.
        from app.models import BrowserUatTier0Execution, BrowserUatTier0PageResult

        execution_id, target_url = _seed(db_session_factory, status="running")
        correlation_id = f"tier0-{execution_id.replace('-', '')[:8]}"
        fake_client = FakeTier0DispatchClient()
        fake_client.poll_sequence[correlation_id] = [
            Tier0PollResult(
                status="completed",
                conclusion="success",
                provider_run_reference="123456",
                results=[
                    {
                        "channel": "chrome",
                        "platform": "windows",
                        "browser_version": "151.0.7922.137",
                        "overall_status": "pass",
                        "pages": [
                            {
                                "url": target_url,
                                "status": "pass",
                                "http_status": 200,
                                "console_error_count": 0,
                                "viewport_results": [],
                            }
                        ],
                    },
                    {
                        "channel": "msedge",
                        "platform": "windows",
                        "browser_version": "151.0.7922.137",
                        "overall_status": "pass",
                        "pages": [
                            {
                                "url": target_url,
                                "status": "pass",
                                "http_status": 200,
                                "console_error_count": 0,
                                "viewport_results": [],
                            }
                        ],
                    },
                ],
            ),
        ]
        monkeypatch.setattr(browser_uat_tier0, "_build_dispatch_client", lambda: fake_client)

        result = browser_uat_tier0.poll_browser_uat_tier0.run(execution_id, 1)

        assert result == {"status": "completed", "artifact_count": 2}
        with db_session_factory() as db:
            execution = db.scalar(
                select(BrowserUatTier0Execution).where(
                    BrowserUatTier0Execution.execution_id == uuid.UUID(execution_id)
                )
            )
            assert execution.status == "completed"
            assert execution.provider_run_reference == "123456"
            # Lightweight summary only -- the real evidence lives in the M4
            # tables checked below, not duplicated into structured_output.
            assert execution.structured_output == {"artifact_count": 2}
            assert execution.completed_at is not None

            page_results = (
                db.query(BrowserUatTier0PageResult)
                .filter(BrowserUatTier0PageResult.execution_id == execution.id)
                .all()
            )
            assert len(page_results) == 2
            channels = {page_result.browser_channel for page_result in page_results}
            assert channels == {"chrome", "msedge"}

    def test_poll_finalizes_as_partial_on_failed_conclusion(
        self, db_session_factory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.models import BrowserUatTier0Execution

        execution_id, target_url = _seed(db_session_factory, status="running")
        correlation_id = f"tier0-{execution_id.replace('-', '')[:8]}"
        fake_client = FakeTier0DispatchClient()
        fake_client.poll_sequence[correlation_id] = [
            Tier0PollResult(
                status="completed",
                conclusion="failure",
                results=[
                    {
                        "channel": "chrome",
                        "platform": "windows",
                        "browser_version": "151.0.7922.137",
                        "overall_status": "fail",
                        "pages": [
                            {
                                "url": target_url,
                                "status": "fail",
                                "http_status": 500,
                                "console_error_count": 0,
                                "viewport_results": [],
                            }
                        ],
                    },
                ],
            ),
        ]
        monkeypatch.setattr(browser_uat_tier0, "_build_dispatch_client", lambda: fake_client)

        result = browser_uat_tier0.poll_browser_uat_tier0.run(execution_id, 1)

        assert result == {"status": "partial", "artifact_count": 1}
        with db_session_factory() as db:
            execution = db.scalar(
                select(BrowserUatTier0Execution).where(
                    BrowserUatTier0Execution.execution_id == uuid.UUID(execution_id)
                )
            )
            assert execution.status == "partial"

    def test_poll_finalizes_as_completed_with_zero_artifacts_when_none_were_produced(
        self, db_session_factory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A run can complete successfully with no artifacts at all (e.g.
        # every job's upload step was somehow skipped) -- must not crash on
        # an empty results list, just finalize honestly.
        from app.models import BrowserUatTier0Execution

        execution_id, _ = _seed(db_session_factory, status="running")
        correlation_id = f"tier0-{execution_id.replace('-', '')[:8]}"
        fake_client = FakeTier0DispatchClient()
        fake_client.poll_sequence[correlation_id] = [
            Tier0PollResult(status="completed", conclusion="success", results=[]),
        ]
        monkeypatch.setattr(browser_uat_tier0, "_build_dispatch_client", lambda: fake_client)

        result = browser_uat_tier0.poll_browser_uat_tier0.run(execution_id, 1)

        assert result == {"status": "completed", "artifact_count": 0}
        with db_session_factory() as db:
            execution = db.scalar(
                select(BrowserUatTier0Execution).where(
                    BrowserUatTier0Execution.execution_id == uuid.UUID(execution_id)
                )
            )
            assert execution.status == "completed"
            assert execution.structured_output == {"artifact_count": 0}

    def test_poll_stops_and_marks_unavailable_past_the_attempt_ceiling(
        self, db_session_factory, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        from app.models import BrowserUatTier0Execution

        execution_id, _ = _seed(db_session_factory, status="running")

        def explode():  # pragma: no cover - must not be reached
            raise AssertionError("must not poll past the attempt ceiling")

        monkeypatch.setattr(browser_uat_tier0, "_build_dispatch_client", explode)

        with caplog.at_level("WARNING", logger="worker_app.tasks.browser_uat_tier0"):
            result = browser_uat_tier0.poll_browser_uat_tier0.run(
                execution_id, browser_uat_tier0.MAX_POLL_ATTEMPTS + 1
            )

        assert result == {"status": "unavailable", "reason": "timeout"}
        with db_session_factory() as db:
            execution = db.scalar(
                select(BrowserUatTier0Execution).where(
                    BrowserUatTier0Execution.execution_id == uuid.UUID(execution_id)
                )
            )
            assert execution.status == "unavailable"

        # M7: a stuck/never-completing run must be traceable in worker logs,
        # not just silently marked unavailable in the database.
        assert "browser_uat_tier0_poll_timeout" in caplog.text
        assert execution_id in caplog.text

    def test_poll_on_a_terminal_execution_is_a_safe_no_op(
        self, db_session_factory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        execution_id, _ = _seed(db_session_factory, status="completed")

        def explode():  # pragma: no cover - must not be reached
            raise AssertionError("must not poll a terminal execution")

        monkeypatch.setattr(browser_uat_tier0, "_build_dispatch_client", explode)

        result = browser_uat_tier0.poll_browser_uat_tier0.run(execution_id, 1)

        assert result == {"status": "completed", "skipped": True}


class TestBuildDispatchClient:
    """_build_dispatch_client itself -- every other test in this file
    monkeypatches it away entirely, so its own token-presence logic had no
    coverage until now."""

    def test_a_missing_token_raises_dispatch_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from types import SimpleNamespace

        fake_settings = SimpleNamespace(
            github_actions_token=None,
            github_actions_repo="owner/repo",
            github_actions_ref="main",
        )
        monkeypatch.setattr(browser_uat_tier0, "get_settings", lambda: fake_settings)

        from worker_app.integrations.browser_uat_tier0_dispatch import DispatchUnavailableError

        with pytest.raises(DispatchUnavailableError):
            browser_uat_tier0._build_dispatch_client()

    def test_an_empty_string_token_also_raises_dispatch_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Regression: docker-compose's ${VAR:-} substitution sets an unset
        # env var to an empty string inside the container, not "absent" --
        # and pydantic-settings parses that as SecretStr(''), not None, for
        # an Optional[SecretStr] field. A bare `is None` check would let
        # this through and hit GitHub with a blank Bearer token instead of
        # failing cleanly here.
        from types import SimpleNamespace

        from pydantic import SecretStr

        fake_settings = SimpleNamespace(
            github_actions_token=SecretStr(""),
            github_actions_repo="owner/repo",
            github_actions_ref="main",
        )
        monkeypatch.setattr(browser_uat_tier0, "get_settings", lambda: fake_settings)

        from worker_app.integrations.browser_uat_tier0_dispatch import DispatchUnavailableError

        with pytest.raises(DispatchUnavailableError):
            browser_uat_tier0._build_dispatch_client()

    def test_a_real_token_builds_a_real_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from types import SimpleNamespace

        from pydantic import SecretStr

        fake_settings = SimpleNamespace(
            github_actions_token=SecretStr("real-token-value"),
            github_actions_repo="owner/repo",
            github_actions_ref="main",
        )
        monkeypatch.setattr(browser_uat_tier0, "get_settings", lambda: fake_settings)

        from worker_app.integrations.browser_uat_tier0_dispatch import (
            GitHubActionsTier0DispatchClient,
        )

        client = browser_uat_tier0._build_dispatch_client()

        assert isinstance(client, GitHubActionsTier0DispatchClient)
        assert client.repo == "owner/repo"
        assert client.ref == "main"
        assert client.token == "real-token-value"
