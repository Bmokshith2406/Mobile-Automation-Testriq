"""Soft delete utilities for data recovery and audit trails."""

from datetime import datetime
from typing import Any, Optional
from bson import ObjectId

from app.core.logging import logger
from app.core.exceptions import DatabaseError


def active_document_filter(field_prefix: str = "") -> dict[str, Any]:
    field_name = f"{field_prefix}deleted_at" if field_prefix else "deleted_at"
    return {
        "$or": [
            {field_name: None},
            {field_name: {"$exists": False}},
        ]
    }


async def soft_delete_by_id(
    collection,
    doc_id: ObjectId | str,
    deleted_by: Optional[str] = None,
) -> bool:
    """
    Soft delete a document by setting deleted_at timestamp.
    """
    try:
        if isinstance(doc_id, str):
            doc_id = ObjectId(doc_id)
        
        result = await collection.update_one(
            {"_id": doc_id},
            {
                "$set": {
                    "deleted_at": datetime.utcnow(),
                    "deleted_by": deleted_by,
                }
            }
        )
        
        if result.matched_count == 0:
            logger.warning(f"No document found to soft delete: {doc_id}")
            return False
        
        logger.info(f"Soft deleted document: {doc_id}")
        return True
        
    except Exception as e:
        logger.error(f"Error soft deleting document: {e}")
        raise DatabaseError(f"Failed to soft delete document: {e}", operation="soft_delete")


async def restore_deleted(
    collection,
    doc_id: ObjectId | str,
    restored_by: Optional[str] = None,
) -> bool:
    """
    Restore a soft-deleted document.
    """
    try:
        if isinstance(doc_id, str):
            doc_id = ObjectId(doc_id)
        
        result = await collection.update_one(
            {"_id": doc_id},
            {
                "$set": {
                    "deleted_at": None,
                    "restored_at": datetime.utcnow(),
                    "restored_by": restored_by,
                }
            }
        )
        
        if result.matched_count == 0:
            logger.warning(f"No document found to restore: {doc_id}")
            return False
        
        logger.info(f"Restored deleted document: {doc_id}")
        return True
        
    except Exception as e:
        logger.error(f"Error restoring document: {e}")
        raise DatabaseError(f"Failed to restore document: {e}", operation="restore")


async def list_deleted_documents(
    collection,
    limit: int = 100,
    skip: int = 0,
) -> list[dict]:
    """
    List all soft-deleted documents.
    """
    try:
        cursor = collection.find(
            {"deleted_at": {"$ne": None}},
            {"_id": 1, "method_name": 1, "deleted_at": 1, "deleted_by": 1}
        ).skip(skip).limit(limit)
        
        return await cursor.to_list(length=limit)
        
    except Exception as e:
        logger.error(f"Error listing deleted documents: {e}")
        raise DatabaseError(f"Failed to list deleted documents: {e}", operation="list_deleted")


async def permanently_delete_old(
    collection,
    days_ago: int = 30,
) -> int:
    """
    Permanently delete documents that were soft-deleted more than N days ago.
    """
    try:
        cutoff_date = datetime.utcnow()
        # Calculate timestamp from N days ago
        from datetime import timedelta
        cutoff_date = cutoff_date - timedelta(days=days_ago)
        
        result = await collection.delete_many(
            {
                "$and": [
                    {"deleted_at": {"$lt": cutoff_date}},
                    {"deleted_at": {"$ne": None}},
                ]
            }
        )
        
        logger.info(f"Permanently deleted {result.deleted_count} old soft-deleted documents")
        return result.deleted_count
        
    except Exception as e:
        logger.error(f"Error permanently deleting documents: {e}")
        raise DatabaseError(f"Failed to permanently delete documents: {e}", operation="permanent_delete")
