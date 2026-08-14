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
    # Max simultaneously executing analysis stages on this worker host. Stages
    # run as a chain (one active task per run), so this caps concurrent
    # browser-heavy analyses. Raise only on a dedicated worker host.
    celery_worker_concurrency: int = Field(default=2, ge=1, le=32)
    # Redis redelivers any message left unacknowledged for this long. Analysis
    # stages are acks_late, so they ack only on completion: if a stage runs
    # longer than this, the broker redelivers it WHILE IT IS STILL RUNNING and
    # a second worker slot executes the same stage concurrently. The floor of
    # 3600 is the Celery default and must never be lowered -- this value has to
    # stay above the longest possible stage runtime, not below it.
    celery_broker_visibility_timeout_seconds: int = Field(default=21_600, ge=3_600, le=86_400)
    ai_provider: AIProviderName = AIProviderName.DISABLED
    ai_model: str = Field(default="not-configured", min_length=1, max_length=200)
    ai_base_url: AnyHttpUrl = "http://host.docker.internal:11434"
    ai_timeout_seconds: int = Field(default=120, ge=1, le=600)
    browser_launch_timeout_ms: int = Field(default=20_000, ge=1_000, le=120_000)
    navigation_timeout_ms: int = Field(default=45_000, ge=1_000, le=180_000)
    dom_readiness_timeout_ms: int = Field(default=15_000, ge=1_000, le=60_000)
    page_stabilization_ms: int = Field(default=2_000, ge=0, le=10_000)
    evidence_collection_timeout_ms: int = Field(default=20_000, ge=1_000, le=120_000)
    lighthouse_timeout_seconds: int = Field(default=120, ge=10, le=300)
    analysis_job_timeout_seconds: int = Field(default=300, ge=60, le=900)
    analysis_max_attempts: int = Field(default=2, ge=1, le=3)
    analysis_retry_backoff_seconds: float = Field(default=1.0, ge=0, le=10)
    w3c_validation_enabled: bool = True
    w3c_validation_endpoint: AnyHttpUrl = "https://validator.w3.org/nu/?out=json"
    w3c_timeout_seconds: int = Field(default=20, ge=1, le=60)
    policy_page_timeout_seconds: int = Field(default=15, ge=1, le=60)
    diagnostic_max_resources: int = Field(default=20, ge=1, le=100)
    diagnostic_evidence_limit: int = Field(default=20, ge=1, le=100)
    discovery_max_urls: int = Field(default=50_000, ge=1, le=100_000)
    discovery_max_html_pages: int = Field(default=10_000, ge=1, le=50_000)
    # Emergency safety bound against pathologically deep / self-generating URL
    # spaces only. Normal finite sites finish by frontier exhaustion well before
    # this, so it must never be the routine stop condition.
    discovery_max_depth: int = Field(default=1_000, ge=0, le=10_000)
    discovery_max_query_variants_per_path: int = Field(default=200, ge=1, le=10_000)
    discovery_max_links_per_page: int = Field(default=500, ge=1, le=5000)
    discovery_max_sitemap_files: int = Field(default=50, ge=1, le=200)
    discovery_max_sitemap_depth: int = Field(default=5, ge=0, le=10)
    discovery_max_redirects: int = Field(default=5, ge=0, le=10)
    discovery_request_timeout_seconds: int = Field(default=15, ge=1, le=60)
    discovery_deadline_seconds: int = Field(default=1800, ge=10, le=3600)
    discovery_max_response_bytes: int = Field(default=2_000_000, ge=10_000, le=10_000_000)
    discovery_include_verified_subdomains: bool = False
    discovery_max_fetch_attempts: int = Field(default=3, ge=1, le=5)
    discovery_retry_backoff_seconds: float = Field(default=0.25, ge=0, le=5)
    page_analysis_max_level_1: int = Field(default=10_000, ge=1, le=50_000)
    page_analysis_max_level_2: int = Field(default=10, ge=0, le=50)
    page_analysis_per_page_timeout_seconds: int = Field(default=15, ge=5, le=60)
    page_analysis_total_timeout_seconds: int = Field(default=900, ge=60, le=3600)
    responsive_viewports: str = (
        "mobile_portrait:390x844,mobile_landscape:844x390,tablet:768x1024,"
        "laptop:1366x768,desktop:1920x1080"
    )

    @property
    def parsed_responsive_viewports(self) -> list[tuple[str, int, int]]:
        results = []
        for item in self.responsive_viewports.split(","):
            name, dimensions = item.split(":", 1)
            width, height = dimensions.lower().split("x", 1)
            results.append((name, int(width), int(height)))
        return results

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
