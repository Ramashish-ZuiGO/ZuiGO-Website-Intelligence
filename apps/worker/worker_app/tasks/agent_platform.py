import logging
import uuid

from app.db.session import SessionLocal
from app.models import AgentExecution, AgentRun
from app.services.workflow_execution import DeterministicWorkflowOrchestrator
from sqlalchemy import select

from worker_app.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="worker.run_workflow_execution",
    acks_late=True,
    soft_time_limit=900,
    time_limit=960,
)
def run_workflow_execution(execution_id: str) -> dict[str, str]:
    parsed_execution_id = uuid.UUID(execution_id)
    logger.info("workflow_execution_task_started execution_id=%s", execution_id)
    execution = DeterministicWorkflowOrchestrator(SessionLocal).execute(parsed_execution_id)
    logger.info(
        "workflow_execution_task_finished execution_id=%s status=%s",
        execution_id,
        execution.status,
    )
    return {
        "execution_id": str(execution.execution_id),
        "status": execution.status,
    }


@celery_app.task(
    name="worker.retry_agent_run",
    acks_late=True,
    soft_time_limit=900,
    time_limit=960,
)
def retry_agent_run(run_id: str) -> dict[str, str]:
    parsed_run_id = uuid.UUID(run_id)
    logger.info("agent_retry_task_started run_id=%s", run_id)
    with SessionLocal() as db:
        run = db.scalar(select(AgentRun).where(AgentRun.agent_run_id == parsed_run_id))
        if run is None:
            logger.warning("agent_retry_run_not_found run_id=%s", run_id)
            return {"run_id": run_id, "status": "not_found"}
        execution = db.get(AgentExecution, run.execution_id)
        if execution is None:
            logger.warning("agent_retry_execution_not_found run_id=%s", run_id)
            return {"run_id": run_id, "status": "execution_not_found"}
        execution_id = execution.execution_id
    execution = DeterministicWorkflowOrchestrator(SessionLocal).execute(execution_id)
    logger.info(
        "agent_retry_task_finished run_id=%s execution_id=%s status=%s",
        run_id,
        execution_id,
        execution.status,
    )
    return {
        "run_id": run_id,
        "execution_id": str(execution.execution_id),
        "status": execution.status,
    }
