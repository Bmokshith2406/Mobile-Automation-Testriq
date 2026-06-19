from typing import List, Dict, Any

from app.core.config import get_settings
from app.core.logging import logger
from app.db.mongo import get_testcase_collection

from app.services.embeddings import embed_text

settings = get_settings()


# -------------------------------------------------------
# Search helper for dedupe (reuse vector DB)
# -------------------------------------------------------

async def search_similar_testcases(
    query: str,
    limit: int = 3,
) -> List[Dict[str, Any]]:
    """
    Runs a semantic search using the dedupe summary as a query
    and returns the top-k most similar existing test cases.

    Returns structure:
    [
        {
          "document": {...},   # full Mongo document
          "score": <float>     # vector similarity score
        },
        ...
    ]
    """

    # -------------------------------------------------------
    # Safety guard
    # -------------------------------------------------------

    try:
        if not query or not query.strip():
            return []
    except Exception:
        return []


    # -------------------------------------------------------
    # Embed query
    # -------------------------------------------------------

    try:
        query_vector = embed_text(query)
    except Exception:
        logger.exception("Failed to embed dedupe query")
        return []


    # -------------------------------------------------------
    # Vector search pipeline
    # -------------------------------------------------------

    try:

        pipeline = [
            {
                "$vectorSearch": {
                    "index": settings.VECTOR_INDEX_NAME,
                    "path": "main_vector",
                    "queryVector": query_vector,
                    "numCandidates": 50,
                    "limit": limit,
                }
            },
            {
                "$project": {
                    "score": {"$meta": "vectorSearchScore"},
                    "document": "$$ROOT",
                }
            }
        ]

    except Exception:
        logger.exception("Dedupe search pipeline build failed")
        return []


    # -------------------------------------------------------
    # Execute search
    # -------------------------------------------------------

    try:
        col = get_testcase_collection()

        results = await col.aggregate(
            pipeline
        ).to_list(length=limit)

        return results or []

    except Exception:
        logger.exception("Dedupe vector search failed")
        return []
