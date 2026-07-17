import json
from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Any
from urllib.parse import quote

from pydantic import AnyHttpUrl, SecretStr, TypeAdapter, field_validator
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
