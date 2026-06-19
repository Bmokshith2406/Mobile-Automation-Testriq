from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core.config import get_settings
from app.core.logging import logger
from app.core.exceptions import DatabaseError

settings = get_settings()

_mongo_client: Optional[AsyncIOMotorClient] = None


def get_client() -> AsyncIOMotorClient:
    global _mongo_client

    try:
        if _mongo_client is None:
            logger.info("Connecting to MongoDB Atlas...")

            try:
                connection_string = settings.MONGO_CONNECTION_STRING
                _mongo_client = AsyncIOMotorClient(
                    connection_string,
                    maxPoolSize=settings.DB_POOL_MAX_SIZE,
                    minPoolSize=settings.DB_POOL_MIN_SIZE,
                    serverSelectionTimeoutMS=5000,
                    socketTimeoutMS=30000,
                    connectTimeoutMS=10000,
                    retryWrites=True,
                )
                logger.info(f"MongoDB client initialized with pool size: {settings.DB_POOL_MIN_SIZE}-{settings.DB_POOL_MAX_SIZE}")
                
            except Exception as err:
                logger.critical(f"MongoDB client initialization failed: {err}", exc_info=True)
                raise DatabaseError(f"Failed to initialize MongoDB client: {err}", operation="connect")

        return _mongo_client

    except DatabaseError:
        raise
    except Exception as err:
        logger.critical(f"Unexpected error getting MongoDB client: {err}", exc_info=True)
        raise DatabaseError(f"Unexpected error getting MongoDB client: {err}", operation="get_client")


def get_db() -> AsyncIOMotorDatabase:
    """Get MongoDB database instance."""
    try:
        client = get_client()
        return client[settings.DB_NAME]
    except DatabaseError:
        raise
    except Exception as err:
        logger.critical(f"Error getting database: {err}", exc_info=True)
        raise DatabaseError(f"Error getting database: {err}", operation="get_db")


async def ping_db():
    """Verify database connectivity."""
    try:
        client = get_client()
    except Exception as err:
        logger.critical(f"Failed to get MongoDB client for ping: {err}")
        raise

    try:
        await client.admin.command("ping")
        logger.info("MongoDB ping successful")
    except Exception as err:
        logger.critical(f"MongoDB ping failed: {err}", exc_info=True)
        raise DatabaseError("MongoDB ping failed", operation="ping")


async def close_db():
    """Close MongoDB connection pool."""
    global _mongo_client

    try:
        if _mongo_client is not None:
            try:
                _mongo_client.close()
                logger.info("MongoDB connection closed")
            except Exception as err:
                logger.warning(f"Error closing MongoDB connection: {err}")
            
            _mongo_client = None

    except Exception as err:
        logger.warning(f"Error in close_db: {err}")


def get_methods_collection():
    """Get methods collection with error handling."""
    try:
        db = get_db()
        return db[settings.COLLECTION_SCRIPT_METHODS]
    except DatabaseError:
        raise
    except Exception as err:
        logger.critical(f"Error getting methods collection: {err}")
        raise DatabaseError(f"Error getting methods collection: {err}", operation="get_methods_collection")


def get_users_collection():
    """Get users collection with error handling."""
    try:
        db = get_db()
        return db[settings.COLLECTION_USERS]
    except DatabaseError:
        raise
    except Exception as err:
        logger.critical(f"Error getting users collection: {err}")
        raise DatabaseError(f"Error getting users collection: {err}", operation="get_users_collection")


def get_audit_collection():
    """Get audit logs collection with error handling."""
    try:
        db = get_db()
        return db[settings.COLLECTION_AUDIT]
    except DatabaseError:
        raise
    except Exception as err:
        logger.critical(f"Error getting audit collection: {err}")
        raise DatabaseError(f"Error getting audit collection: {err}", operation="get_audit_collection")
