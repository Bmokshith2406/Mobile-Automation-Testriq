from typing import Optional

from fastapi import APIRouter, UploadFile, File, Form, Request, BackgroundTasks

from app.routes.executor_routes.common import EXECUTOR_RESPONSES, _execute_python_file_for_framework

router = APIRouter()


@router.post(
    "/appium/run",
    summary="Execute an Appium Python script with runtime device options",
    description=(
        "Executes a generated Appium Python script. Appium hub and device "
        "matrix options are accepted only on this route. HTTP 200 means the "
        "execution process completed and returned an artifact ZIP; check "
        "X-Semantic-Status and execution_manifest.json inside the ZIP to know "
        "whether the test passed or failed. Local/VM Appium runs clean and "
        "relaunch the app by default; BrowserStack/Sauce runs stay "
        "non-destructive unless the matrix device explicitly opts in with "
        "clean_app_before_each_run and allow_destructive_app_reset."
    ),
    response_description="Execution artifact ZIP",
    tags=["executor"],
    responses=EXECUTOR_RESPONSES,
)
async def execute_appium_file(
    request: Request,
    script: UploadFile = File(..., description="Generated Appium Python script to execute"),
    appium_server_url: Optional[str] = Form(
        default=None,
        description="Optional per-run Appium hub URL override, for example BrowserStack or Sauce.",
    ),
    appium_device_filter: Optional[str] = Form(
        default=None,
        description="Optional comma-separated Appium runtime device labels/slugs/device names to run.",
    ),
    appium_device_matrix: Optional[str] = Form(
        default=None,
        description="Optional JSON Appium runtime device matrix/capabilities.",
    ),
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    return await _execute_python_file_for_framework(
        request=request,
        script=script,
        framework="appium",
        background_tasks=background_tasks,
        appium_server_url=appium_server_url,
        appium_device_filter=appium_device_filter,
        appium_device_matrix=appium_device_matrix,
    )
