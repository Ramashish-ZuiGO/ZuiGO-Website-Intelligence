"""Stage execution exclusivity.

Invariant: for one (execution_id, attempt, stage) at most one active delivery
may perform side effects. Celery task ids do not guarantee this — a broker
redelivery of a still-running acks_late stage produced two concurrent
executions of the identical stage in production.

These tests drive the real guard against a real database so the claim, the
attempt scoping and the duplicate refusal are exercised end to end.
"""

import uuid
from datetime import UTC, datetime

import app.models  # noqa: F401 - registers every table on Base.metadata
import pytest
from app.db.base import Base
from celery.exceptions import Ignore
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from worker_app.tasks import real_analysis

BROWSER_STAGE = "browser_compatibility"


@pytest.fixture
def execution_db(monkeypatch: pytest.MonkeyPatch):
    """In-memory database shared by the guard under test."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(real_analysis, "SessionLocal", session_factory)
    return session_factory


def _seed_execution(session_factory, *, attempt: int = 1, status: str = "running") -> str:
    from app.models import AgentExecution, Project

    execution_id = uuid.uuid4()
    project_id = uuid.uuid4()
    with session_factory() as db:
        db.add(Project(id=project_id, name="Ownership Fixture"))
        db.add(
            AgentExecution(
                id=uuid.uuid4(),
                execution_id=execution_id,
                workflow_id="real-analysis",
                workflow_version="1.0.0",
                project_id=project_id,
                input_fingerprint="f" * 64,
                idempotency_key=f"key-{execution_id}",
                status=status,
                attempt=attempt,
                structured_input={"discovery_run_id": str(uuid.uuid4())},
                structured_output={},
                started_at=datetime.now(UTC),
            )
        )
        db.commit()
    return str(execution_id)


def _ownership(session_factory, execution_id: str) -> dict:
    from app.models import AgentExecution

    with session_factory() as db:
        execution = db.scalar(
            select(AgentExecution).where(AgentExecution.execution_id == uuid.UUID(execution_id))
        )
        return dict(execution.structured_output.get(real_analysis.STAGE_OWNERSHIP_KEY, {}))


class TestDuplicateDeliverySuppression:
    def test_second_delivery_of_same_execution_attempt_stage_is_refused(self, execution_db) -> None:
        execution_id = _seed_execution(execution_db)

        # Delivery A: the genuine first delivery acquires ownership.
        assert real_analysis._enter_stage(execution_id, BROWSER_STAGE) is None

        # Delivery B: identical execution, attempt and stage, arriving while A
        # is still running (A is not terminal).
        with pytest.raises(Ignore):
            real_analysis._enter_stage(execution_id, BROWSER_STAGE)

    def test_duplicate_leaves_ownership_and_progress_untouched(self, execution_db) -> None:
        execution_id = _seed_execution(execution_db)
        real_analysis._enter_stage(execution_id, BROWSER_STAGE)
        owner_before = _ownership(execution_db, execution_id)[BROWSER_STAGE]

        with pytest.raises(Ignore):
            real_analysis._enter_stage(execution_id, BROWSER_STAGE)

        owner_after = _ownership(execution_db, execution_id)[BROWSER_STAGE]
        # The duplicate must not steal ownership or rewrite the claim.
        assert owner_after == owner_before

    def test_duplicate_stage_task_performs_no_browser_work(
        self, execution_db, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        execution_id = _seed_execution(execution_db)
        real_analysis._enter_stage(execution_id, BROWSER_STAGE)

        def blocked(*_args, **_kwargs):
            raise AssertionError("duplicate delivery performed browser work")

        monkeypatch.setattr(real_analysis, "collect_real_browser_compatibility", blocked)
        monkeypatch.setattr(real_analysis, "_update_journey_stage", blocked)

        # Ignore propagates out of the task body, so Celery acks the message
        # without dispatching the chain continuation.
        with pytest.raises(Ignore):
            real_analysis.run_real_browser_stage.run(str(uuid.uuid4()), execution_id)

    def test_duplicate_records_no_fabricated_stage_completion(self, execution_db) -> None:
        from app.models import AgentExecution

        execution_id = _seed_execution(execution_db)
        real_analysis._enter_stage(execution_id, BROWSER_STAGE)
        with pytest.raises(Ignore):
            real_analysis._enter_stage(execution_id, BROWSER_STAGE)

        with execution_db() as db:
            execution = db.scalar(
                select(AgentExecution).where(AgentExecution.execution_id == uuid.UUID(execution_id))
            )
            output = execution.structured_output
            assert BROWSER_STAGE not in output.get("completed_stage_ids", [])
            assert execution.status == "running"


class TestAttemptIsolation:
    def test_later_attempt_is_never_blocked_by_an_earlier_attempts_claim(
        self, execution_db
    ) -> None:
        from app.models import AgentExecution

        execution_id = _seed_execution(execution_db, attempt=1)
        assert real_analysis._enter_stage(execution_id, BROWSER_STAGE) is None

        # Attempt 1's worker dies holding ownership; the execution goes stale
        # and is resumed, which is the only thing that releases the claim.
        with execution_db() as db:
            execution = db.scalar(
                select(AgentExecution).where(AgentExecution.execution_id == uuid.UUID(execution_id))
            )
            execution.attempt = 2
            db.commit()

        assert real_analysis._enter_stage(execution_id, BROWSER_STAGE) is None
        assert _ownership(execution_db, execution_id)[BROWSER_STAGE]["attempt"] == 2

    def test_duplicate_within_the_new_attempt_is_still_refused(self, execution_db) -> None:
        from app.models import AgentExecution

        execution_id = _seed_execution(execution_db, attempt=1)
        real_analysis._enter_stage(execution_id, BROWSER_STAGE)
        with execution_db() as db:
            execution = db.scalar(
                select(AgentExecution).where(AgentExecution.execution_id == uuid.UUID(execution_id))
            )
            execution.attempt = 2
            db.commit()

        real_analysis._enter_stage(execution_id, BROWSER_STAGE)
        with pytest.raises(Ignore):
            real_analysis._enter_stage(execution_id, BROWSER_STAGE)

    def test_a_stale_attempt_one_redelivery_cannot_take_over_concurrently(
        self, execution_db
    ) -> None:
        # Correctness over speed: a redelivery arriving while attempt 1 still
        # owns the stage is refused rather than allowed to take over. Recovery
        # is the product's stale -> resume path, which bumps the attempt.
        execution_id = _seed_execution(execution_db, attempt=1)
        real_analysis._enter_stage(execution_id, BROWSER_STAGE)

        with pytest.raises(Ignore):
            real_analysis._enter_stage(execution_id, BROWSER_STAGE)


class TestGuardAppliesToEveryStage:
    @pytest.mark.parametrize(
        "stage",
        [
            "website_discovery",
            "page_analysis",
            "primary_page_analysis",
            "browser_compatibility",
            "multi_agent_analysis",
        ],
    )
    def test_every_real_analysis_stage_is_exclusive(self, execution_db, stage: str) -> None:
        execution_id = _seed_execution(execution_db)

        assert real_analysis._enter_stage(execution_id, stage) is None
        with pytest.raises(Ignore):
            real_analysis._enter_stage(execution_id, stage)

    def test_stages_are_independent_of_each_other(self, execution_db) -> None:
        execution_id = _seed_execution(execution_db)

        # Owning one stage must not block a different stage of the same attempt.
        assert real_analysis._enter_stage(execution_id, "website_discovery") is None
        assert real_analysis._enter_stage(execution_id, "page_analysis") is None

    def test_no_stage_entry_point_bypasses_the_guard(self) -> None:
        from pathlib import Path

        source = Path("apps/worker/worker_app/tasks/real_analysis.py").read_text(encoding="utf-8")
        # Every stage task must enter through the shared guard, with no
        # per-stage or per-URL special casing.
        assert source.count("_enter_stage(workflow_execution_id") == 5
        assert "_skip_terminal_stage(workflow_execution_id" not in source


class TestTerminalExecutionsStillSkip:
    def test_terminal_execution_skips_without_claiming_ownership(self, execution_db) -> None:
        execution_id = _seed_execution(execution_db, status="cancelled")

        result = real_analysis._enter_stage(execution_id, BROWSER_STAGE)

        assert result == {"status": "cancelled", "stage": BROWSER_STAGE, "skipped": True}
        assert _ownership(execution_db, execution_id) == {}


class TestCoordinationAuthority:
    def test_ownership_is_claimed_under_a_row_lock_in_postgres(self) -> None:
        from pathlib import Path

        source = Path("apps/worker/worker_app/tasks/real_analysis.py").read_text(encoding="utf-8")
        claim = source[source.index("def _claim_stage(") : source.index("def _enter_stage(")]
        # Postgres, not Redis, is the coordination authority: concurrent
        # claimants serialise on the execution row.
        assert "with_for_update()" in claim

    def test_exclusivity_does_not_depend_on_the_broker(self) -> None:
        from pathlib import Path

        source = Path("apps/worker/worker_app/tasks/real_analysis.py").read_text(encoding="utf-8")
        claim = source[source.index("def _claim_stage(") : source.index("def _enter_stage(")]
        for broker_symbol in ("redis", "celery_app.control", "visibility_timeout"):
            assert broker_symbol not in claim
