"""One-click Android Tier 0 check (scripts/run_manual_tier0_android_check.py).

Same testing approach as tests/test_ingest_manual_tier0_result.py -- scripts/
isn't on pythonpath and the module imports app.db.session.SessionLocal
directly, so these tests add scripts/ to sys.path and monkeypatch that
binding to an in-memory SQLite engine. subprocess.run and
ingest_manual_tier0_result are also monkeypatched so these tests never spawn
a real Node process or touch a real device -- they only prove the
orchestration logic (URL lookup, env vars passed to the check step, and
that a failed check never gets ingested).
"""

import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.db.base import Base
from app.models import AnalysisRun, Project, Website
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

SCRIPTS_DIR = str(Path(__file__).resolve().parents[1] / "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import run_manual_tier0_android_check as cli  # noqa: E402


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


def _seed_analysis_run(
    db: Session, *, url: str = "https://manual-android-fixture.test/"
) -> uuid.UUID:
    project = Project(name="OneClickAndroidTest")
    db.add(project)
    db.flush()
    website = Website(project_id=project.id, url=url)
    db.add(website)
    db.flush()
    analysis_run = AnalysisRun(website_id=website.id, status="completed", progress_percent=100)
    db.add(analysis_run)
    db.commit()
    return analysis_run.id


class TestResolveTargetUrl:
    def test_returns_the_websites_real_url(self, db_session: Session) -> None:
        analysis_run_id = _seed_analysis_run(db_session, url="https://fluidcontrols.test/")

        assert cli._resolve_target_url(analysis_run_id) == "https://fluidcontrols.test/"

    def test_unknown_analysis_run_raises(self, db_session: Session) -> None:
        with pytest.raises(ValueError, match="does not exist"):
            cli._resolve_target_url(uuid.uuid4())


class TestMainOrchestration:
    def test_a_successful_check_gets_ingested_with_the_right_arguments(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        analysis_run_id = _seed_analysis_run(db_session, url="https://fluidcontrols.test/")

        # Simulate the Node check script succeeding by writing a real results
        # file at whatever RESULTS_PATH the wrapper computed, exactly like
        # the real subprocess would.
        subprocess_calls = []

        def fake_run(command, *, env, check):
            subprocess_calls.append((command, env))
            results_path = Path(env["RESULTS_PATH"])
            results_path.write_text(
                '{"channel": "chrome", "platform": "android", "browser_version": "151.0", '
                '"overall_status": "pass", "pages": []}',
                encoding="utf-8",
            )
            return SimpleNamespace(returncode=0)

        monkeypatch.setattr(cli.subprocess, "run", fake_run)
        monkeypatch.setattr(cli, "SCRIPT_DIR", tmp_path)
        monkeypatch.setattr(
            cli, "ANDROID_CHECK_SCRIPT", tmp_path / "browser_uat_tier0_check_android.mjs"
        )

        ingest_calls = []

        def fake_ingest(*, analysis_run_id, job_result, idempotency_key):
            ingest_calls.append((analysis_run_id, job_result, idempotency_key))
            return uuid.uuid4()

        monkeypatch.setattr(cli, "ingest_manual_tier0_result", fake_ingest)
        monkeypatch.setattr(
            sys,
            "argv",
            ["run_manual_tier0_android_check.py", "--analysis-run-id", str(analysis_run_id)],
        )

        exit_code = cli.main()

        assert exit_code == 0
        assert len(subprocess_calls) == 1
        _command, env = subprocess_calls[0]
        assert env["TARGET_PAGES"] == '["https://fluidcontrols.test/"]'
        assert len(ingest_calls) == 1
        assert ingest_calls[0][0] == analysis_run_id
        assert ingest_calls[0][1]["overall_status"] == "pass"

    def test_a_failed_check_is_never_ingested(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        analysis_run_id = _seed_analysis_run(db_session)

        def fake_run(command, *, env, check):
            return SimpleNamespace(returncode=1)

        monkeypatch.setattr(cli.subprocess, "run", fake_run)
        monkeypatch.setattr(cli, "SCRIPT_DIR", tmp_path)
        monkeypatch.setattr(
            cli, "ANDROID_CHECK_SCRIPT", tmp_path / "browser_uat_tier0_check_android.mjs"
        )

        ingest_calls = []
        monkeypatch.setattr(
            cli,
            "ingest_manual_tier0_result",
            lambda **kwargs: ingest_calls.append(kwargs) or uuid.uuid4(),
        )
        monkeypatch.setattr(
            sys,
            "argv",
            ["run_manual_tier0_android_check.py", "--analysis-run-id", str(analysis_run_id)],
        )

        exit_code = cli.main()

        assert exit_code == 1
        assert ingest_calls == []

    def test_device_serial_is_passed_through_when_given(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        analysis_run_id = _seed_analysis_run(db_session)
        subprocess_calls = []

        def fake_run(command, *, env, check):
            subprocess_calls.append(env)
            results_path = Path(env["RESULTS_PATH"])
            results_path.write_text(
                '{"channel": "chrome", "platform": "android", "browser_version": "151.0", '
                '"overall_status": "pass", "pages": []}',
                encoding="utf-8",
            )
            return SimpleNamespace(returncode=0)

        monkeypatch.setattr(cli.subprocess, "run", fake_run)
        monkeypatch.setattr(cli, "SCRIPT_DIR", tmp_path)
        monkeypatch.setattr(
            cli, "ANDROID_CHECK_SCRIPT", tmp_path / "browser_uat_tier0_check_android.mjs"
        )
        monkeypatch.setattr(cli, "ingest_manual_tier0_result", lambda **kwargs: uuid.uuid4())
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "run_manual_tier0_android_check.py",
                "--analysis-run-id",
                str(analysis_run_id),
                "--android-device-serial",
                "emulator-5554",
            ],
        )

        cli.main()

        assert subprocess_calls[0]["ANDROID_DEVICE_SERIAL"] == "emulator-5554"

    def test_no_device_serial_means_the_env_var_is_absent(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        analysis_run_id = _seed_analysis_run(db_session)
        subprocess_calls = []

        def fake_run(command, *, env, check):
            subprocess_calls.append(env)
            results_path = Path(env["RESULTS_PATH"])
            results_path.write_text(
                '{"channel": "chrome", "platform": "android", "browser_version": "151.0", '
                '"overall_status": "pass", "pages": []}',
                encoding="utf-8",
            )
            return SimpleNamespace(returncode=0)

        monkeypatch.setattr(cli.subprocess, "run", fake_run)
        monkeypatch.setattr(cli, "SCRIPT_DIR", tmp_path)
        monkeypatch.setattr(
            cli, "ANDROID_CHECK_SCRIPT", tmp_path / "browser_uat_tier0_check_android.mjs"
        )
        monkeypatch.setattr(cli, "ingest_manual_tier0_result", lambda **kwargs: uuid.uuid4())
        monkeypatch.setattr(
            sys,
            "argv",
            ["run_manual_tier0_android_check.py", "--analysis-run-id", str(analysis_run_id)],
        )

        cli.main()

        assert "ANDROID_DEVICE_SERIAL" not in subprocess_calls[0]
