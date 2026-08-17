"""M1 (docs/REPORT_QUALITY_INITIATIVE.md): the minimal shared-credential
auth gate. tests/conftest.py's autouse fixture bypasses auth for every
OTHER test file by default -- these tests specifically undo that bypass to
exercise the real mechanism end to end.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from app.config import get_settings
from app.db.base import Base
from app.db.session import get_db
from app.errors.exceptions import ApplicationError
from app.main import app
from app.services.auth import (
    JWT_ALGORITHM,
    TOKEN_SUBJECT,
    create_access_token,
    require_bearer_auth,
    verify_credentials,
)
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# Real bcrypt hash of "correct horse battery staple" -- test-only, never
# used anywhere real. Generated once via bcrypt.hashpw, pinned here so the
# test doesn't depend on bcrypt's own randomized-salt behavior at test time.
_TEST_PASSWORD = "correct horse battery staple"
_TEST_PASSWORD_HASH = "$2b$12$r0nu6RSqzlpFX6KdKHLvIOZ3zw9hVnth5QoQAqloy4qH1JChdG/KC"


@pytest.fixture
def auth_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("ADMIN_USERNAME", "test-admin")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", _TEST_PASSWORD_HASH)
    monkeypatch.setenv("JWT_SECRET_KEY", "test-jwt-secret-key-that-is-at-least-32-bytes-long")
    yield
    get_settings.cache_clear()


class TestVerifyCredentials:
    def test_correct_username_and_password_succeeds(self, auth_settings: None) -> None:
        assert verify_credentials("test-admin", _TEST_PASSWORD) is True

    def test_wrong_password_fails(self, auth_settings: None) -> None:
        assert verify_credentials("test-admin", "wrong-password") is False

    def test_wrong_username_fails(self, auth_settings: None) -> None:
        assert verify_credentials("someone-else", _TEST_PASSWORD) is False

    def test_both_wrong_fails(self, auth_settings: None) -> None:
        assert verify_credentials("someone-else", "wrong-password") is False


class TestAccessTokenRoundTrip:
    def test_a_freshly_created_token_decodes_to_the_expected_subject(
        self, auth_settings: None
    ) -> None:
        token, expires_at = create_access_token()

        payload = jwt.decode(
            token, "test-jwt-secret-key-that-is-at-least-32-bytes-long", algorithms=[JWT_ALGORITHM]
        )

        assert payload["sub"] == TOKEN_SUBJECT
        assert expires_at > datetime.now(UTC)

    def test_require_bearer_auth_accepts_a_real_token(self, auth_settings: None) -> None:
        token, _expires_at = create_access_token()

        subject = require_bearer_auth(authorization=f"Bearer {token}")

        assert subject == TOKEN_SUBJECT


class TestRequireBearerAuthRejections:
    def test_missing_header_is_rejected(self, auth_settings: None) -> None:
        with pytest.raises(ApplicationError) as error:
            require_bearer_auth(authorization=None)

        assert error.value.code == "AUTHENTICATION_REQUIRED"
        assert error.value.status_code == 401

    def test_malformed_header_without_bearer_prefix_is_rejected(self, auth_settings: None) -> None:
        with pytest.raises(ApplicationError) as error:
            require_bearer_auth(authorization="Basic dXNlcjpwYXNz")

        assert error.value.code == "AUTHENTICATION_REQUIRED"

    def test_tampered_token_is_rejected(self, auth_settings: None) -> None:
        token, _expires_at = create_access_token()

        with pytest.raises(ApplicationError) as error:
            require_bearer_auth(authorization=f"Bearer {token}tampered")

        assert error.value.code == "TOKEN_INVALID"

    def test_expired_token_is_rejected(self, auth_settings: None) -> None:
        settings = get_settings()
        expired_token = jwt.encode(
            {"sub": TOKEN_SUBJECT, "exp": datetime.now(UTC) - timedelta(hours=1)},
            settings.jwt_secret_key.get_secret_value(),
            algorithm=JWT_ALGORITHM,
        )

        with pytest.raises(ApplicationError) as error:
            require_bearer_auth(authorization=f"Bearer {expired_token}")

        assert error.value.code == "TOKEN_EXPIRED"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db() -> Iterator[Session]:
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    # Undo the global test-suite bypass (tests/conftest.py) -- these tests
    # specifically exercise the real auth mechanism end to end.
    app.dependency_overrides.pop(require_bearer_auth, None)

    get_settings.cache_clear()
    monkeypatch.setenv("ADMIN_USERNAME", "test-admin")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", _TEST_PASSWORD_HASH)
    monkeypatch.setenv("JWT_SECRET_KEY", "test-jwt-secret-key-that-is-at-least-32-bytes-long")

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.pop(get_db, None)
    get_settings.cache_clear()


class TestLoginRoute:
    def test_correct_credentials_return_a_usable_token(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "test-admin", "password": _TEST_PASSWORD},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["token_type"] == "bearer"
        assert body["access_token"]

        protected = client.get(
            "/api/v1/projects", headers={"Authorization": f"Bearer {body['access_token']}"}
        )
        assert protected.status_code == 200

    def test_wrong_password_is_rejected(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "test-admin", "password": "wrong"},
        )

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"

    def test_wrong_username_is_rejected(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "nobody", "password": _TEST_PASSWORD},
        )

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


class TestProtectedRoutesRequireAuth:
    def test_a_protected_route_without_a_token_is_rejected(self, client: TestClient) -> None:
        response = client.get("/api/v1/projects")

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"

    def test_a_protected_route_with_an_invalid_token_is_rejected(self, client: TestClient) -> None:
        response = client.get(
            "/api/v1/projects", headers={"Authorization": "Bearer not-a-real-token"}
        )

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "TOKEN_INVALID"

    def test_health_remains_unprotected(self, client: TestClient) -> None:
        response = client.get("/health")

        assert response.status_code == 200

    def test_login_itself_remains_unprotected(self, client: TestClient) -> None:
        # A wrong password still reaches the real login logic (401
        # INVALID_CREDENTIALS) rather than being rejected for lacking a
        # token first (401 AUTHENTICATION_REQUIRED) -- proves /auth/login
        # is genuinely outside the protected router, not just conveniently
        # passing because of a valid token.
        response = client.post(
            "/api/v1/auth/login", json={"username": "test-admin", "password": "wrong"}
        )

        assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"
