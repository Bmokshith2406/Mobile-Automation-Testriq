from hashlib import sha256
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import PyMongoError

from app.core.config import get_settings
from app.core.logging import logger
from app.models.schemas import APILog, RawScript


settings = get_settings()
_client: Optional[AsyncIOMotorClient] = None
_db: Optional[AsyncIOMotorDatabase] = None


def is_mongo_enabled() -> bool:
    return settings.mongo_enabled


def get_mongo_client() -> Optional[AsyncIOMotorClient]:
    global _client, _db

    if not is_mongo_enabled():
        return None

    if _client is None:
        try:
            _client = AsyncIOMotorClient(
                settings.MONGO_URI,
                serverSelectionTimeoutMS=5000,
            )
            _db = _client[settings.MONGO_DB]
            logger.info("MongoDB client initialized")
        except PyMongoError as exc:
            logger.error(f"MongoDB client initialization failed: {exc}")
            raise

    return _client


def get_database() -> Optional[AsyncIOMotorDatabase]:
    global _db
    if _db is None and get_mongo_client() is None:
        return None
    return _db


async def close_mongo_connection() -> None:
    global _client, _db

    if _client is not None:
        _client.close()
        _client = None
        _db = None
        logger.info("MongoDB client connection closed")


async def validate_mongo_connection() -> bool:
    if not is_mongo_enabled():
        logger.info("MongoDB connectivity check skipped because MONGO_URI is not configured")
        return False

    client = get_mongo_client()
    if client is None:
        return False

    try:
        await client.admin.command("ping")
        logger.info(f"MongoDB connection established successfully (db='{settings.MONGO_DB}')")
        return True
    except Exception as exc:
        logger.error(f"MongoDB connection validation failed: {exc}")
        if settings.MONGO_REQUIRED_FOR_STARTUP and settings.FAIL_FAST_STARTUP:
            raise
        return False


async def ping_db() -> bool:
    if not is_mongo_enabled():
        return False

    client = get_mongo_client()
    if client is None:
        return False

    try:
        await client.admin.command("ping")
        return True
    except Exception as exc:
        logger.warning(f"MongoDB ping failed: {exc}")
        return False


async def log_api_call(record: dict) -> None:
    database = get_database()
    if database is None:
        return

    try:
        model = APILog(**record)
        await database[settings.COLLECTION_API_LOGS].insert_one(model.model_dump(mode="python"))
    except Exception as exc:
        logger.error(f"MongoDB log_api_call failed: {exc}")


async def store_raw_script(
    filename: str,
    content: str,
    metadata: dict | None = None,
) -> None:
    if not settings.STORE_RAW_SCRIPTS:
        return

    database = get_database()
    if database is None:
        return

    try:
        document = {
            "filename": filename,
            "content": content,
            "size": len(content),
            "script_sha256": sha256(content.encode("utf-8")).hexdigest(),
        }
        if metadata:
            document.update(metadata)

        model = RawScript(**document)
        await database[settings.COLLECTION_RAW_SCRIPTS].insert_one(model.model_dump(mode="python"))
    except Exception as exc:
        logger.error(f"MongoDB store_raw_script failed: {exc}")
