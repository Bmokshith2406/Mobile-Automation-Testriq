import uuid
from fastapi import FastAPI, Request

from app.core.logging import logger
from app.core.resilience import circuit_states, CircuitState
from app.db.mongo import connect_to_mongo, disconnect_from_mongo
from app.services.http_client import init_client, close_client
from app.routes.health import router as health_router
from app.routes.metrics import router as metrics_router
from app.routes.orchestrator import router as orchestrator_router

app = FastAPI(title="Automation Orchestrator", version="2.0.0")

@app.on_event("startup")
async def startup():
    await init_client()
    await connect_to_mongo()
    # warm up circuit states
    for svc in ("generator", "executor", "reporter"):
        circuit_states.setdefault(svc, CircuitState())

@app.on_event("shutdown")
async def shutdown():
    await disconnect_from_mongo()
    await close_client()

@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id

    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response

# Include Routers
app.include_router(health_router, tags=["health"])
app.include_router(metrics_router, tags=["metrics"])
app.include_router(orchestrator_router, tags=["orchestrator"])
