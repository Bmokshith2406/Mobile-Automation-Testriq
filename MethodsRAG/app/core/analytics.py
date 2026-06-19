from datetime import datetime
from typing import Optional, Dict, Any

from app.db.mongo import get_db
from app.core.config import get_settings
from app.core.logging import logger

settings = get_settings()


async def log_api_call(
    endpoint: str,
    method: str,
    user: Optional[dict],
    payload: Optional[Dict[str, Any]] = None,
    extra: Optional[Dict[str, Any]] = None,
):

    try:
        try:
            db = get_db()
        except Exception as err:
            logger.warning(f"Audit log skipped — DB unavailable: {err}")
            return

        try:
            doc = {
                "timestamp": datetime.utcnow(),
                "endpoint": endpoint,
                "method": method,
                "user_id": user.get("id") if user else None,
                "username": user.get("username") if user else None,
                "payload": payload or {},
                "extra": extra or {},
            }
        except Exception as err:
            logger.warning(f"Audit log skipped — doc assembly failed: {err}")
            return

        try:
            await db[settings.COLLECTION_AUDIT].insert_one(doc)
        except Exception as err:
            logger.warning(f"Failed to write audit log: {err}")

    except Exception as err:
        # Absolute fallback safety — do NOT allow auditing to affect API stability
        logger.warning(f"Audit logging unexpected failure: {err}")
