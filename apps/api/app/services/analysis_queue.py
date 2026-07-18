from celery import Celery

from app.config import get_settings

TASK_NAME = "worker.run_analysis"


def enqueue_analysis(analysis_run_id: str) -> str:
    redis_url = get_settings().redis_url
    queue_client = Celery("website_intelligence_api", broker=redis_url)
    try:
        result = queue_client.send_task(TASK_NAME, args=[analysis_run_id])
        return result.id
    finally:
        queue_client.close()
