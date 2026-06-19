"""Startup diagnostic checks for production readiness."""

from app.core.config import get_settings
from app.core.gemini_client import get_gemini_client
from app.core.logging import logger
from app.db.mongo import get_client, ping_db
from app.services.embeddings import is_embedding_model_loaded, load_embedding_model


async def run_startup_diagnostics() -> dict:
    results = {
        "environment": {},
        "database": {},
        "ai_services": {},
        "embeddings": {},
        "status": "initializing",
    }

    try:
        settings = get_settings()

        auth_configured = bool(settings.API_KEY or settings.JWT_SECRET_KEY != settings.DEFAULT_JWT_SECRET)
        checks = {
            "GOOGLE_API_KEY": bool(settings.GOOGLE_API_KEY),
            "MONGO_CONNECTION_STRING": bool(settings.MONGO_CONNECTION_STRING),
            "AUTH": auth_configured,
            "CORS_ALLOWED_ORIGINS": len(settings.CORS_ALLOWED_ORIGINS) > 0,
            "DATABASE_POOLING": (
                settings.DB_POOL_MIN_SIZE > 0
                and settings.DB_POOL_MAX_SIZE >= settings.DB_POOL_MIN_SIZE
            ),
            "RATE_LIMITING": settings.RATE_LIMIT_PER_MINUTE > 0,
        }
        results["environment"]["checks"] = checks
        results["environment"]["all_passed"] = all(checks.values())

        await ping_db()
        get_client()
        results["database"]["mongodb_ping"] = True
        results["database"]["connection_pool_configured"] = True
        results["database"]["all_passed"] = True

        client = await get_gemini_client()
        results["ai_services"]["gemini_available"] = client is not None

        if not is_embedding_model_loaded():
            await load_embedding_model()
        results["embeddings"]["model_loaded"] = is_embedding_model_loaded()

        if (
            results["environment"]["all_passed"]
            and results["database"]["all_passed"]
            and results["ai_services"]["gemini_available"]
            and results["embeddings"]["model_loaded"]
        ):
            results["status"] = "ready"
        else:
            results["status"] = "degraded"

        return results

    except Exception as exc:
        logger.critical(f"Diagnostic suite failed: {exc}", exc_info=True)
        results["status"] = "error"
        results["error"] = str(exc)
        return results


async def health_check() -> dict:
    diagnostics = await run_startup_diagnostics()
    return {
        "status": "healthy" if diagnostics["status"] == "ready" else diagnostics["status"],
        "details": diagnostics,
    }
