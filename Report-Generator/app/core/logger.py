import logging
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from contextvars import ContextVar

try:
    from pythonjsonlogger.json import JsonFormatter
except ImportError:  # Backward compatibility with older python-json-logger releases
    from pythonjsonlogger.jsonlogger import JsonFormatter

# Context variables for request tracing
request_id_ctx_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
trace_id_ctx_var: ContextVar[Optional[str]] = ContextVar("trace_id", default=None)


# ------------------------------------------------------------------------------
# Clean Console Formatter (Human Readable)
# ------------------------------------------------------------------------------

class ConsoleFormatter(logging.Formatter):
    """Readable console formatter with correlation IDs."""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        level = record.levelname
        logger_name = record.name
        message = record.getMessage()

        request_id = request_id_ctx_var.get()
        trace_id = trace_id_ctx_var.get()

        correlation = ""
        if request_id:
            correlation += f" | req={request_id}"
        if trace_id:
            correlation += f" | trace={trace_id}"

        base_log = (
            f"{timestamp} | {level:<8} | {logger_name} | {message}{correlation}"
        )

        if record.exc_info:
            base_log += "\n" + self.formatException(record.exc_info)

        return base_log


class CustomJsonFormatter(JsonFormatter):
    """JSON formatter for production logs."""
    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        log_record['timestamp'] = datetime.now(timezone.utc).isoformat()
        log_record['level'] = record.levelname
        log_record['logger'] = record.name
        
        req_id = request_id_ctx_var.get()
        trace_id = trace_id_ctx_var.get()
        if req_id:
            log_record['request_id'] = req_id
        if trace_id:
            log_record['trace_id'] = trace_id

# ------------------------------------------------------------------------------
# Logging Setup
# ------------------------------------------------------------------------------

def setup_logging(
    log_level: str = "INFO",
    service_name: str = "service",
    environment: str = "dev",
) -> None:
    """Configure clean, readable console logging."""

    root_logger = logging.getLogger()

    # Prevent duplicate handlers
    if root_logger.handlers:
        return

    root_logger.setLevel(log_level)

    handler = logging.StreamHandler(sys.stdout)
    if environment == "dev":
        formatter = ConsoleFormatter()
    else:
        formatter = CustomJsonFormatter()

    handler.setFormatter(formatter)
    root_logger.addHandler(handler)

    # Reduce noise from framework logs
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    
    # Silence Sentry debug noise
    logging.getLogger("sentry_sdk").setLevel(logging.WARNING)
    logging.getLogger("sentry_sdk.errors").setLevel(logging.WARNING)

    root_logger.info(
        f"Logging initialized | service={service_name} | env={environment} | level={log_level}"
    )


# ------------------------------------------------------------------------------
# Logger Factory
# ------------------------------------------------------------------------------

def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


# ------------------------------------------------------------------------------
# Request ID / Trace ID helpers
# ------------------------------------------------------------------------------

def set_request_id(request_id: Optional[str] = None):
    if not request_id:
        request_id = str(uuid.uuid4())
    request_id_ctx_var.set(request_id)
    return request_id


def set_trace_id(trace_id: Optional[str] = None):
    if not trace_id:
        trace_id = str(uuid.uuid4())
    trace_id_ctx_var.set(trace_id)
    return trace_id
