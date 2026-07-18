import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, insert, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from worker_app import db as worker_db
from worker_app.tasks import analysis


@pytest.fixture
def session_factory(monkeypatch: pytest.MonkeyPatch) -> Iterator[sessionmaker]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    worker_db.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(analysis, "SessionLocal", factory)
    monkeypatch.setattr(analysis.time, "sleep", lambda _: None)
    yield factory
    worker_db.metadata.drop_all(engine)
    engine.dispose()


def insert_queued_run(factory: sessionmaker) -> uuid.UUID:
    run_id = uuid.uuid4()
    now = datetime.now(UTC)
    with factory() as session:
        session.execute(
            insert(worker_db.analysis_runs).values(
                id=run_id,
                website_id=uuid.uuid4(),
                status="queued",
                progress_percent=0,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()
    return run_id


def load_run(factory: sessionmaker, run_id: uuid.UUID) -> dict[str, object]:
    with factory() as session:
        row = (
            session.execute(
                select(worker_db.analysis_runs).where(worker_db.analysis_runs.c.id == run_id)
            )
            .mappings()
            .one()
        )
        return dict(row)


def test_worker_transitions_queued_to_completed(session_factory: sessionmaker) -> None:
    run_id = insert_queued_run(session_factory)

    result = analysis.run_analysis.run(str(run_id))
    stored = load_run(session_factory, run_id)

    assert result["status"] == "completed"
    assert stored["status"] == "completed"
    assert stored["progress_percent"] == 100
    assert stored["started_at"] is not None
    assert stored["completed_at"] is not None
    assert stored["current_step"] == "Analysis lifecycle completed"


def test_worker_failure_stores_safe_failed_state(
    session_factory: sessionmaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = insert_queued_run(session_factory)

    def fail_lifecycle(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("internal secret must not be stored")

    monkeypatch.setattr(analysis, "advance_lifecycle", fail_lifecycle)

    result = analysis.run_analysis.run(str(run_id))
    stored = load_run(session_factory, run_id)

    assert result["status"] == "failed"
    assert stored["status"] == "failed"
    assert stored["error_code"] == "ANALYSIS_TASK_FAILED"
    assert stored["error_message"] == "Analysis lifecycle task failed."
    assert "secret" not in str(stored["error_message"])
