"""M1 (docs/REPORT_QUALITY_INITIATIVE.md): a minimal shared-credential auth
gate for internal-only usage today -- deliberately NOT the full
multi-tenant/RBAC system docs/PRODUCT_MASTER_SPEC.md describes as a later
phase (user's explicit scope decision: "minimal gate now, full system
later"). One admin username/password (bcrypt-hashed, configured via
ADMIN_USERNAME/ADMIN_PASSWORD_HASH), issuing short-lived signed JWTs. No
user table, no session table -- stateless verification, matching the
project's "keep it simple" principle for this first pass.
"""

import hmac
from datetime import UTC, datetime, timedelta
from typing import Annotated

import bcrypt
import jwt
from fastapi import Header

from app.config import get_settings
from app.errors.exceptions import ApplicationError

JWT_ALGORITHM = "HS256"
TOKEN_SUBJECT = "admin"


def verify_credentials(username: str, password: str) -> bool:
    """Both comparisons run unconditionally (never short-circuited) so a
    wrong username can't be distinguished from a wrong password by
    response timing -- a login endpoint is a natural target for that."""
    settings = get_settings()
    username_matches = hmac.compare_digest(username, settings.admin_username)
    password_matches = bcrypt.checkpw(
        password.encode("utf-8"),
        settings.admin_password_hash.get_secret_value().encode("utf-8"),
    )
    return username_matches and password_matches


def create_access_token() -> tuple[str, datetime]:
    settings = get_settings()
    expires_at = datetime.now(UTC) + timedelta(hours=settings.jwt_expiry_hours)
    token = jwt.encode(
        {"sub": TOKEN_SUBJECT, "exp": expires_at},
        settings.jwt_secret_key.get_secret_value(),
        algorithm=JWT_ALGORITHM,
    )
    return token, expires_at


def _decode_access_token(token: str) -> dict[str, object]:
    settings = get_settings()
    try:
        return jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[JWT_ALGORITHM],
        )
    except jwt.ExpiredSignatureError as exc:
        raise ApplicationError(
            code="TOKEN_EXPIRED",
            message="Session has expired. Please log in again.",
            status_code=401,
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise ApplicationError(
            code="TOKEN_INVALID",
            message="Invalid authentication token.",
            status_code=401,
        ) from exc


def require_bearer_auth(authorization: Annotated[str | None, Header()] = None) -> str:
    """FastAPI dependency guarding every protected route. Applied once at
    the router level (app/api/router.py) rather than per-route, so a newly
    added route can never accidentally ship unprotected.
    """
    if authorization is None or not authorization.startswith("Bearer "):
        raise ApplicationError(
            code="AUTHENTICATION_REQUIRED",
            message="Missing or malformed Authorization header.",
            status_code=401,
        )
    token = authorization.removeprefix("Bearer ").strip()
    payload = _decode_access_token(token)
    return str(payload.get("sub", ""))
