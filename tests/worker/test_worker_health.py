from worker_app.tasks.health import health_check


def test_worker_health_task_returns_expected_response() -> None:
    assert health_check.run() == {"status": "healthy", "service": "worker"}
