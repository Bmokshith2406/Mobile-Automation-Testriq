from fastapi import APIRouter

from app.routes.executor_routes import appium, cypress, playwright, selenium, stats

router = APIRouter()
router.include_router(playwright.router)
router.include_router(selenium.router)
router.include_router(cypress.router)
router.include_router(appium.router)
router.include_router(stats.router)

__all__ = ["router"]
