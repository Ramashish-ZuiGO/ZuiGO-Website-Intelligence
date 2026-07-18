from celery import Celery

from worker_app.config import get_settings
from worker_app.logging_config import configure_logging

settings = get_settings()
configure_logging(settings.log_level)
redis_url = str(settings.redis_url)

celery_app = Celery("website_intelligence_worker", broker=redis_url, backend=redis_url)
celery_app.conf.update(
    include=["worker_app.tasks.health", "worker_app.tasks.analysis"],
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)
