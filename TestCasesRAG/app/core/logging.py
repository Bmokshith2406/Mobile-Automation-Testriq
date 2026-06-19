import logging
import json
from datetime import datetime, timezone
from contextvars import ContextVar, Token
from typing import Any, Optional, Dict

from app.core.config import get_settings

settings = get_settings()
_log_context: ContextVar[Dict[str, Any]] = ContextVar("log_context", default={})


class JSONFormatter(logging.Formatter):
    """JSON structured logging for production."""

    def format(self, record: logging.LogRecord) -> str:
        log_data: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add extra fields if present
        if hasattr(record, "request_id"):
            log_data["request_id"] = record.request_id

        if hasattr(record, "correlation_id"):
            log_data["correlation_id"] = record.correlation_id

        if hasattr(record, "user_id"):
            log_data["user_id"] = record.user_id

        # Add exception info if present
        if record.exc_info:
            try:
                log_data["exception"] = self.formatException(record.exc_info)
            except Exception:
                log_data["exception"] = "exception_formatting_failed"

        # Add any extra dict data
        if hasattr(record, "extra_data") and isinstance(record.extra_data, dict):
            log_data.update(record.extra_data)

        try:
            return json.dumps(log_data, default=str)
        except Exception:
            # Fallback if JSON serialization fails
            return str(log_data)


class StructuredLogger:
    """
    Production-ready structured logger with context tracking.
    Automatically includes request IDs, correlation IDs, and metrics.
    """

    def __init__(self, name: str):
        self._logger = logging.getLogger(name)

    def _log(
        self,
        level: int,
        message: str,
        extra: Optional[Dict[str, Any]] = None,
        exc_info: bool = False,
    ):
        """Internal logging method with structured fields."""

        try:
            extra_data = {
                **get_log_context(),
                **(extra or {}),
            }

            self._logger.log(
                level,
                message,
                exc_info=exc_info,
                extra={"extra_data": extra_data},
            )

        except Exception:
            # Absolute safety fallback
            try:
                self._logger.log(level, message)
            except Exception:
                pass

    def debug(self, message: str, extra: Optional[Dict[str, Any]] = None):
        """Log debug message."""
        self._log(logging.DEBUG, message, extra)

    def info(self, message: str, extra: Optional[Dict[str, Any]] = None):
        """Log info message."""
        self._log(logging.INFO, message, extra)

    def warning(self, message: str, extra: Optional[Dict[str, Any]] = None):
        """Log warning message."""
        self._log(logging.WARNING, message, extra)

    def error(
        self,
        message: str,
        extra: Optional[Dict[str, Any]] = None,
        exc_info: bool = False,
    ):
        """Log error message."""
        self._log(logging.ERROR, message, extra, exc_info=exc_info)

    def critical(
        self,
        message: str,
        extra: Optional[Dict[str, Any]] = None,
        exc_info: bool = False,
    ):
        """Log critical message."""
        self._log(logging.CRITICAL, message, extra, exc_info=exc_info)


def setup_logging() -> StructuredLogger:
    """Setup production-grade structured logging."""

    try:
        root = logging.getLogger()

        # Only add handlers if not already configured
        if not root.handlers:
            console_handler = logging.StreamHandler()

            if settings.LOG_FORMAT == "json":
                formatter = JSONFormatter()
            else:
                formatter = logging.Formatter(
                    "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
                )

            console_handler.setFormatter(formatter)
            root.addHandler(console_handler)

        # Set log level
        log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
        root.setLevel(log_level)

        return StructuredLogger("testcase-search")

    except Exception:
        # Fallback to basic logging
        try:
            logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            )
            return StructuredLogger("testcase-search")

        except Exception:
            return StructuredLogger("testcase-search")


logger = setup_logging()


def set_log_context(context: Dict[str, Any]) -> Token:
    return _log_context.set(context)


def reset_log_context(token: Token) -> None:
    _log_context.reset(token)


def get_log_context() -> Dict[str, Any]:
    try:
        return dict(_log_context.get())
    except Exception:
        return {}
