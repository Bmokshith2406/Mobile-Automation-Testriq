import json
import logging
from contextvars import ContextVar, Token
from datetime import datetime, timezone
from typing import Any

from app.core.config import get_settings

settings = get_settings()
_log_context: ContextVar[dict[str, Any]] = ContextVar("log_context", default={})


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        context = _log_context.get({})
        record.request_id = context.get("request_id", "-")
        record.correlation_id = context.get("correlation_id", "-")
        record.trace_id = context.get("trace_id", "-")
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
            "correlation_id": getattr(record, "correlation_id", "-"),
            "trace_id": getattr(record, "trace_id", "-"),
        }

        for key, value in record.__dict__.items():
            if key.startswith("_") or key in {
                "args",
                "asctime",
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
                "message",
                "msg",
                "name",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "stack_info",
                "thread",
                "threadName",
                "request_id",
                "correlation_id",
                "trace_id",
            }:
                continue

            payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


def set_log_context(values: dict[str, Any]) -> Token:
    current = dict(_log_context.get({}))
    current.update({k: v for k, v in values.items() if v is not None})
    return _log_context.set(current)


def reset_log_context(token: Token) -> None:
    _log_context.reset(token)


def clear_log_context() -> None:
    _log_context.set({})


def setup_logging() -> logging.Logger:
    logger = logging.getLogger("method-search")
    logger.setLevel(getattr(logging, settings.LOG_LEVEL, logging.INFO))
    logger.propagate = False

    if logger.handlers:
        return logger

    handler = logging.StreamHandler()
    handler.addFilter(RequestContextFilter())

    if settings.LOG_FORMAT == "json":
        formatter: logging.Formatter = JsonFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s | %(request_id)s | %(message)s"
        )

    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger


logger = setup_logging()
