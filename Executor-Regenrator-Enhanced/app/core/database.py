"""
Database Persistence Layer - Production Connection Manager

Features:
- Connection lifecycle management
- MongoClient timeouts (serverSelectionTimeoutMS and connectTimeoutMS)
- Repository routing convenience functions
"""

import logging
from typing import Optional
from contextlib import asynccontextmanager

from app.core.config import get_settings
from app.models.database import RepairRecord, ExecutionRecord, FailurePattern
from app.core.repositories import Repository, InMemoryRepository, MongoDBRepository

logger = logging.getLogger("database")


class DatabaseManager:
    """
    Manages database connections and provides repository access.
    """
    
    _instance: Optional["DatabaseManager"] = None
    
    @classmethod
    def get_instance(cls) -> "DatabaseManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def __init__(self):
        self.settings = get_settings()
        self._repository = None
        self._client = None
        self._initialized = False
        self._storage_mode = "uninitialized"
        self._last_error: Optional[str] = None
    
    async def initialize(self):
        """Initialize the database connection with strict timeouts."""
        if self._initialized:
            return
        
        if self.settings.MONGODB_URL:
            try:
                from motor.motor_asyncio import AsyncIOMotorClient
                # Proactively set connection timeouts to avoid blocking forever on DB down
                self._client = AsyncIOMotorClient(
                    self.settings.MONGODB_URL,
                    serverSelectionTimeoutMS=5000,
                    connectTimeoutMS=5000,
                )
                await self._client.admin.command("ping")
                db = self._client[self.settings.MONGODB_DB_NAME]
                self._repository = MongoDBRepository(db)
                await self._repository.initialize_indexes()
                self._storage_mode = "mongodb"
                self._last_error = None
                logger.info("Initialized MongoDB connection to %s", self.settings.MONGODB_DB_NAME)
            except Exception as e:
                if self._client:
                    self._client.close()
                    self._client = None
                self._last_error = str(e)

                if self.settings.is_development or self.settings.ALLOW_INMEMORY_DATABASE_FALLBACK:
                    logger.exception(
                        "Failed to connect to MongoDB, falling back to in-memory: %s",
                        e,
                    )
                    self._repository = InMemoryRepository()
                    self._storage_mode = "in-memory-fallback"
                else:
                    logger.exception("Failed to connect to MongoDB: %s", e)
                    raise RuntimeError(
                        "MongoDB is configured but unavailable; refusing to fall back to in-memory storage"
                    ) from e
        else:
            logger.info("No MongoDB URL configured, using in-memory repository")
            self._repository = InMemoryRepository()
            self._storage_mode = "in-memory"
            self._last_error = None
        
        self._initialized = True
    
    @property
    def repository(self):
        """Get the repository instance."""
        if self._repository is None:
            self._repository = InMemoryRepository()
            self._storage_mode = "in-memory"
        return self._repository

    @property
    def storage_mode(self) -> str:
        return self._storage_mode

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error
    
    async def close(self):
        """Close database connections."""
        if self._client:
            self._client.close()
            self._client = None
        self._initialized = False
        self._storage_mode = "uninitialized"
        logger.info("Database connections closed")


def get_database() -> DatabaseManager:
    """Get the database manager instance."""
    return DatabaseManager.get_instance()


async def get_repository() -> Repository:
    """Get the repository instance."""
    db = get_database()
    await db.initialize()
    return db.repository


@asynccontextmanager
async def transaction():
    """
    Context manager for database transactions.
    Provides compatibility for transactional routing.
    """
    try:
        yield
    except Exception:
        raise
