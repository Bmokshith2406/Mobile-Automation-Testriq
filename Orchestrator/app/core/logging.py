import logging
import os

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

class SafeFormatter(logging.Formatter):
    def format(self, record):
        if not hasattr(record, "request_id"):
            record.request_id = "-"
        return super().format(record)

handler = logging.StreamHandler()
handler.setFormatter(
    SafeFormatter("%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s")
)

root_logger = logging.getLogger()
root_logger.handlers = []
root_logger.addHandler(handler)
root_logger.setLevel(LOG_LEVEL)

logger = logging.getLogger("orchestrator")

def request_logger_adapter(request_id: str) -> logging.LoggerAdapter:
    """Return a LoggerAdapter that injects request_id into log records' 'request_id' key."""
    return logging.LoggerAdapter(logger, {"request_id": request_id})
