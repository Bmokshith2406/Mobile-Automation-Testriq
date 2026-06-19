from typing import Optional, Any, Iterable, Dict, List
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core.config import get_settings
from app.core.logging import logger

settings = get_settings()

_mongo_client: Optional[AsyncIOMotorClient] = None


# ==========================================================
# SAFE OBJECTID
# ==========================================================

def safe_object_id(id_str: str) -> ObjectId:
    """Safely convert string to ObjectId."""
    try:
        return ObjectId(id_str)
    except Exception:
        raise ValueError(f"Invalid ObjectId: {id_str}")


def expand_id_candidates(document_id: Any) -> List[Any]:
    """
    Return all practical Mongo _id representations for a document id.

    New writes use string UUIDs, but legacy data may still use ObjectId.
    These helpers let read/update/delete paths work with both safely.
    """
    if document_id is None:
        return []

    candidates: List[Any] = []
    seen = set()

    def _append(value: Any):
        marker = f"{type(value).__name__}:{value}"
        if marker not in seen:
            seen.add(marker)
            candidates.append(value)

    if isinstance(document_id, ObjectId):
        _append(document_id)
        _append(str(document_id))
        return candidates

    value = str(document_id).strip()
    if not value:
        return []

    _append(value)

    if ObjectId.is_valid(value):
        _append(ObjectId(value))

    return candidates


def build_id_query(document_id: Any) -> Dict[str, Any]:
    """Build a Mongo query that matches string UUID and legacy ObjectId values."""
    candidates = expand_id_candidates(document_id)

    if not candidates:
        return {"_id": None}

    if len(candidates) == 1:
        return {"_id": candidates[0]}

    return {"_id": {"$in": candidates}}


def build_ids_in_query(document_ids: Iterable[Any]) -> Dict[str, Any]:
    """Build an $in query for multiple ids with mixed string/ObjectId support."""
    expanded: List[Any] = []
    seen = set()

    for document_id in document_ids or []:
        for candidate in expand_id_candidates(document_id):
            marker = f"{type(candidate).__name__}:{candidate}"
            if marker not in seen:
                seen.add(marker)
                expanded.append(candidate)

    return {"_id": {"$in": expanded}}


# ==========================================================
# CLIENT
# ==========================================================

def get_client() -> AsyncIOMotorClient:
    global _mongo_client

    try:
        if _mongo_client is None:
            logger.info("Initializing MongoDB Atlas client")

            _mongo_client = AsyncIOMotorClient(
                settings.MONGO_CONNECTION_STRING,
                serverSelectionTimeoutMS=5000,
                connectTimeoutMS=5000,
                socketTimeoutMS=10000,
                retryWrites=True,
                retryReads=True,
                maxPoolSize=50,
                minPoolSize=10,
                tls=True,
            )

            logger.info("MongoDB client initialized")

        return _mongo_client

    except Exception as err:
        logger.exception(f"MongoDB client initialization failed: {err}")
        raise


# ==========================================================
# DATABASE
# ==========================================================

def get_db() -> AsyncIOMotorDatabase:
    try:
        client = get_client()
        return client[settings.DB_NAME]
    except Exception as err:
        logger.exception(f"Database connection failed: {err}")
        raise


# ==========================================================
# HEALTH CHECK
# ==========================================================

async def ping_db():
    try:
        client = get_client()

        await client.admin.command("ping")

        # Force server selection validation
        await client.server_info()

        logger.info("MongoDB ping successful")

    except Exception as err:
        logger.exception(f"MongoDB ping failed: {err}")
        raise


async def is_mongodb_healthy() -> bool:
    """Check MongoDB connection health."""
    try:
        await ping_db()
        return True
    except Exception:
        return False


# ==========================================================
# CLOSE CONNECTION
# ==========================================================

async def close_db():
    global _mongo_client

    if _mongo_client is not None:
        try:
            _mongo_client.close()
            logger.info("MongoDB connection closed")
        except Exception as err:
            logger.warning(f"MongoDB close error: {err}")
        finally:
            _mongo_client = None


# ==========================================================
# INDEX CREATION
# ==========================================================

async def create_indexes():
    """Create indexes for performance."""
    try:
        db = get_db()

        # Testcases
        col_tc = db[settings.COLLECTION_TESTCASES]

        await col_tc.create_index("Test Case ID")
        await col_tc.create_index("Feature")
        await col_tc.create_index("CreatedAt")
        await col_tc.create_index("UpdatedAt")
        await col_tc.create_index("Popularity")
        await col_tc.create_index("playwright_script_id")
        await col_tc.create_index([("Tags", 1)], sparse=True)
        await col_tc.create_index([("Priority", 1)], sparse=True)
        await col_tc.create_index([("Platform", 1)], sparse=True)
        await col_tc.create_index([("deleted_at", 1)], sparse=True)

        logger.info("Test case indexes created")

        # Scripts
        col_scripts = db[settings.COLLECTION_SCRIPTS]

        await col_scripts.create_index("testcase_id")
        await col_scripts.create_index("testcase_object_id")
        await col_scripts.create_index("created_at")
        await col_scripts.create_index([("deleted_at", 1)], sparse=True)

        logger.info("Script indexes created")



        # Audit
        col_audit = db[settings.COLLECTION_AUDIT]

        await col_audit.create_index([("timestamp", -1)])
        await col_audit.create_index([("user_id", 1), ("timestamp", -1)])

        logger.info("Audit indexes created")

        # Ingestion jobs
        col_jobs = db[settings.COLLECTION_INGESTION_JOBS]

        await col_jobs.create_index("status")
        await col_jobs.create_index("created_at")
        await col_jobs.create_index("updated_at")
        await col_jobs.create_index([("requested_by.id", 1), ("created_at", -1)])

        logger.info("Ingestion job indexes created")

    except Exception as err:
        logger.warning(f"Index creation failed: {err}")


# ==========================================================
# TRANSACTION SESSION
# ==========================================================

@asynccontextmanager
async def transaction_session():
    """MongoDB transaction context manager."""
    client = get_client()

    async with await client.start_session() as session:
        async with session.start_transaction():
            yield session


# ==========================================================
# SOFT DELETE
# ==========================================================

async def soft_delete_testcase(testcase_id: str, session=None):
    """Soft delete a test case."""
    col = get_testcase_collection()

    result = await col.update_one(
        build_id_query(testcase_id),
        {
            "$set": {
                "deleted_at": datetime.now(timezone.utc),
                "UpdatedAt": datetime.now(timezone.utc),
            }
        },
        session=session,
    )

    return result.modified_count > 0


async def soft_delete_script(script_id: str, session=None):
    """Soft delete a script."""
    col = get_playwright_scripts_collection()

    result = await col.update_one(
        build_id_query(script_id),
        {
            "$set": {
                "deleted_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }
        },
        session=session,
    )

    return result.modified_count > 0


async def restore_testcase(testcase_id: str, session=None):
    """Restore soft-deleted testcase."""
    col = get_testcase_collection()

    result = await col.update_one(
        build_id_query(testcase_id),
        {
            "$unset": {"deleted_at": ""},
            "$set": {"UpdatedAt": datetime.now(timezone.utc)},
        },
        session=session,
    )

    return result.modified_count > 0


# ==========================================================
# ACTIVE DOCUMENT FILTER
# ==========================================================

def active_documents_filter():
    """Filter to exclude soft deleted records."""
    return {
        "$or": [
            {"deleted_at": {"$exists": False}},
            {"deleted_at": None},
        ]
    }


# ==========================================================
# COLLECTION GETTERS
# ==========================================================

def get_testcase_collection():
    try:
        db = get_db()
        return db[settings.COLLECTION_TESTCASES]
    except Exception as err:
        logger.exception(f"Failed to get testcase collection: {err}")
        raise


def get_playwright_scripts_collection():
    try:
        db = get_db()
        return db[settings.COLLECTION_SCRIPTS]
    except Exception as err:
        logger.exception(f"Failed to get scripts collection: {err}")
        raise





def get_audit_collection():
    try:
        db = get_db()
        return db[settings.COLLECTION_AUDIT]
    except Exception as err:
        logger.exception(f"Failed to get audit collection: {err}")
        raise


def get_ingestion_jobs_collection():
    try:
        db = get_db()
        return db[settings.COLLECTION_INGESTION_JOBS]
    except Exception as err:
        logger.exception(f"Failed to get ingestion jobs collection: {err}")
        raise
