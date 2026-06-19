import time
from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
import app.services.http_client as http_client
from app.core.resilience import circuit_states

router = APIRouter()

@router.get("/health", response_class=PlainTextResponse)
async def health():
    return "ok"

@router.get("/ready", response_class=PlainTextResponse)
async def ready():
    # If HTTP client initialized and circuits not entirely open
    client_ready = http_client._app_client is not None
    any_open = any(
        cs.open_until and cs.open_until > time.time() for cs in circuit_states.values()
    )
    if client_ready and not any_open:
        return "ready"
    raise HTTPException(status_code=503, detail="not ready")
