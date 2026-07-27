from celery import Celery

from app.config import get_settings

WORKFLOW_EXECUTION_TASK = "worker.run_workflow_execution"
AGENT_RETRY_TASK = "worker.retry_agent_run"


def workflow_task_id(execution_id: str, attempt: int) -> str:
    return f"workflow-execution:{execution_id}:attempt:{attempt}"


def agent_retry_task_id(run_id: str, next_attempt: int) -> str:
    return f"agent-run:{run_id}:attempt:{next_attempt}"


def _queue_client() -> Celery:
    return Celery(
        "website_intelligence_agent_platform",
        broker=get_settings().redis_url,
    )


def enqueue_workflow_execution(
    execution_id: str,
    *,
    attempt: int,
) -> str:
    task_id = workflow_task_id(execution_id, attempt)
    client = _queue_client()
    try:
        result = client.send_task(
            WORKFLOW_EXECUTION_TASK,
            args=[execution_id],
            task_id=task_id,
        )
        return result.id
    finally:
        client.close()


def enqueue_agent_retry(
    run_id: str,
    *,
    next_attempt: int,
) -> str:
    task_id = agent_retry_task_id(run_id, next_attempt)
    client = _queue_client()
    try:
        result = client.send_task(
            AGENT_RETRY_TASK,
            args=[run_id],
            task_id=task_id,
        )
        return result.id
    finally:
        client.close()


def revoke_workflow_task(task_id: str) -> None:
    client = _queue_client()
    try:
        client.control.revoke(task_id, terminate=False)
    finally:
        client.close()
