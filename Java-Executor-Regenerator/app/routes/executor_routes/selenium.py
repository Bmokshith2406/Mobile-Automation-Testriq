from fastapi import APIRouter, UploadFile, File, Request, BackgroundTasks

from app.routes.executor_routes.common import EXECUTOR_RESPONSES, _execute_python_file_for_framework

router = APIRouter()

@router.post(
    "/selenium/run",
    summary="Execute a Selenium Python script with bounded self-healing",
    description="Executes a generated Selenium Python script and returns a ZIP artifact.",
    response_description="Execution artifact ZIP",
    tags=["executor"],
    responses=EXECUTOR_RESPONSES,
)
async def execute_selenium_file(
    request: Request,
    script: UploadFile = File(..., description="Generated Selenium Python script to execute"),
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    return await _execute_python_file_for_framework(
        request=request,
        script=script,
        framework="selenium",
        background_tasks=background_tasks,
    )
