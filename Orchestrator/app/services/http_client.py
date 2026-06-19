import asyncio
import httpx
from typing import Optional
from app.core.config import settings
from app.core.logging import logger

_app_client: Optional[httpx.AsyncClient] = None
_concurrency_semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_RUNS)

async def get_client() -> httpx.AsyncClient:
    global _app_client
    if _app_client is None:
        raise RuntimeError("HTTP client not initialized")
    return _app_client

async def init_client():
    global _app_client
    _app_client = httpx.AsyncClient(
        timeout=httpx.Timeout(settings.DOWNSTREAM_TIMEOUT_SECONDS),
        follow_redirects=True,
    )
    logger.info("HTTP client initialized", extra={"request_id": "-"})

async def close_client():
    global _app_client
    if _app_client:
        await _app_client.aclose()
        logger.info("HTTP client closed", extra={"request_id": "-"})

def get_semaphore() -> asyncio.Semaphore:
    return _concurrency_semaphore
