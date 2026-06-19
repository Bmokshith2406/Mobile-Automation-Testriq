"""
API v1 Routes

This module aggregates all v1 API routes.
"""

from fastapi import APIRouter

from app.api.v1 import repair, executor, health

router = APIRouter()

# Include sub-routers
router.include_router(repair.router, prefix="/repair", tags=["repair"])
router.include_router(executor.router, prefix="/executor", tags=["executor"])
router.include_router(health.router, prefix="/health", tags=["health"])
