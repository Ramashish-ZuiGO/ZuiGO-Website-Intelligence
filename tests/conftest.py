"""Root-level fixtures shared by every test file.

M1 (docs/REPORT_QUALITY_INITIATIVE.md) added a bearer-token dependency to
every /api/v1 route except /auth/login. Rather than editing the ~20
existing test files that already build their own TestClient/dependency
overrides (one per file, following the app.dependency_overrides[get_db]
pattern), this autouse fixture bypasses auth by default for every test --
mirroring how a real caller would carry a valid token, without requiring
every unrelated test to know about auth at all.

A test that specifically exercises real auth behavior (login success/
failure, a protected route rejecting a missing/invalid/expired token) must
explicitly undo the bypass for itself: `app.dependency_overrides.pop(require_bearer_auth, None)`.
"""

import os

# This file is pytest's root conftest, so it is imported before any
# subdirectory conftest (tests/api, tests/worker) gets a chance to run its
# own os.environ setup -- `from app.main import app` below eagerly triggers
# app.db.session's module-level get_settings() call, so the required
# Settings fields must already be satisfied by the time this import
# executes. setdefault() only fills gaps: a real .env (local dev) or
# explicit CI env vars still win via pydantic-settings' normal precedence
# for anything already set in the process env.
os.environ.setdefault("POSTGRES_PASSWORD", "test_password")
os.environ.setdefault("REDIS_URL", "redis://redis:6379/0")
os.environ.setdefault("ADMIN_USERNAME", "test-admin")
os.environ.setdefault(
    "ADMIN_PASSWORD_HASH", "$2b$12$r0nu6RSqzlpFX6KdKHLvIOZ3zw9hVnth5QoQAqloy4qH1JChdG/KC"
)
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-that-is-at-least-32-bytes-long")

from collections.abc import Iterator

import pytest
from app.main import app
from app.services.auth import require_bearer_auth


@pytest.fixture(autouse=True)
def _bypass_auth_by_default() -> Iterator[None]:
    app.dependency_overrides[require_bearer_auth] = lambda: "test-bypass"
    yield
    app.dependency_overrides.pop(require_bearer_auth, None)
