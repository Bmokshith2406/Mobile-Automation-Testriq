from typing import List, Dict, Any

from app.core.config import get_settings
from app.core.logging import logger
from app.db.mongo import get_methods_collection

from app.services.embeddings import embed_text


settings = get_settings()


# -------------------------------------------------------
# Search helper for METHOD dedupe
# -------------------------------------------------------

async def search_similar_methods(
    query: str,
    limit: int = 3,
) -> List[Dict[str, Any]]:
    """
    Uses ONLY the 10–12 word method summary as the query,
    embeds it and compares against stored main_vector
    (summary + raw method embeddings).

    MADL generation is NOT required for search.

    Returns:
    [
        {
          "document": {...},   # full Mongo METHOD document
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
    # Embed search summary
    # -------------------------------------------------------
    try:
        query_vector = embed_text(query)
    except Exception:
        logger.exception("Failed to embed method dedupe query")
        return []


    # -------------------------------------------------------
    # Vector search pipeline (NO CHANGE REQUIRED)
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
        logger.exception("Method dedupe search pipeline build failed")
        return []


    # -------------------------------------------------------
    # Execute search
    # -------------------------------------------------------
    try:
        col = get_methods_collection()

        results = await col.aggregate(
            pipeline
        ).to_list(length=limit)

        return results or []

    except Exception:
        logger.exception("Method dedupe vector search failed")
        return []
