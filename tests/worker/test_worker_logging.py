import logging

from worker_app.config import LogLevel
from worker_app.logging_config import HANDLER_NAME, configure_logging, create_formatter


def test_worker_logging_configuration() -> None:
    configure_logging(LogLevel.WARNING)
    handler = next(
        handler for handler in logging.getLogger().handlers if handler.get_name() == HANDLER_NAME
    )
    record = logging.LogRecord("worker.test", logging.WARNING, __file__, 1, "configured", (), None)
    rendered = create_formatter().format(record)

    assert handler.level == logging.WARNING
    assert "level=WARNING service=worker logger=worker.test message=configured" in rendered

    configure_logging(LogLevel.INFO)
