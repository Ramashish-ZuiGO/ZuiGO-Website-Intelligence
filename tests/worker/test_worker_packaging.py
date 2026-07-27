import importlib
from pathlib import Path

from worker_app.celery_app import celery_app

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_worker_build_packages_shared_api_app() -> None:
    compose = (REPOSITORY_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    worker_block = compose.split("\n  worker:\n", maxsplit=1)[1].split("\nvolumes:", maxsplit=1)[0]
    dockerfile = (REPOSITORY_ROOT / "apps/worker/Dockerfile").read_text(encoding="utf-8")
    requirements = (REPOSITORY_ROOT / "apps/worker/requirements.txt").read_text(encoding="utf-8")

    assert "context: ." in worker_block
    assert "dockerfile: apps/worker/Dockerfile" in worker_block
    assert "PYTHONPATH=/app" in dockerfile
    assert "COPY apps/api/app ./app" in dockerfile
    assert "COPY apps/worker/worker_app ./worker_app" in dockerfile
    assert "httpx==0.28.1" in requirements


def test_worker_startup_modules_import_with_shared_app_services() -> None:
    imported_modules = [
        importlib.import_module(module_name) for module_name in celery_app.conf.include
    ]

    assert {module.__name__ for module in imported_modules} == set(celery_app.conf.include)
