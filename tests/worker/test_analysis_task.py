import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, func, insert, select
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
    yield factory
    worker_db.metadata.drop_all(engine)
    engine.dispose()


def insert_queued_run(factory: sessionmaker) -> uuid.UUID:
    run_id = uuid.uuid4()
    website_id = uuid.uuid4()
    now = datetime.now(UTC)
    with factory() as session:
        session.execute(
            insert(worker_db.websites).values(id=website_id, url="https://example.com/")
        )
        session.execute(
            insert(worker_db.analysis_runs).values(
                id=run_id,
                website_id=website_id,
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


def configure_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(analysis, "validate_public_url", lambda url: url)
    monkeypatch.setattr(analysis, "chromium_executable_path", lambda: "/chromium")
    monkeypatch.setattr(
        analysis,
        "inspect_page",
        lambda url, **kwargs: {
            "requested_url": url,
            "final_url": url,
            "http_status_code": 200,
            "page_title": "Example",
            "meta_description": "Example page",
            "canonical_url": url,
            "html_language": "en",
            "h1_count": 1,
            "h1_texts": ["Example"],
            "image_count": 0,
            "images_missing_alt": 0,
            "page_javascript_errors": [],
            "failed_network_requests": [],
            "https_usage": True,
            "user_agent": "test-agent",
        },
    )
    monkeypatch.setattr(
        analysis,
        "run_lighthouse",
        lambda url, chrome, timeout: {
            "lighthouseVersion": "13.3.0",
            "finalDisplayedUrl": url,
            "categories": {
                "performance": {"score": 0.9},
                "accessibility": {"score": 1.0},
                "best-practices": {"score": 1.0},
                "seo": {"score": 1.0},
            },
            "audits": {},
        },
    )


def test_successful_result_persistence_and_retry_is_idempotent(
    session_factory: sessionmaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = insert_queued_run(session_factory)
    configure_success(monkeypatch)

    first = analysis.run_analysis.run(str(run_id))
    second = analysis.run_analysis.run(str(run_id))
    stored = load_run(session_factory, run_id)
    with session_factory() as session:
        result_count = session.scalar(select(func.count()).select_from(worker_db.analysis_results))
        score_count = session.scalar(select(func.count()).select_from(worker_db.analysis_scores))
        interpretation_count = session.scalar(
            select(func.count()).select_from(worker_db.analysis_interpretations)
        )

    assert first["status"] == "completed"
    assert second["status"] == "completed"
    assert stored["progress_percent"] == 100
    assert result_count == 1
    assert score_count == 1
    assert interpretation_count == 1
    assert stored["status"] == "completed"


def test_worker_failure_stores_safe_failed_state(
    session_factory: sessionmaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = insert_queued_run(session_factory)
    monkeypatch.setattr(analysis, "validate_public_url", lambda url: url)
    monkeypatch.setattr(
        analysis,
        "inspect_page",
        lambda url: (_ for _ in ()).throw(RuntimeError("internal secret must not be stored")),
    )

    result = analysis.run_analysis.run(str(run_id))
    stored = load_run(session_factory, run_id)

    assert result["status"] == "failed"
    assert stored["status"] == "failed"
    assert stored["error_code"] == "INTERNAL_ANALYSIS_ERROR"
    assert stored["error_message"] == "The analysis could not be completed."
    assert "secret" not in str(stored["error_message"])


def test_unexpected_interpretation_failure_keeps_technical_audit_completed(
    session_factory: sessionmaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = insert_queued_run(session_factory)
    configure_success(monkeypatch)
    monkeypatch.setattr(
        analysis,
        "generate_interpretation",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("provider secret")),
    )

    result = analysis.run_analysis.run(str(run_id))
    stored = load_run(session_factory, run_id)
    with session_factory() as session:
        interpretation_count = session.scalar(
            select(func.count()).select_from(worker_db.analysis_interpretations)
        )

    assert result["status"] == "completed"
    assert stored["status"] == "completed"
    assert interpretation_count == 0


def test_transient_retry_succeeds_once(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = 0

    def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise analysis.AnalysisFailure(
                analysis.FailureDetail("NAVIGATION_TIMEOUT", "Timed out.", "loading_website", True)
            )
        return "ok"

    monkeypatch.setattr(analysis.time, "sleep", lambda seconds: None)
    result, attempt = analysis.run_with_retries(
        operation,
        max_attempts=2,
        backoff_seconds=1,
        context={"analysis_run_id": "run", "project_id": "project", "website_id": "website"},
    )
    assert result == "ok"
    assert attempt == 2


def test_retry_limit_is_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(analysis.time, "sleep", lambda seconds: None)

    def operation() -> None:
        raise analysis.AnalysisFailure(
            analysis.FailureDetail("BROWSER_LAUNCH_FAILED", "Failed.", "preparing_browser", True)
        )

    with pytest.raises(analysis.AnalysisFailure) as error:
        analysis.run_with_retries(
            operation,
            max_attempts=2,
            backoff_seconds=1,
            context={"analysis_run_id": "run", "project_id": "project", "website_id": "website"},
        )
    assert error.value.detail.attempt == 2


def test_progress_is_monotonic(session_factory: sessionmaker) -> None:
    run_id = insert_queued_run(session_factory)
    with session_factory() as session:
        analysis.stage(session, run_id, 40, "running_lighthouse")
        analysis.stage(session, run_id, 20, "loading_website")
    stored = load_run(session_factory, run_id)
    assert stored["progress_percent"] == 40
