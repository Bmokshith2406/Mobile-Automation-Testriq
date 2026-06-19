import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.database import get_repository

router = APIRouter()
logger = logging.getLogger("api.executor")


@router.get(
    "/stats",
    summary="Get execution statistics",
    description="Returns statistics about script executions.",
    tags=["executor"],
)
async def get_execution_stats():
    try:
        repo = await get_repository()
        stats = await repo.get_execution_stats()
        return JSONResponse(content=stats)
    except Exception as e:
        logger.warning("Failed to get execution stats: %s", e)
        return JSONResponse(content={"error": "Stats unavailable"})
