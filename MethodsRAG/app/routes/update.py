import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException

from app.core.analytics import log_api_call
from app.core.cache import cache_clear
from app.core.exceptions import DatabaseError, NotFoundError
from app.core.logging import logger
from app.core.rate_limiter import rate_limit_dependency
from app.core.security import verify_api_key
from app.core.validation import build_document_lookup
from app.db.mongo import get_methods_collection
from app.models.schemas import UpdateMethodRequest
from app.services.code_provenance import STORED_FRAMEWORK_FIELD, STORED_LANGUAGE_FIELD
from app.services.embeddings import embed_text

router = APIRouter()


@router.put("/update/{doc_id}")
async def update_method(
    doc_id: str,
    update_data: UpdateMethodRequest = Body(...),
    _: str = Depends(rate_limit_dependency),
    principal: dict = Depends(verify_api_key),
):
    """Update stored method metadata and documentation, reembedding when needed."""
    col = get_methods_collection()
    document_lookup = build_document_lookup(doc_id)

    try:
        existing_doc = await col.find_one(document_lookup)
    except Exception as err:
        logger.error(f"MongoDB find_one failed: {err}", exc_info=True)
        raise DatabaseError(f"Failed fetching method: {err}", operation="find_one")

    if existing_doc is None:
        raise NotFoundError("Method", identifier=doc_id)

    updated_doc = dict(existing_doc)
    doc_section = updated_doc.setdefault("method_documentation", {})
    should_reprocess = False

    for field in [
        "summary",
        "description",
        "intent",
        "applies",
        "returns",
        "owner",
        "example_usage",
        "reusable",
    ]:
        value = getattr(update_data, field, None)
        if value is not None:
            doc_section[field] = value
            should_reprocess = True

    if update_data.params is not None:
        doc_section["params"] = update_data.params
        should_reprocess = True

    if update_data.keywords is not None:
        doc_section["keywords"] = update_data.keywords
        should_reprocess = True

    if update_data.framework is not None:
        updated_doc[STORED_FRAMEWORK_FIELD] = update_data.framework
        updated_doc.pop("framework", None)

    if update_data.language is not None:
        updated_doc[STORED_LANGUAGE_FIELD] = update_data.language
        updated_doc.pop("language", None)

    if should_reprocess:
        try:
            raw_method = updated_doc.get("raw_method_code", "")
            summary = doc_section.get("summary", "")
            md_json = json.dumps(updated_doc["method_documentation"], sort_keys=True)

            summary_embedding, raw_method_embedding, madl_embedding, main_vector = await asyncio.gather(
                asyncio.to_thread(embed_text, summary),
                asyncio.to_thread(embed_text, raw_method),
                asyncio.to_thread(embed_text, md_json),
                asyncio.to_thread(embed_text, f"{summary} {raw_method}"),
            )

            if not all([summary_embedding, raw_method_embedding, madl_embedding, main_vector]):
                raise RuntimeError("Embedding generation returned empty vectors")

            updated_doc["summary_embedding"] = summary_embedding
            updated_doc["raw_method_embedding"] = raw_method_embedding
            updated_doc["madl_embedding"] = madl_embedding
            updated_doc["main_vector"] = main_vector
            doc_section["last_updated"] = datetime.now(timezone.utc).date().isoformat()
        except Exception as err:
            logger.exception(f"Embedding rebuild failed for method {doc_id}: {err}")
            raise HTTPException(
                status_code=500,
                detail="Failed rebuilding embeddings for method.",
            )

    updated_doc["updated_at"] = datetime.now(timezone.utc)

    try:
        await col.replace_one({"_id": existing_doc["_id"]}, updated_doc)
    except Exception as err:
        logger.exception(f"MongoDB replace_one failed: {err}")
        raise HTTPException(
            status_code=500,
            detail="Failed saving updated method.",
        )

    cache_clear()
    await log_api_call(
        endpoint=f"/api/update/{doc_id}",
        method="PUT",
        user=principal,
        payload=update_data.model_dump(exclude_none=True),
        extra={"updated_method_id": str(existing_doc["_id"])},
    )

    response_doc = dict(updated_doc)
    response_doc["id"] = str(response_doc["_id"])
    response_doc["framework"] = (
        response_doc.get(STORED_FRAMEWORK_FIELD) or response_doc.get("framework")
    )
    response_doc["language"] = (
        response_doc.get(STORED_LANGUAGE_FIELD) or response_doc.get("language")
    )
    for key in [
        "_id",
        "summary_embedding",
        "raw_method_embedding",
        "madl_embedding",
        "main_vector",
        STORED_FRAMEWORK_FIELD,
        STORED_LANGUAGE_FIELD,
    ]:
        response_doc.pop(key, None)

    logger.info(f"Updated method {doc_id}")
    return {
        "success": True,
        "message": f"Method {doc_id} updated successfully",
        "updated_method": response_doc,
    }
