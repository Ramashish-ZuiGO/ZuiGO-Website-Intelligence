from worker_app.celery_app import celery_app
from worker_app.tasks.agent_platform import retry_agent_run, run_workflow_execution


def test_agent_platform_celery_tasks_are_registered_with_safe_serialization() -> None:
    assert run_workflow_execution.name == "worker.run_workflow_execution"
    assert retry_agent_run.name == "worker.retry_agent_run"
    assert "worker.run_workflow_execution" in celery_app.tasks
    assert "worker.retry_agent_run" in celery_app.tasks
    assert celery_app.conf.task_serializer == "json"
    assert celery_app.conf.accept_content == ["json"]
    assert celery_app.conf.result_serializer == "json"
    assert "worker_app.tasks.agent_platform" in celery_app.conf.include
