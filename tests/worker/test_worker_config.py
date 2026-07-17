import pytest
from pydantic import ValidationError
from worker_app.celery_app import celery_app
from worker_app.config import AppEnvironment, LogLevel, WorkerSettings, get_settings


def test_worker_redis_configuration() -> None:
    settings = WorkerSettings(
        _env_file=None,
        app_env="test",
        log_level="WARNING",
        redis_url="redis://cache:6379/2",
    )

    assert settings.app_env is AppEnvironment.TEST
    assert settings.log_level is LogLevel.WARNING
    assert str(settings.redis_url) == "redis://cache:6379/2"
    configured_redis_url = str(get_settings().redis_url)
    assert celery_app.conf.broker_url == configured_redis_url
    assert celery_app.conf.result_backend == configured_redis_url


def test_worker_requires_redis_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REDIS_URL")

    with pytest.raises(ValidationError) as error:
        WorkerSettings(_env_file=None)

    assert {item["loc"] for item in error.value.errors()} == {("redis_url",)}
