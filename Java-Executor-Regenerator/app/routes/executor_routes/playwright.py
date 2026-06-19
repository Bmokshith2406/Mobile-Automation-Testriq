from fastapi import APIRouter, UploadFile, File, Request, BackgroundTasks

from app.routes.executor_routes.common import EXECUTOR_RESPONSES, _execute_python_file_for_framework

router = APIRouter()

@router.post(
    "/playwright/run",
    summary="Execute a Playwright Python script with bounded self-healing",
    description="Executes a generated Playwright Python script and returns a ZIP artifact.",
    response_description="Execution artifact ZIP",
    tags=["executor"],
    responses=EXECUTOR_RESPONSES,
)
async def execute_playwright_file(
    request: Request,
    script: UploadFile = File(..., description="Generated Playwright Python script to execute"),
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    return await _execute_python_file_for_framework(
        request=request,
        script=script,
        framework="playwright",
        background_tasks=background_tasks,
    )
