from datetime import datetime, timezone
import io
import time
from typing import Any, Dict, Optional

from bson import ObjectId
from gridfs.errors import NoFile
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorGridFSBucket
from pymongo import ASCENDING, DESCENDING, TEXT
from pymongo.errors import PyMongoError

from app.core.config import settings
from app.core.errors import database_error, not_found_error, validation_error
from app.core.logging import get_logger
from app.core.metrics import Metrics

logger = get_logger(__name__)

_client: Optional[AsyncIOMotorClient] = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _validate_object_id(report_id: str) -> ObjectId:
    if not ObjectId.is_valid(report_id):
        raise validation_error("Invalid report ID format")
    return ObjectId(report_id)


def get_db():
    if not _client:
        raise database_error("MongoDB client not initialized")
    return _client[settings.MONGODB_DB_NAME]


def get_bucket() -> AsyncIOMotorGridFSBucket:
    return AsyncIOMotorGridFSBucket(get_db(), bucket_name=settings.MONGODB_BUCKET_NAME)


def get_files_collection():
    return get_db()[f"{settings.MONGODB_BUCKET_NAME}.files"]


def get_chunks_collection():
    return get_db()[f"{settings.MONGODB_BUCKET_NAME}.chunks"]


async def connect_to_mongo() -> None:
    global _client

    if not settings.mongo_enabled:
        logger.info("MongoDB connection skipped because MONGO_ENABLED=false")
        return

    try:
        _client = AsyncIOMotorClient(
            settings.MONGODB_URI,
            maxPoolSize=50,
            minPoolSize=5,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
            socketTimeoutMS=5000,
            retryWrites=True,
        )
        await _client.admin.command("ping")
        logger.info("MongoDB connected successfully")
    except PyMongoError as exc:
        logger.exception("MongoDB connection failed: %s", exc)
        _client = None
        raise database_error("MongoDB connection failed") from exc


async def disconnect_from_mongo() -> None:
    global _client

    if _client:
        _client.close()
        _client = None
        logger.info("MongoDB disconnected")


async def ensure_indexes() -> None:
    if not settings.mongo_enabled:
        return

    try:
        files_collection = get_files_collection()
        await files_collection.create_index([("metadata.name", ASCENDING)], name="report_name_idx")
        await files_collection.create_index([("uploadDate", ASCENDING)], name="upload_date_idx")
        await files_collection.create_index([("metadata.name", TEXT)], name="report_name_text_idx")
        logger.info("MongoDB indexes ensured")
    except PyMongoError as exc:
        logger.error("Index creation failed", extra={"error": str(exc)})
        raise database_error("Failed to create indexes") from exc


async def ping_db() -> bool:
    if not settings.mongo_enabled:
        return True

    if not _client:
        return False

    try:
        start = time.perf_counter()
        await _client.admin.command("ping")
        duration = time.perf_counter() - start
        Metrics.MONGO_PING_DURATION.observe(duration)
        return True
    except Exception as exc:
        logger.warning("MongoDB ping failed", extra={"error": str(exc)})
        return False


def _serialize_file_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    metadata = doc.get("metadata", {})
    created_at = metadata.get("created_at") or doc.get("uploadDate")
    updated_at = metadata.get("updated_at") or created_at

    return {
        "_id": str(doc["_id"]),
        "name": metadata.get("name", doc.get("filename", "report")),
        "filename": doc.get("filename"),
        "content_type": metadata.get("content_type", "text/html"),
        "created_at": created_at,
        "updated_at": updated_at,
        "size": doc.get("length", metadata.get("size")),
    }


async def insert_report(
    *,
    name: str,
    filename: str,
    html_bytes: bytes,
    content_type: str,
) -> Dict[str, Any]:
    if not settings.mongo_enabled:
        raise database_error("MongoDB storage is disabled")

    bucket = get_bucket()
    file_id = ObjectId()
    now = _utcnow()

    metadata = {
        "name": name,
        "created_at": now,
        "updated_at": now,
        "content_type": content_type,
        "size": len(html_bytes),
    }

    try:
        await bucket.upload_from_stream_with_id(
            file_id,
            filename,
            io.BytesIO(html_bytes),
            metadata=metadata,
        )
        logger.info(
            "Report stored in GridFS",
            extra={"report_id": str(file_id), "size": len(html_bytes)},
        )
        return {
            "report_id": str(file_id),
            "name": name,
            "created_at": now,
            "size": len(html_bytes),
            "content_type": content_type,
        }
    except PyMongoError as exc:
        logger.exception("Insert failed: %s", exc)
        raise database_error("Failed to insert report") from exc


async def get_report_by_id(report_id: str) -> Optional[Dict[str, Any]]:
    if not settings.mongo_enabled:
        raise database_error("MongoDB storage is disabled")

    try:
        obj_id = _validate_object_id(report_id)
        doc = await get_files_collection().find_one({"_id": obj_id})
        if not doc:
            return None
        return _serialize_file_doc(doc)
    except PyMongoError as exc:
        logger.error("Fetch failed", extra={"report_id": report_id, "error": str(exc)})
        raise database_error("Failed to fetch report") from exc


async def get_report_content(report_id: str) -> bytes:
    if not settings.mongo_enabled:
        raise database_error("MongoDB storage is disabled")

    obj_id = _validate_object_id(report_id)
    bucket = get_bucket()

    try:
        download_stream = await bucket.open_download_stream(obj_id)
        return await download_stream.read()
    except NoFile as exc:
        raise not_found_error(message=f"Report {report_id} not found") from exc
    except PyMongoError as exc:
        logger.error("Download failed", extra={"report_id": report_id, "error": str(exc)})
        raise database_error("Failed to download report") from exc


async def list_reports(*, skip: int = 0, limit: int = 50) -> list[Dict[str, Any]]:
    if not settings.mongo_enabled:
        raise database_error("MongoDB storage is disabled")

    safe_skip = max(0, int(skip))
    safe_limit = min(max(1, int(limit)), 500)

    try:
        cursor = (
            get_files_collection()
            .find({})
            .sort("uploadDate", DESCENDING)
            .skip(safe_skip)
            .limit(safe_limit)
        )
        return [_serialize_file_doc(doc) async for doc in cursor]
    except PyMongoError as exc:
        logger.error("Report list failed", extra={"error": str(exc)})
        raise database_error("Failed to list reports") from exc


async def delete_report_by_id(report_id: str) -> bool:
    if not settings.mongo_enabled:
        raise database_error("MongoDB storage is disabled")

    obj_id = _validate_object_id(report_id)
    bucket = get_bucket()

    try:
        existing = await get_files_collection().find_one({"_id": obj_id}, {"_id": 1})
        if not existing:
            return False
        await bucket.delete(obj_id)
        logger.warning("Report deleted", extra={"report_id": report_id})
        return True
    except NoFile:
        return False
    except PyMongoError as exc:
        logger.error("Report delete failed", extra={"report_id": report_id, "error": str(exc)})
        raise database_error("Failed to delete report") from exc


async def delete_all_reports() -> int:
    if not settings.mongo_enabled:
        raise database_error("MongoDB storage is disabled")

    try:
        files_collection = get_files_collection()
        chunks_collection = get_chunks_collection()
        file_ids = [doc["_id"] async for doc in files_collection.find({}, {"_id": 1})]
        if not file_ids:
            return 0

        await chunks_collection.delete_many({"files_id": {"$in": file_ids}})
        files_result = await files_collection.delete_many({"_id": {"$in": file_ids}})
        logger.warning("All reports deleted", extra={"deleted_reports": files_result.deleted_count})
        return int(files_result.deleted_count)
    except PyMongoError as exc:
        logger.error("Delete all reports failed", extra={"error": str(exc)})
        raise database_error("Failed to delete reports") from exc
