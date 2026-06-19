from typing import Optional
from motor.motor_asyncio import AsyncIOMotorClient
from app.core.config import settings
from app.core.logging import logger

_client: Optional[AsyncIOMotorClient] = None

async def connect_to_mongo() -> None:
    global _client
    try:
        _client = AsyncIOMotorClient(
            settings.MONGO_URI,
            maxPoolSize=50,
            minPoolSize=5,
            serverSelectionTimeoutMS=5000,
        )
        await _client.admin.command("ping")
        logger.info(f"Connected to MongoDB at {settings.MONGO_URI}")
        
        # Ensure indexes
        db = _client[settings.MONGO_DB]
        col = db["execution_history"]
        # Basic index on testcase_id
        await col.create_index("testcase_id")
    except Exception as exc:
        logger.error(f"MongoDB connection failed: {exc}")
        _client = None

async def disconnect_from_mongo() -> None:
    global _client
    if _client:
        _client.close()
        _client = None
        logger.info("MongoDB disconnected")

def get_db():
    if not _client:
        raise RuntimeError("MongoDB client not initialized")
    return _client[settings.MONGO_DB]

def get_execution_history_collection():
    return get_db()["execution_history"]
