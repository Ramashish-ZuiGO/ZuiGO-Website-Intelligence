"""Production network boundary.

PostgreSQL and Redis must be reachable only on the internal Compose network.
Publishing either to the host exposes the canonical datastore and the Celery
broker (which doubles as a control surface) to anything that can reach the host.
"""

from pathlib import Path

import pytest
import yaml

COMPOSE = yaml.safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))
SERVICES = COMPOSE["services"]
INTERNAL_ONLY_SERVICES = ("postgres", "redis")


def _published_ports(service_name: str) -> list:
    return SERVICES[service_name].get("ports") or []


@pytest.mark.parametrize("service_name", INTERNAL_ONLY_SERVICES)
def test_datastore_services_are_not_published_to_the_host(service_name: str) -> None:
    assert _published_ports(service_name) == [], (
        f"{service_name} must not publish ports; containers reach it over the "
        "internal Compose network."
    )


@pytest.mark.parametrize("service_name", INTERNAL_ONLY_SERVICES)
def test_datastore_services_are_not_host_networked(service_name: str) -> None:
    # host networking would bypass the ports check entirely.
    assert SERVICES[service_name].get("network_mode") != "host"


def test_api_and_worker_reach_dependencies_by_service_name(service_name: str = "api") -> None:
    environment = SERVICES[service_name]["environment"]
    postgres_host = environment["POSTGRES_HOST"]

    assert "postgres" in postgres_host
    assert "localhost" not in postgres_host and "127.0.0.1" not in postgres_host


def test_only_the_api_is_publicly_reachable() -> None:
    publishing = {name for name in SERVICES if _published_ports(name)}

    assert publishing == {"api"}, (
        "Only the API may be published. Redis/Celery control surfaces and the "
        "database must never be exposed."
    )


def test_redis_is_not_started_with_a_public_bind_override() -> None:
    command = str(SERVICES["redis"].get("command", ""))

    assert "--bind 0.0.0.0" not in command
    assert "--protected-mode no" not in command
