import os

from celery import Celery

redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")

celery_app = Celery("website_intelligence_worker", broker=redis_url, backend=redis_url)
celery_app.conf.update(
    include=["worker_app.tasks.health"],
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)
