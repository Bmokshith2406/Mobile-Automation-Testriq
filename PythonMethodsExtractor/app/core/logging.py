import logging
import sys
from contextvars import ContextVar, Token


_LOG_CONTEXT: ContextVar[dict[str, str]] = ContextVar("log_context", default={})


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        context = _LOG_CONTEXT.get({})
        record.request_id = context.get("request_id", "-")
        record.correlation_id = context.get("correlation_id", "-")
        record.trace_id = context.get("trace_id", "-")
        return True


def setup_logging(log_level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RequestContextFilter())
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s | %(message)s "
            "| request_id=%(request_id)s correlation_id=%(correlation_id)s trace_id=%(trace_id)s"
        )
    )

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(log_level.upper())
    root_logger.addHandler(handler)


def set_log_context(values: dict[str, str]) -> Token:
    merged = dict(_LOG_CONTEXT.get({}))
    merged.update({key: value for key, value in values.items() if value})
    return _LOG_CONTEXT.set(merged)


def reset_log_context(token: Token) -> None:
    _LOG_CONTEXT.reset(token)


def get_log_context() -> dict[str, str]:
    return dict(_LOG_CONTEXT.get({}))


logger = logging.getLogger("playwright_python_method_extractor")
