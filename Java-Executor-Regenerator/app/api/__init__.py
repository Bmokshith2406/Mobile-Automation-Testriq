"""
API Module - Versioned API Routes

This module provides versioned API routing for the repair engine.
"""

from fastapi import APIRouter
from app.api.v1 import router as v1_routes

# API Version prefix
API_V1_PREFIX = "/api/v1"
API_V2_PREFIX = "/api/v2"

# Create versioned routers
v1_router = APIRouter(prefix=API_V1_PREFIX, tags=["v1"])
v2_router = APIRouter(prefix=API_V2_PREFIX, tags=["v2"])
v1_router.include_router(v1_routes)

__all__ = ["API_V1_PREFIX", "API_V2_PREFIX", "v1_router", "v2_router"]
