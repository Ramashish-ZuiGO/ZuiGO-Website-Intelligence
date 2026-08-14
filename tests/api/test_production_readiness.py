"""Production readiness contract.

Covers the liveness/readiness split, truthful dependency reporting, bounded and
non-leaking probe responses, and the operational Celery settings that govern
planned-restart safety and browser-heavy admission control.
"""

import app.api.routes.health as health_module
import pytest
from app.config import Settings, get_settings
from app.main import app
from fastapi.testclient import TestClient
from worker_app.celery_app import celery_app
from worker_app.config import WorkerSettings

client = TestClient(app)


class _StubRedis:
    def __init__(self, *, fails: bool) -> None:
        self.fails = fails
        self.closed = False

    def ping(self) -> bool:
        if self.fails:
            raise ConnectionError("redis://secret-host:6379 refused the connection")
        return True

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def stub_dependencies(monkeypatch: pytest.MonkeyPatch):
    """Control both readiness dependencies without real infrastructure."""
    state = {"database_ok": True, "redis_ok": True, "redis_client": None}

    def fake_probe_database() -> str:
        return "available" if state["database_ok"] else "unavailable"

    def fake_from_url(*_args: object, **_kwargs: object) -> _StubRedis:
        stub = _StubRedis(fails=not state["redis_ok"])
        state["redis_client"] = stub
        return stub

    monkeypatch.setattr(health_module, "_probe_database", fake_probe_database)
    monkeypatch.setattr(health_module.redis.Redis, "from_url", staticmethod(fake_from_url))
    return state


class TestLivenessVersusReadiness:
    def test_health_is_pure_liveness_and_never_touches_dependencies(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def explode() -> str:  # pragma: no cover - must never be called
            raise AssertionError("/health must not perform dependency I/O")

        monkeypatch.setattr(health_module, "_probe_database", explode)
        response = client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "healthy", "service": "api"}

    def test_ready_reports_ready_when_all_required_dependencies_are_usable(
        self, stub_dependencies: dict
    ) -> None:
        response = client.get("/ready")

        assert response.status_code == 200
        assert response.json() == {
            "status": "ready",
            "service": "api",
            "dependencies": {"database": "available", "redis": "available"},
        }

    def test_ready_is_false_when_database_is_unavailable(self, stub_dependencies: dict) -> None:
        stub_dependencies["database_ok"] = False
        response = client.get("/ready")

        assert response.status_code == 503
        payload = response.json()
        assert payload["status"] == "not_ready"
        assert payload["dependencies"]["database"] == "unavailable"

    def test_ready_is_false_when_redis_is_unavailable(self, stub_dependencies: dict) -> None:
        stub_dependencies["redis_ok"] = False
        response = client.get("/ready")

        assert response.status_code == 503
        payload = response.json()
        assert payload["status"] == "not_ready"
        assert payload["dependencies"]["redis"] == "unavailable"

    def test_ready_never_leaks_infrastructure_detail_or_credentials(
        self, stub_dependencies: dict
    ) -> None:
        stub_dependencies["redis_ok"] = False
        stub_dependencies["database_ok"] = False
        body = client.get("/ready").text

        for leak in (
            "secret-host",
            "6379",
            "password",
            "postgresql",
            "Traceback",
            "ConnectionError",
        ):
            assert leak not in body

    def test_ready_closes_its_redis_probe_connection(self, stub_dependencies: dict) -> None:
        client.get("/ready")

        assert stub_dependencies["redis_client"].closed is True

    def test_ready_honours_allowed_cors_origin(self, stub_dependencies: dict) -> None:
        response = client.get("/ready", headers={"Origin": "http://localhost:3000"})

        assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


class TestReadinessProbeIsBounded:
    def test_probe_bounds_both_connect_and_statement_time(self) -> None:
        timeout_seconds = get_settings().readiness_timeout_seconds
        connect_args = health_module.probe_connect_args(timeout_seconds)

        assert connect_args["connect_timeout"] <= max(1, int(timeout_seconds))
        assert f"statement_timeout={int(timeout_seconds * 1000)}" in connect_args["options"]

    def test_probe_engine_does_not_consume_the_request_pool(self) -> None:
        from sqlalchemy.pool import NullPool

        engine = health_module._build_probe_engine()
        try:
            assert isinstance(engine.pool, NullPool)
        finally:
            engine.dispose()

    def test_readiness_timeout_is_constrained_to_a_non_blocking_range(self) -> None:
        field = Settings.model_fields["readiness_timeout_seconds"]
        bounds = {type(item).__name__: item for item in field.metadata}

        assert field.default == 3.0
        assert bounds["Le"].le <= 15.0


class TestDatabaseConnectionManagement:
    def test_api_engine_bounds_connection_attempts(self) -> None:
        from app.db.session import CONNECT_ARGS

        assert CONNECT_ARGS["connect_timeout"] == get_settings().db_connect_timeout_seconds

    def test_api_engine_keeps_pre_ping_enabled(self) -> None:
        from app.db.session import engine

        assert engine.pool._pre_ping is True

    def test_pool_sizing_is_environment_configurable_with_unchanged_defaults(self) -> None:
        settings = get_settings()

        assert settings.db_pool_size == 5
        assert settings.db_max_overflow == 10
        assert settings.db_pool_recycle_seconds == -1


class TestWorkerOperationalSafety:
    def test_long_tasks_reserve_exactly_one_message_per_slot(self) -> None:
        # Prefetching acks_late browser stages strands them for the full broker
        # visibility timeout if the worker dies before starting them.
        assert celery_app.conf.worker_prefetch_multiplier == 1

    def test_acks_late_remains_enabled_on_analysis_stages(self) -> None:
        # Locked recovery semantics: redelivery after an interrupted stage is
        # what makes stale -> resume possible. Must never be weakened.
        stage_names = [
            "worker.run_real_discovery_stage",
            "worker.run_real_page_analysis_stage",
            "worker.run_real_primary_analysis_stage",
            "worker.run_real_browser_stage",
            "worker.run_real_agent_stage",
        ]
        import worker_app.tasks.real_analysis  # noqa: F401 - registers the tasks

        for name in stage_names:
            assert celery_app.tasks[name].acks_late is True, name

    def test_broker_visibility_timeout_exceeds_longest_stage_runtime(self) -> None:
        # Defence in depth ONLY: raising this reduces pointless redelivery of
        # still-running stages, but it does not and cannot guarantee exclusive
        # execution. Exclusivity is enforced by the stage-ownership claim in
        # tests/worker/test_stage_execution_ownership.py.
        transport_options = celery_app.conf.broker_transport_options or {}
        visibility_timeout = transport_options["visibility_timeout"]

        longest_stage_time_limit = max(
            task.time_limit
            for task in celery_app.tasks.values()
            if getattr(task, "time_limit", None)
        )
        assert visibility_timeout > longest_stage_time_limit
        assert visibility_timeout > 3_600

    def test_visibility_timeout_can_never_be_configured_below_the_celery_default(self) -> None:
        # Shortening it would force faster redelivery and duplicate live work.
        field = WorkerSettings.model_fields["celery_broker_visibility_timeout_seconds"]
        bounds = {type(item).__name__: item for item in field.metadata}

        assert bounds["Ge"].ge == 3_600

    def test_worker_retries_broker_connection_on_startup(self) -> None:
        assert celery_app.conf.broker_connection_retry_on_startup is True

    def test_browser_heavy_concurrency_is_capped_below_host_saturation(self) -> None:
        # Stages run as a chain (one active task per run), so worker concurrency
        # is the cap on concurrent analyses. Saturation is documented at ~4+.
        assert celery_app.conf.worker_concurrency < 4

    def test_worker_concurrency_is_environment_configurable(self) -> None:
        field = WorkerSettings.model_fields["celery_worker_concurrency"]
        assert field.default == 2
