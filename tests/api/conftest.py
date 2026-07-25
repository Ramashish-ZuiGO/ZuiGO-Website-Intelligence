import os

os.environ["APP_ENV"] = "test"
os.environ["LOG_LEVEL"] = "INFO"
os.environ["POSTGRES_USER"] = "website_intelligence"
os.environ["POSTGRES_PASSWORD"] = "test_password"
os.environ["POSTGRES_DB"] = "website_intelligence"
os.environ["POSTGRES_HOST"] = "postgres"
os.environ["POSTGRES_PORT"] = "5432"
os.environ["REDIS_URL"] = "redis://redis:6379/0"
os.environ["BACKEND_CORS_ORIGINS"] = "http://localhost:3000"

import json
import tempfile

import pytest
from app.config import get_settings


@pytest.fixture(autouse=True, scope="session")
def setup_test_allowed_roots(tmp_path_factory: pytest.TempPathFactory) -> None:
    """Ensure test temporary directories are allowed as repository roots."""
    base_temp = str(tmp_path_factory.getbasetemp().parent)
    sys_temp = tempfile.gettempdir()

    current_roots = ["C:\\Users", "/home", "/app"]
    os.environ["ALLOWED_REPOSITORY_ROOTS"] = json.dumps(current_roots + [base_temp, sys_temp])
    get_settings.cache_clear()

    yield

    get_settings.cache_clear()
