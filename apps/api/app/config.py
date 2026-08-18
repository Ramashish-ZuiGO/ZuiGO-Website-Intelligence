import json
from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Any
from urllib.parse import quote

from pydantic import AnyHttpUrl, Field, SecretStr, TypeAdapter, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

http_url_adapter = TypeAdapter(AnyHttpUrl)


class AppEnvironment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class Settings(BaseSettings):
    app_env: AppEnvironment = AppEnvironment.DEVELOPMENT
    log_level: LogLevel = LogLevel.INFO
    postgres_user: str = "website_intelligence"
    postgres_password: SecretStr
    postgres_db: str = "website_intelligence"
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    redis_url: str
    backend_cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]
    allowed_repository_roots: list[str] = ["C:\\Users", "/home", "/app"]

    # M1 (docs/REPORT_QUALITY_INITIATIVE.md): a single shared admin
    # credential, not a user table -- this is a minimal gate for
    # internal-only usage today, not the full multi-tenant/RBAC system the
    # product spec describes as a later phase. The password is never stored
    # in plaintext; only its bcrypt hash lives in config.
    admin_username: str
    admin_password_hash: SecretStr
    jwt_secret_key: SecretStr
    jwt_expiry_hours: int = Field(default=24, ge=1, le=168)

    # Readiness probing. Bounded so /ready can never become a slow or hanging
    # endpoint when a dependency is degraded.
    readiness_timeout_seconds: float = Field(default=3.0, ge=0.1, le=15.0)
    # Without an explicit connect timeout, a request that needs a new pooled
    # connection while Postgres is unreachable blocks indefinitely.
    db_connect_timeout_seconds: int = Field(default=10, ge=1, le=60)
    # Pool sizing is environment-configurable rather than hard-coded; the
    # defaults reproduce SQLAlchemy's own defaults so behaviour is unchanged
    # unless an operator opts into different sizing.
    db_pool_size: int = Field(default=5, ge=1, le=100)
    db_max_overflow: int = Field(default=10, ge=0, le=100)
    # -1 disables recycling (SQLAlchemy default); pool_pre_ping already guards
    # against stale connections.
    db_pool_recycle_seconds: int = Field(default=-1, ge=-1, le=86_400)

    # M2 (docs/REPORT_QUALITY_INITIATIVE.md): abuse protection. In-memory,
    # per-process counters -- correct for this deployment's single uvicorn
    # worker process (no --workers flag); would need a shared store (Redis is
    # already a dependency) if the API ever scales to multiple processes.
    # Upper bound is high enough to let the test suite set an effectively
    # unlimited value (tests/conftest.py) without tripping across its
    # thousands of requests through the shared app singleton.
    rate_limit_general_per_minute: int = Field(default=120, ge=1, le=10_000_000)
    # Applies specifically to endpoints that trigger a real, expensive
    # Playwright/Lighthouse analysis run (each can take up to an hour) --
    # much stricter than the general limit.
    rate_limit_expensive_per_minute: int = Field(default=5, ge=1, le=10_000_000)
    max_request_body_bytes: int = Field(default=5_000_000, ge=1_024, le=100_000_000)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def database_url(self) -> str:
        user = quote(self.postgres_user, safe="")
        password = quote(self.postgres_password.get_secret_value(), safe="")
        database = quote(self.postgres_db, safe="")
        return (
            f"postgresql+psycopg://{user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{database}"
        )

    # Performance Intelligence
    crux_api_key: str | None = None
    crux_timeout_seconds: float = 10.0

    @field_validator("backend_cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: Any) -> list[str]:
        if isinstance(value, str):
            stripped_value = value.strip()
            if stripped_value.startswith("["):
                value = json.loads(stripped_value)
            else:
                value = stripped_value.split(",")

        if not isinstance(value, list):
            raise ValueError("BACKEND_CORS_ORIGINS must be a comma-separated or JSON list")

        origins = [str(origin).strip().rstrip("/") for origin in value if str(origin).strip()]
        if not origins:
            raise ValueError("BACKEND_CORS_ORIGINS must contain at least one origin")

        for origin in origins:
            parsed_origin = http_url_adapter.validate_python(origin)
            if parsed_origin.path not in ("", "/") or parsed_origin.query or parsed_origin.fragment:
                raise ValueError("CORS origins must not contain paths, queries, or fragments")

        return origins

    @property
    def cors_origins(self) -> list[str]:
        return self.backend_cors_origins


@lru_cache
def get_settings() -> Settings:
    return Settings()
