from celery import Celery

from app.config import get_settings

TASK_NAME = "worker.run_analysis"
DISCOVERY_TASK_NAME = "worker.run_discovery"
PAGE_ANALYSIS_TASK_NAME = "worker.run_page_analysis"


def enqueue_analysis(analysis_run_id: str) -> str:
    redis_url = get_settings().redis_url
    queue_client = Celery("website_intelligence_api", broker=redis_url)
    try:
        result = queue_client.send_task(TASK_NAME, args=[analysis_run_id])
        return result.id
    finally:
        queue_client.close()


def enqueue_discovery(discovery_run_id: str) -> str:
    redis_url = get_settings().redis_url
    queue_client = Celery("website_intelligence_api", broker=redis_url)
    try:
        result = queue_client.send_task(DISCOVERY_TASK_NAME, args=[discovery_run_id])
        return result.id
    finally:
        queue_client.close()


def enqueue_page_analysis(discovery_run_id: str, page_analysis_execution_id: str) -> str:
    redis_url = get_settings().redis_url
    queue_client = Celery("website_intelligence_api", broker=redis_url)
    try:
        result = queue_client.send_task(
            PAGE_ANALYSIS_TASK_NAME,
            args=[discovery_run_id, page_analysis_execution_id],
        )
        return result.id
    finally:
        queue_client.close()
