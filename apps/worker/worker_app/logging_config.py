import logging
import time
from typing import Any

from celery import signals

from worker_app.config import LogLevel, get_settings

HANDLER_NAME = "zuigo-worker"
LOG_FORMAT = "%(asctime)s level=%(levelname)s service=worker logger=%(name)s message=%(message)s"
logger = logging.getLogger("worker_app.lifecycle")


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


@signals.setup_logging.connect
def setup_celery_logging(**_: Any) -> None:
    configure_logging(get_settings().log_level)


@signals.worker_ready.connect
def log_worker_ready(**_: Any) -> None:
    logger.info("worker_startup status=ready")
