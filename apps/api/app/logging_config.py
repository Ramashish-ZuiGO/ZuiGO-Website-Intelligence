import logging
import time

from app.config import LogLevel

HANDLER_NAME = "zuigo-api"
LOG_FORMAT = "%(asctime)s level=%(levelname)s service=api logger=%(name)s message=%(message)s"


def create_formatter() -> logging.Formatter:
    formatter = logging.Formatter(LOG_FORMAT, datefmt="%Y-%m-%dT%H:%M:%SZ")
    formatter.converter = time.gmtime
    return formatter


def configure_logging(log_level: LogLevel) -> None:
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level.value)

    handler = next(
        (existing for existing in root_logger.handlers if existing.get_name() == HANDLER_NAME),
        None,
    )
    if handler is None:
        handler = logging.StreamHandler()
        handler.set_name(HANDLER_NAME)
        root_logger.addHandler(handler)

    handler.setLevel(log_level.value)
    handler.setFormatter(create_formatter())

    for logger_name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(logger_name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True

    logging.getLogger("uvicorn.access").disabled = True
