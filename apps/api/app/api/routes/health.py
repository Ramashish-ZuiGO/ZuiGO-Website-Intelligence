"""Liveness and readiness probes.

``/health`` answers "is this process alive?" and performs no dependency I/O, so
it stays cheap and cannot be made to fail by a degraded dependency.

``/ready`` answers the different and operationally decisive question: "can this
instance safely accept production work?". Only dependencies that are genuinely
required to accept an analysis request are probed:

* PostgreSQL — canonical state for every website, run, finding and artifact.
* Redis — Celery broker; without it no analysis can be queued at all.

The LLM provider is deliberately NOT probed: deterministic analysis without an
LLM is a supported product mode, so its absence must never fail readiness.

Responses are machine-readable and carry no exception text, credentials, host
names or other infrastructure detail.
"""

import logging
from typing import Literal

import redis
from fastapi import APIRouter, Response
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from app.config import get_settings

router = APIRouter()

logger = logging.getLogger("app.health")

DependencyState = Literal["available", "unavailable"]


def probe_connect_args(timeout_seconds: float) -> dict[str, object]:
    """Connect arguments that bound a readiness probe end to end."""
    return {
        "connect_timeout": max(1, int(timeout_seconds)),
        "options": f"-c statement_timeout={max(1, int(timeout_seconds * 1000))}",
    }


def _build_probe_engine():  # noqa: ANN202 - SQLAlchemy Engine
    """Dedicated, hard-bounded engine for readiness probes.

    Deliberately separate from the request pool: it never consumes a pooled
    connection, and both the connect and the query are bounded by the readiness
    timeout so ``/ready`` cannot become a slow or hanging endpoint. Opening a
    fresh connection is also the stronger signal -- it proves the instance can
    still acquire a database connection right now.
    """
    settings = get_settings()
    return create_engine(
        settings.database_url,
        poolclass=NullPool,
        connect_args=probe_connect_args(settings.readiness_timeout_seconds),
    )


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "healthy", "service": "api"}


def _probe_database() -> DependencyState:
    try:
        probe_engine = _build_probe_engine()
        try:
            with probe_engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        finally:
            probe_engine.dispose()
    except Exception as exception:
        # Detail is logged server-side only; the response stays generic.
        logger.warning(
            "readiness_dependency_unavailable dependency=database exception_type=%s",
            type(exception).__name__,
        )
        return "unavailable"
    return "available"


def _probe_redis(timeout_seconds: float) -> DependencyState:
    client = None
    try:
        client = redis.Redis.from_url(
            get_settings().redis_url,
            socket_connect_timeout=timeout_seconds,
            socket_timeout=timeout_seconds,
        )
        client.ping()
    except Exception as exception:
        logger.warning(
            "readiness_dependency_unavailable dependency=redis exception_type=%s",
            type(exception).__name__,
        )
        return "unavailable"
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:  # pragma: no cover - close is best effort
                pass
    return "available"


@router.get("/ready")
def ready(response: Response) -> dict[str, object]:
    timeout_seconds = get_settings().readiness_timeout_seconds
    dependencies: dict[str, DependencyState] = {
        "database": _probe_database(),
        "redis": _probe_redis(timeout_seconds),
    }
    is_ready = all(state == "available" for state in dependencies.values())
    if not is_ready:
        # Truthful non-200 so load balancers and deploy gates stop sending work
        # to an instance that cannot serve it.
        response.status_code = 503
    return {
        "status": "ready" if is_ready else "not_ready",
        "service": "api",
        "dependencies": dependencies,
    }
