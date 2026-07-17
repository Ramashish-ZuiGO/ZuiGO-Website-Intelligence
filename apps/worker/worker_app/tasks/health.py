import logging

from worker_app.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="worker.health_check")
def health_check() -> dict[str, str]:
    logger.info("health_check status=healthy")
    return {"status": "healthy", "service": "worker"}
