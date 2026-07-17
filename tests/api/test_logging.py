import logging
import re

import pytest
from app.config import LogLevel
from app.logging_config import HANDLER_NAME, configure_logging, create_formatter
from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_api_logging_configuration() -> None:
    configure_logging(LogLevel.INFO)
    handler = next(
        handler for handler in logging.getLogger().handlers if handler.get_name() == HANDLER_NAME
    )
    record = logging.LogRecord("app.test", logging.INFO, __file__, 1, "configured", (), None)
    rendered = create_formatter().format(record)

    assert handler.level == logging.INFO
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z ", rendered)
    assert "level=INFO service=api logger=app.test message=configured" in rendered


def test_api_request_log_is_created_without_sensitive_headers(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger="app.request"):
        response = client.get(
            "/missing",
            headers={
                "Authorization": "Bearer sensitive-token",
                "Cookie": "session=sensitive-cookie",
                "X-Request-ID": "request-123",
            },
        )

    assert response.status_code == 404
    assert "http_request method=GET path='/missing' status=404" in caplog.text
    assert "request_id=request-123" in caplog.text
    assert "sensitive-token" not in caplog.text
    assert "sensitive-cookie" not in caplog.text
    assert "Authorization" not in caplog.text
    assert "Cookie" not in caplog.text
