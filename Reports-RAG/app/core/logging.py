import contextvars
from datetime import datetime, timezone
import json
import logging
import sys
from typing import Any, Dict

from app.core.config import settings


_log_context: contextvars.ContextVar[Dict[str, Any]] = contextvars.ContextVar(
    "log_context",
    default={},
)
_LOGGER_INITIALIZED = False


def set_log_context(values: Dict[str, Any]) -> contextvars.Token:
    current = dict(_log_context.get())
    current.update(values)
    return _log_context.set(current)


def reset_log_context(token: contextvars.Token) -> None:
    _log_context.reset(token)


def get_log_context() -> Dict[str, Any]:
    return dict(_log_context.get())


class JsonFormatter(logging.Formatter):
    """Structured JSON formatter with request context support."""

    _RESERVED_FIELDS = {
        "args",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
    }

    def format(self, record: logging.LogRecord) -> str:
        log_record: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        log_record.update(get_log_context())

        for key, value in record.__dict__.items():
            if key not in self._RESERVED_FIELDS:
                log_record[key] = value

        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_record, default=str)


def _build_formatter() -> logging.Formatter:
    if settings.is_production:
        return JsonFormatter()

    return logging.Formatter(
        fmt="[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def configure_logging() -> None:
    global _LOGGER_INITIALIZED

    if _LOGGER_INITIALIZED:
        return

    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)
    handler.setFormatter(_build_formatter())
    root_logger.addHandler(handler)

    _LOGGER_INITIALIZED = True


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)


configure_logging()
logger = get_logger(settings.APP_NAME)
