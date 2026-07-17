import logging

import pytest
from worker_app.tasks.health import health_check


def test_worker_health_task_returns_expected_response_and_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger="worker_app.tasks.health"):
        result = health_check.run()

    assert result == {"status": "healthy", "service": "worker"}
    assert "health_check status=healthy" in caplog.text
