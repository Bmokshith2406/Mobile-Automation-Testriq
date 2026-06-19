from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.analytics import log_api_call
from app.core.cache import cache_clear
from app.core.logging import logger
from app.core.metrics import Metrics
from app.core.rate_limiter import rate_limit_dependency
from app.core.security import verify_admin_api_key
from app.core.soft_delete import active_document_filter
from app.core.validation import build_document_lookup, validate_pagination, validate_string_field
from app.db.mongo import get_db, get_methods_collection
from app.core.config import get_settings

router = APIRouter()
settings = get_settings()
ALLOWED_SORT_FIELDS = {"method_name", "created_at", "CreatedAt", "updated_at", "popularity", "Popularity"}


def _normalize_document(doc: dict) -> dict:
    normalized = dict(doc)
    normalized["id"] = str(normalized.get("_id"))
    normalized.pop("_id", None)
    return normalized


@router.get("/get-all-methods")
async def get_all_methods(
    skip: int = 0,
    limit: int = 50,
    sort_by: str = "method_name",
    order: int = 1,
    _: str = Depends(rate_limit_dependency),
    principal: dict = Depends(verify_admin_api_key),
):
    col = get_methods_collection()
    limit, skip = validate_pagination(limit, skip)
    sort_by = validate_string_field(sort_by, "sort_by", min_length=1, max_length=50)

    if sort_by not in ALLOWED_SORT_FIELDS:
        raise HTTPException(
            status_code=400,
            detail=f"sort_by must be one of: {', '.join(sorted(ALLOWED_SORT_FIELDS))}",
        )

    projection = {
        "summary_embedding": 0,
        "raw_method_embedding": 0,
        "madl_embedding": 0,
        "main_vector": 0,
    }
    sort_order = -1 if order < 0 else 1

    try:
        cursor = (
            col.find(active_document_filter(), projection)
            .sort(sort_by, sort_order)
            .skip(skip)
            .limit(limit)
        )
        methods = [_normalize_document(doc) async for doc in cursor]
    except Exception as err:
        logger.exception(f"Mongo cursor build failed: {err}")
        raise HTTPException(status_code=500, detail="Failed to query database.")

    return {
        "success": True,
        "count": len(methods),
        "skip": skip,
        "limit": limit,
        "methods": methods,
    }


@router.post("/delete-all")
async def delete_all_data(
    confirm: bool = Query(False, description="Pass true to confirm deletion"),
    _: str = Depends(rate_limit_dependency),
    principal: dict = Depends(verify_admin_api_key),
):
    col = get_methods_collection()

    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Confirmation required. Pass ?confirm=true to delete all data.",
        )

    try:
        result = await col.delete_many({})
        cache_clear()
        await log_api_call(
            endpoint="/api/delete-all",
            method="POST",
            user=principal,
            payload={"confirm": confirm},
            extra={"deleted_documents": result.deleted_count},
        )
        logger.warning(
            f"Cleared collection '{settings.COLLECTION_SCRIPT_METHODS}' | Deleted {result.deleted_count} documents"
        )
        return {
            "success": True,
            "collection": settings.COLLECTION_SCRIPT_METHODS,
            "deleted_documents": result.deleted_count,
            "message": "All documents cleared from collection.",
        }
    except Exception:
        logger.error("Delete failed", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while deleting data.")


@router.delete("/method/{doc_id}")
async def delete_method(
    doc_id: str,
    _: str = Depends(rate_limit_dependency),
    principal: dict = Depends(verify_admin_api_key),
):
    col = get_methods_collection()

    try:
        res = await col.delete_one(build_document_lookup(doc_id))
        if res.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Method not found")

        cache_clear()
        await log_api_call(
            endpoint=f"/api/method/{doc_id}",
            method="DELETE",
            user=principal,
            payload={"doc_id": doc_id},
        )
        logger.info(f"Deleted method {doc_id}")
        return {
            "success": True,
            "message": f"Method {doc_id} deleted",
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error deleting method {doc_id}: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete method")


@router.get("/metrics")
async def get_metrics(
    _: str = Depends(rate_limit_dependency),
    principal: dict = Depends(verify_admin_api_key),
):
    try:
        db = get_db()
        audit_col = db[settings.COLLECTION_AUDIT]
    except Exception as err:
        logger.exception(f"Failed resolving DB collections: {err}")
        raise HTTPException(status_code=500, detail="DB resolution failed.")

    since = datetime.now(timezone.utc) - timedelta(days=1)

    try:
        queries_today = await audit_col.count_documents(
            {
                "endpoint": "/api/search",
                "timestamp": {"$gte": since.replace(tzinfo=None)},
            }
        )

        top_methods_pipeline = [
            {"$match": {"endpoint": "/api/search", "timestamp": {"$gte": since.replace(tzinfo=None)}}},
            {"$unwind": "$extra.top_method_names"},
            {
                "$group": {
                    "_id": "$extra.top_method_names",
                    "count": {"$sum": 1},
                }
            },
            {"$sort": {"count": -1}},
            {"$limit": 5},
        ]
        top_methods = await audit_col.aggregate(top_methods_pipeline).to_list(length=5)
    except Exception as err:
        logger.exception(f"Metrics aggregation failed: {err}")
        raise HTTPException(status_code=500, detail="Failed computing metrics.")

    snapshot = Metrics.get_metrics_snapshot()
    return {
        "queries_today": queries_today,
        "top_methods": [item["_id"] for item in top_methods if item.get("_id")],
        "application_metrics": snapshot,
    }


@router.get("/get-by-id/{doc_id}")
async def get_method_by_id(
    doc_id: str,
    _: str = Depends(rate_limit_dependency),
    principal: dict = Depends(verify_admin_api_key),
):
    col = get_methods_collection()

    try:
        document_lookup = {
            "$and": [
                build_document_lookup(doc_id),
                active_document_filter(),
            ]
        }
        doc = await col.find_one(document_lookup)

        if not doc:
            raise HTTPException(status_code=404, detail="Method not found")

        return {
            "success": True,
            "method": _normalize_document(doc),
        }
    except HTTPException:
        raise
    except Exception as err:
        logger.error(f"Error fetching method by id: {err}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch method")
