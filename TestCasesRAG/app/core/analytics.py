from datetime import datetime, timezone
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
        # -----------------------------------------------------
        # Get DB connection
        # -----------------------------------------------------
        try:
            db = get_db()
        except Exception as err:
            logger.warning(
                "audit_log_db_unavailable",
                extra={"error": str(err), "endpoint": endpoint},
            )
            return

        # -----------------------------------------------------
        # Assemble document
        # -----------------------------------------------------
        try:
            safe_payload = payload or {}
            safe_extra = extra or {}

            doc = {
                "timestamp": datetime.now(timezone.utc),
                "endpoint": endpoint,
                "method": method,
                "user_id": user.get("id") if user else None,
                "username": user.get("username") if user else None,
                "role": user.get("role") if user else None,
                "payload": safe_payload,
                "extra": safe_extra,
            }
        except Exception as err:
            logger.warning(
                "audit_log_doc_assembly_failed",
                extra={"error": str(err), "endpoint": endpoint},
            )
            return

        # -----------------------------------------------------
        # Write to DB
        # -----------------------------------------------------
        try:
            collection = db[settings.COLLECTION_AUDIT]
            await collection.insert_one(doc)
        except Exception as err:
            logger.warning(
                "audit_log_write_failed",
                extra={"error": str(err), "endpoint": endpoint},
            )

    except Exception as err:
        # -----------------------------------------------------
        # Absolute fallback safety
        # Never break the API because of logging
        # -----------------------------------------------------
        logger.warning(
            "audit_log_unexpected_failure",
            extra={"error": str(err), "endpoint": endpoint},
        )
