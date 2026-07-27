from celery import Celery, chain

from app.config import get_settings

TASK_NAME = "worker.run_analysis"
DISCOVERY_TASK_NAME = "worker.run_discovery"
PAGE_ANALYSIS_TASK_NAME = "worker.run_page_analysis"
WORKFLOW_TASK_NAME = "worker.run_workflow_execution"


def enqueue_analysis(analysis_run_id: str) -> str:
    redis_url = get_settings().redis_url
    queue_client = Celery("website_intelligence_api", broker=redis_url)
    try:
        result = queue_client.send_task(TASK_NAME, args=[analysis_run_id])
        return result.id
    finally:
        queue_client.close()


def enqueue_analysis_journey(
    analysis_run_id: str,
    workflow_execution_id: str,
    *,
    workflow_attempt: int,
) -> tuple[str, str]:
    """Queue evidence collection before the existing deterministic workflow."""
    redis_url = get_settings().redis_url
    queue_client = Celery("website_intelligence_api", broker=redis_url)
    analysis_task_id = f"analysis-run:{analysis_run_id}"
    workflow_task_id = f"workflow-execution:{workflow_execution_id}:attempt:{workflow_attempt}"
    try:
        pipeline = chain(
            queue_client.signature(
                TASK_NAME,
                args=[analysis_run_id],
                immutable=True,
                task_id=analysis_task_id,
            ),
            queue_client.signature(
                WORKFLOW_TASK_NAME,
                args=[workflow_execution_id],
                immutable=True,
                task_id=workflow_task_id,
            ),
        )
        pipeline.apply_async()
        return analysis_task_id, workflow_task_id
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
