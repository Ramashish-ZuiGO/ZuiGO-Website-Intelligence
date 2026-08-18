"""M1 (docs/REPORT_QUALITY_INITIATIVE.md): the one unprotected route that
issues the token every other route requires. Deliberately excluded from
app/api/router.py's protected v1_router -- see require_bearer_auth's
docstring in app/services/auth.py.
"""

import logging

from fastapi import APIRouter, status

from app.errors.exceptions import ApplicationError
from app.schemas.auth import LoginRequest, LoginResponse
from app.services.auth import create_access_token, verify_credentials

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest) -> LoginResponse:
    if not verify_credentials(payload.username, payload.password):
        # M11: failed attempts are security-relevant; the submitted username
        # is logged (single-admin system), the password never is.
        logger.warning("login_failed username=%s", payload.username)
        raise ApplicationError(
            code="INVALID_CREDENTIALS",
            message="Incorrect username or password.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    token, expires_at = create_access_token()
    logger.info("login_succeeded username=%s expires_at=%s", payload.username, expires_at)
    return LoginResponse(access_token=token, expires_at=expires_at)
