from urllib.parse import unquote

import pytest
from app.config import AppEnvironment, LogLevel, Settings
from pydantic import ValidationError
from sqlalchemy.engine import make_url


def test_valid_settings_load() -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        log_level="DEBUG",
        postgres_user="website user",
        postgres_password="not-a-secret",
        postgres_db="website intelligence",
        postgres_host="database",
        postgres_port=5433,
        redis_url="redis://cache:6379/1",
    )

    database_url = make_url(settings.database_url)

    assert settings.app_env is AppEnvironment.TEST
    assert settings.log_level is LogLevel.DEBUG
    assert database_url.drivername == "postgresql+psycopg"
    assert database_url.username == "website user"
    assert unquote(database_url.database or "") == "website intelligence"
    assert settings.cors_origins == ["http://localhost:3000"]


def test_missing_required_settings_raise_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("POSTGRES_PASSWORD")
    monkeypatch.delenv("REDIS_URL")

    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None)

    missing_fields = {item["loc"] for item in error.value.errors()}
    assert missing_fields == {("postgres_password",), ("redis_url",)}


def test_settings_parse_multiple_cors_origins() -> None:
    settings = Settings(
        _env_file=None,
        postgres_password="not-a-secret",
        redis_url="redis://cache:6379/0",
        backend_cors_origins="http://localhost:3000, https://example.com/",
    )

    assert settings.cors_origins == ["http://localhost:3000", "https://example.com"]
