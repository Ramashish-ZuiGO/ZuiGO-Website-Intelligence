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

from collections.abc import Iterator

import pytest
from app.main import app
from app.services.auth import require_bearer_auth


@pytest.fixture(autouse=True)
def _bypass_auth_by_default() -> Iterator[None]:
    app.dependency_overrides[require_bearer_auth] = lambda: "test-bypass"
    yield
    app.dependency_overrides.pop(require_bearer_auth, None)
