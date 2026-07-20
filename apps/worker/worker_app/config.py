from enum import StrEnum
from functools import lru_cache
from urllib.parse import quote

from pydantic import AnyHttpUrl, Field, RedisDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


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


class AIProviderName(StrEnum):
    DISABLED = "disabled"
    OLLAMA = "ollama"


class WorkerSettings(BaseSettings):
    app_env: AppEnvironment = AppEnvironment.DEVELOPMENT
    log_level: LogLevel = LogLevel.INFO
    redis_url: RedisDsn
    postgres_user: str = "website_intelligence"
    postgres_password: SecretStr
    postgres_db: str = "website_intelligence"
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    ai_provider: AIProviderName = AIProviderName.DISABLED
    ai_model: str = Field(default="not-configured", min_length=1, max_length=200)
    ai_base_url: AnyHttpUrl = "http://host.docker.internal:11434"
    ai_timeout_seconds: int = Field(default=120, ge=1, le=600)

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


@lru_cache
def get_settings() -> WorkerSettings:
    return WorkerSettings()
