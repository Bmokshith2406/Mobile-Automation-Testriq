"""
Executor API Route - Production Grade

Features:
- Self-healing execution
- Metrics integration
- Database persistence
- Sandbox execution support
- Enhanced error handling
"""
import zipfile
from fastapi.responses import FileResponse
from fastapi import HTTPException, UploadFile, Request, BackgroundTasks
from fastapi.responses import JSONResponse
import logging
import os
import time
import asyncio
import shutil
import json
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

async def cleanup_run_files(zip_path: Path, temp_run_dirs: list[str], delete_zip: bool = True):
    # Allow time for FastAPI to finish streaming the response zip file
    await asyncio.sleep(2)
    if delete_zip:
        try:
            if zip_path.exists():
                zip_path.unlink()
                logger.info("Cleaned up temporary zip response: %s", zip_path)
        except Exception as e:
            logger.warning("Failed to clean up temporary zip: %s", e)
        
    for run_dir_str in temp_run_dirs:
        try:
            run_path = Path(run_dir_str).resolve()
            # Double check it is actually a temporary run folder under runs/ to prevent accidental deletions
            if run_path.exists() and "runs" in run_path.parts:
                shutil.rmtree(run_path)
                logger.info("Cleaned up temporary run directory: %s", run_path)
        except Exception as e:
            logger.warning("Failed to clean up temporary run directory %s: %s", run_dir_str, e)
import asyncio
import uuid
import hashlib
import tempfile

from app.core.utils import set_correlation_id


from app.executors import AsyncPythonExecutor
from app.services.auto_repair_trigger import AutoRepairTrigger
from app.services.repair_service import RepairService
from app.services.repair_pipeline import repair_pipeline_safe
from app.services.script_patcher import ScriptPatcher
from app.services.execution_orchestrator import (
    SelfHealingExecutorOrchestrator,
    ExecutorOrchestratorConfig,
)
from app.core.config import get_settings
from app.core.metrics import get_metrics
from app.core.tracing import trace, SpanKind
from app.core.database import get_repository, ExecutionRecord
from app.core.security import SandboxGuard

logger = logging.getLogger("api.executor")
settings = get_settings()

# --------------------------------------------------
# Singletons
# --------------------------------------------------

_executor = AsyncPythonExecutor(
    timeout_seconds=settings.EXECUTOR_TIMEOUT_SECONDS,
    base_work_dir=settings.EXECUTOR_BASE_WORK_DIR,
)
# Bounded concurrency control
MAX_CONCURRENT_REPAIRS = 5
repair_semaphore = asyncio.Semaphore(MAX_CONCURRENT_REPAIRS)

_repair_service = RepairService(
    semaphore=repair_semaphore,
    pipeline_fn=repair_pipeline_safe
)
_repair_trigger = AutoRepairTrigger()
_patcher = ScriptPatcher()
_sandbox_guard = SandboxGuard()

_orchestrator = SelfHealingExecutorOrchestrator(
    executor=_executor,
    repair_trigger=_repair_trigger,
    repair_service=_repair_service,
    patcher=_patcher,
    config=ExecutorOrchestratorConfig(),
)

# --------------------------------------------------
# API Routes
# --------------------------------------------------

EXECUTOR_RESPONSES = {
    200: {"description": "Execution completed (check X-Semantic-Status for result)"},
    400: {"description": "Invalid request (not a .py file or invalid Appium runtime options)"},
    403: {"description": "Script rejected by sandbox guard"},
    500: {"description": "Internal execution error"},
}


@trace(name="executor.execute", kind=SpanKind.SERVER)
async def _execute_python_file_for_framework(
    *,
    request: Request,
    script: UploadFile,
    framework: str,
    background_tasks: BackgroundTasks,
    appium_server_url: Optional[str] = None,
    appium_device_filter: Optional[str] = None,
    appium_device_matrix: Optional[str] = None,
):
    """
    Execute a Python file with bounded self-healing for one selected framework.

    This endpoint:
    - Executes the provided Python script
    - On semantic failure, attempts bounded step-level repair
    - Applies at most one patch per iteration
    - Re-runs script from scratch after patch
    - Returns final execution result

    IMPORTANT:
    - Orchestrator controls execution bounds
    - Semantic status is resolved ONLY via status.txt
    - Route NEVER infers success/failure
    - Route framework is the source of truth for repair behavior
    """

    request_id = getattr(request.state, "request_id", None) or uuid.uuid4().hex[:12]
    set_correlation_id(request_id)
    start_ts = time.perf_counter()
    metrics = get_metrics()

    logger.info(
        "EXEC_START | request_id=%s | framework=%s | filename=%s",
        request_id,
        framework,
        script.filename,
    )

    if not settings.ENABLE_SANDBOX_EXECUTION and not settings.is_development:
        logger.error(
            "EXEC_REJECTED | request_id=%s | reason=sandbox_disabled",
            request_id,
        )
        metrics.script_executions_total.inc(status="rejected")
        raise HTTPException(
            status_code=503,
            detail="Executor sandbox is disabled",
        )

    # Validate file type (.py for Playwright/Selenium/Appium, .js for Cypress)
    if not script.filename or not (
        script.filename.endswith(".py") or script.filename.endswith(".js")
    ):
        metrics.script_executions_total.inc(status="rejected")
        raise HTTPException(
            status_code=400,
            detail="Only .py and .js files are supported",
        )

    try:
        script_content = await script.read()
        try:
            script_text = script_content.decode("utf-8")
        except UnicodeDecodeError:
            metrics.script_executions_total.inc(status="rejected")
            raise HTTPException(
                status_code=400,
                detail="Script must be UTF-8 encoded text",
            )
        script_hash = hashlib.sha256(script_content).hexdigest()[:12]

        # Sandbox validation (if enabled)
        if settings.ENABLE_SANDBOX_EXECUTION:
            is_safe, reason = _sandbox_guard.validate_script(script_text)
            if not is_safe:
                logger.warning(
                    "EXEC_REJECTED | request_id=%s | reason=%s",
                    request_id,
                    reason,
                )
                metrics.script_executions_total.inc(status="rejected")
                raise HTTPException(
                    status_code=403,
                    detail=f"Script rejected by sandbox: {reason}",
                )

        # Check self-healing feature flag
        if not settings.ENABLE_SELF_HEALING:
            logger.info(
                "EXEC_NO_HEALING | request_id=%s | self_healing=disabled",
                request_id,
            )

        appium_devices: list[dict[str, Any]] = []
        runtime_env: dict[str, str] = {}

        if framework == "appium":
            if not _looks_like_appium_script(script_text):
                logger.warning(
                    "APPIUM_ROUTE_SCRIPT_HEURISTIC_MISMATCH | request_id=%s | filename=%s",
                    request_id,
                    script.filename,
                )
            runtime_env = _build_appium_runtime_env(
                appium_server_url=appium_server_url,
                appium_device_filter=None,
                appium_device_matrix=None,
            )
            appium_devices = _select_appium_runtime_devices(
                appium_device_matrix=appium_device_matrix,
                appium_device_filter=appium_device_filter,
            )

        with tempfile.TemporaryDirectory() as tmp_dir:
            script_path = Path(tmp_dir) / script.filename
            script_path.write_text(script_text, encoding="utf-8")

            if appium_devices:
                matrix_run_id = f"matrix_{uuid.uuid4().hex[:8]}"
                matrix_results = []
                created_dirs: list[str] = []

                for device in appium_devices:
                    device_started = time.perf_counter()
                    device_env = _build_appium_device_runtime_env(
                        device=device,
                        appium_server_url=appium_server_url,
                    )
                    result = await _execute_script_once(
                        script_path=script_path,
                        runtime_env=device_env,
                        framework=framework,
                    )
                    device_duration_ms = round(
                        (time.perf_counter() - device_started) * 1000,
                        2,
                    )
                    metrics.script_executions_total.inc(status=result.semantic_status)
                    metrics.script_execution_duration_seconds.observe(
                        device_duration_ms / 1000,
                        status=result.semantic_status,
                    )
                    await _save_execution_record(
                        run_id=result.run_id,
                        script_path=str(script_path),
                        script_hash=script_hash,
                        result=result,
                        duration_ms=int(device_duration_ms),
                        request_id=f"{request_id}:{device['slug']}",
                    )

                    run_dir = _resolve_result_run_dir(result)
                    if not run_dir.exists():
                        logger.error(
                            "RUN_DIR_MISSING | request_id=%s | run_id=%s | status=%s",
                            request_id,
                            result.run_id,
                            result.semantic_status,
                        )
                        raise HTTPException(
                            status_code=500,
                            detail=f"Run directory not found for {device['label']}",
                        )

                    _ensure_final_script(
                        run_dir=run_dir,
                        script_path=script_path,
                        request_id=request_id,
                        run_id=result.run_id,
                    )
                    created_dirs.extend(_created_dirs_for_result(result))
                    matrix_results.append(
                        {
                            "device": device,
                            "result": result,
                            "run_dir": run_dir,
                            "duration_ms": device_duration_ms,
                        }
                    )

                duration_ms = round(
                    (time.perf_counter() - start_ts) * 1000,
                    2,
                )
                semantic_status = (
                    "passed"
                    if all(item["result"].semantic_status == "passed" for item in matrix_results)
                    else "failed"
                )
                zip_path = _write_appium_matrix_zip(
                    matrix_run_id=matrix_run_id,
                    matrix_results=matrix_results,
                    semantic_status=semantic_status,
                )

                logger.info(
                    "EXEC_MATRIX_END | request_id=%s | status=%s | devices=%s | zip_created=%s",
                    request_id,
                    semantic_status,
                    len(matrix_results),
                    zip_path,
                )

                background_tasks.add_task(cleanup_run_files, zip_path, created_dirs, False)

                return FileResponse(
                    path=zip_path,
                    filename=f"{matrix_run_id}.zip",
                    media_type="application/zip",
                    headers={
                        "X-Request-ID": request_id,
                        "X-Semantic-Status": semantic_status,
                        "X-Run-ID": matrix_run_id,
                        "X-Duration-Ms": str(duration_ms),
                        "X-Script-Hash": script_hash,
                        "X-Appium-Matrix-Run-Count": str(len(matrix_results)),
                        "X-Artifact-Zip-Path": str(zip_path),
                    },
                )

            result = await _execute_script_once(
                script_path=script_path,
                runtime_env=runtime_env,
                framework=framework,
            )

            duration_ms = round(
                (time.perf_counter() - start_ts) * 1000, 2
            )

            # Record metrics
            metrics.script_executions_total.inc(status=result.semantic_status)
            metrics.script_execution_duration_seconds.observe(
                duration_ms / 1000,
                status=result.semantic_status,
            )

            # Save to database
            await _save_execution_record(
                run_id=result.run_id,
                script_path=str(script_path),
                script_hash=script_hash,
                result=result,
                duration_ms=int(duration_ms),
                request_id=request_id,
            )

            # --------------------------------------------------
            # ZIP RUN DIRECTORY (SUCCESS-AWARE)
            # --------------------------------------------------

            run_dir = _resolve_result_run_dir(result)
            logger.info(
                "RUN_DIRECTORY_RESOLVED | request_id=%s | run_id=%s | status=%s | path=%s",
                request_id,
                result.run_id,
                result.semantic_status,
                str(run_dir),
            )

            if not run_dir.exists():
                logger.error(
                    "RUN_DIR_MISSING | request_id=%s | run_id=%s | status=%s",
                    request_id,
                    result.run_id,
                    result.semantic_status,
                )
                raise HTTPException(
                    status_code=500,
                    detail="Run directory not found",
                )

            _ensure_final_script(
                run_dir=run_dir,
                script_path=script_path,
                request_id=request_id,
                run_id=result.run_id,
            )

            zip_path = _zip_run_dir(run_dir, result=result)

            logger.info(
                "EXEC_END | request_id=%s | status=%s | zip_created=%s",
                request_id,
                result.semantic_status,
                zip_path,
            )

            created_dirs = _created_dirs_for_result(result)

            background_tasks.add_task(cleanup_run_files, zip_path, created_dirs, False)

            return FileResponse(
                path=zip_path,
                filename=f"{result.run_id}.zip",
                media_type="application/zip",
                headers={
                    "X-Request-ID": request_id,
                    "X-Semantic-Status": result.semantic_status,
                    "X-Run-ID": result.run_id,
                    "X-Duration-Ms": str(duration_ms),
                    "X-Script-Hash": script_hash,
                    "X-Artifact-Zip-Path": str(zip_path),
                },
            )

    except HTTPException:
        raise

    except Exception as exc:
        duration_ms = round((time.perf_counter() - start_ts) * 1000, 2)
        metrics.script_executions_total.inc(status="error")
        
        logger.exception(
            "EXEC_FAILURE | request_id=%s | filename=%s | error=%s",
            request_id,
            script.filename,
            str(exc),
        )

        raise HTTPException(
            status_code=500,
            detail="Internal execution error",
        )


def _build_appium_runtime_env(
    *,
    appium_server_url: Optional[str],
    appium_device_filter: Optional[str],
    appium_device_matrix: Optional[str],
) -> dict[str, str]:
    """
    Builds safe per-run Appium runtime overrides for generated scripts.

    These values are passed only to the subprocess environment for this
    execution/re-execution loop. They do not mutate the process-wide .env.
    """

    runtime_env: dict[str, str] = {}

    if appium_server_url and appium_server_url.strip():
        server_url = appium_server_url.strip()
        parsed = urlparse(server_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise HTTPException(
                status_code=400,
                detail="appium_server_url must be a valid http(s) Appium hub URL",
            )
        runtime_env["APPIUM_SERVER_URL"] = server_url
        cloud_url = _is_cloud_appium_url(server_url)
        runtime_env.setdefault("APPIUM_CLEAN_APP_BEFORE_EACH_RUN", str(not cloud_url).lower())
        runtime_env.setdefault("APPIUM_ALLOW_DESTRUCTIVE_APP_RESET", str(not cloud_url).lower())

    return runtime_env


async def _execute_script_once(
    *,
    script_path: Path,
    runtime_env: dict[str, str],
    framework: str,
):
    if settings.ENABLE_SELF_HEALING:
        return await _orchestrator.execute_script_with_self_healing(
            script_path=str(script_path),
            extra_env=runtime_env or None,
            framework_override=framework,
        )

    return await _executor.execute(
        str(script_path),
        extra_env=runtime_env or None,
    )


def _looks_like_appium_script(script_text: str) -> bool:
    code_lower = script_text.lower()
    return (
        "from appium" in code_lower
        or "import appium" in code_lower
        or "appium.webdriver" in code_lower
        or "appiumby" in code_lower
        or "appiumoptions" in code_lower
    )


def _resolve_default_appium_device_matrix_text() -> str:
    env_matrix = (os.environ.get("APPIUM_DEVICE_MATRIX_JSON") or "").strip()
    if env_matrix:
        return env_matrix

    matrix_path_value = (
        (os.environ.get("APPIUM_DEVICE_MATRIX_PATH") or "").strip()
        or str(settings.APPIUM_DEVICE_MATRIX_PATH or "").strip()
    )
    if not matrix_path_value:
        return ""

    matrix_path = Path(matrix_path_value)
    if not matrix_path.is_absolute():
        matrix_path = Path(__file__).resolve().parents[3] / matrix_path

    try:
        if matrix_path.exists() and matrix_path.is_file():
            return matrix_path.read_text(encoding="utf-8").strip()
    except Exception as exc:
        logger.warning(
            "APPIUM_DEFAULT_MATRIX_READ_FAILED | path=%s | error=%s",
            str(matrix_path),
            exc,
        )

    return ""


def _select_appium_runtime_devices(
    *,
    appium_device_matrix: Optional[str],
    appium_device_filter: Optional[str],
) -> list[dict[str, Any]]:
    matrix_text = (
        appium_device_matrix.strip()
        if appium_device_matrix and appium_device_matrix.strip()
        else _resolve_default_appium_device_matrix_text()
    )

    if not matrix_text:
        if appium_device_filter and appium_device_filter.strip():
            raise HTTPException(
                status_code=400,
                detail=(
                    "appium_device_filter requires appium_device_matrix or "
                    "APPIUM_DEVICE_MATRIX_JSON because generated scripts are "
                    "device agnostic."
                ),
            )
        return []

    devices = _parse_appium_device_matrix(matrix_text)
    return _filter_appium_devices(devices, appium_device_filter)


def _parse_appium_device_matrix(matrix_text: str) -> list[dict[str, Any]]:
    if len(matrix_text) > 200_000:
        raise HTTPException(
            status_code=400,
            detail="appium_device_matrix is too large",
        )

    try:
        parsed_matrix = json.loads(matrix_text)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"appium_device_matrix must be valid JSON: {exc.msg}",
        ) from exc

    if isinstance(parsed_matrix, dict):
        if isinstance(parsed_matrix.get("devices"), list):
            raw_devices = parsed_matrix["devices"]
        elif isinstance(parsed_matrix.get("matrix"), list):
            raw_devices = parsed_matrix["matrix"]
        elif any(
            key in parsed_matrix
            for key in (
                "label",
                "slug",
                "device_name",
                "deviceName",
                "capabilities",
                "platformName",
                "platform_name",
            )
        ):
            raw_devices = [parsed_matrix]
        else:
            raise HTTPException(
                status_code=400,
                detail=(
                    "appium_device_matrix object must contain devices, matrix, "
                    "or a single device capability object"
                ),
            )
    elif isinstance(parsed_matrix, list):
        raw_devices = parsed_matrix
    else:
        raise HTTPException(
            status_code=400,
            detail="appium_device_matrix must be a JSON array or object",
        )

    if not raw_devices:
        raise HTTPException(
            status_code=400,
            detail="appium_device_matrix must contain at least one device",
        )

    devices: list[dict[str, Any]] = []
    seen_slugs: dict[str, int] = {}
    for index, raw_device in enumerate(raw_devices, start=1):
        device = _normalize_appium_device_entry(raw_device, index)
        base_slug = device["slug"]
        count = seen_slugs.get(base_slug, 0) + 1
        seen_slugs[base_slug] = count
        if count > 1:
            device["slug"] = f"{base_slug}_{count}"
        devices.append(device)

    return devices


def _normalize_appium_device_entry(entry: Any, index: int) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise HTTPException(
            status_code=400,
            detail="Every appium_device_matrix entry must be an object",
        )

    capabilities = dict(entry.get("capabilities") or {})
    extra = _pick_appium_value(entry, "extra_capabilities", "extraCapabilities") or {}
    if not isinstance(extra, dict):
        raise HTTPException(
            status_code=400,
            detail="extra_capabilities must be an object",
        )
    capabilities.update(extra)

    provider_options = _provider_options(capabilities)
    platform_name = (
        _pick_appium_value(entry, "platform_name", "platformName")
        or capabilities.get("platformName")
        or "Android"
    )
    device_name = (
        _pick_appium_value(entry, "device_name", "deviceName")
        or capabilities.get("appium:deviceName")
        or capabilities.get("deviceName")
        or provider_options.get("deviceName")
        or provider_options.get("device")
    )
    label = entry.get("label") or device_name or f"device_{index}"
    slug = entry.get("slug") or _slugify_appium_device(label)
    automation_name = (
        _pick_appium_value(entry, "automation_name", "automationName")
        or capabilities.get("appium:automationName")
        or ("XCUITest" if str(platform_name).lower() == "ios" else "UiAutomator2")
    )
    platform_version = (
        _pick_appium_value(entry, "platform_version", "platformVersion")
        or capabilities.get("appium:platformVersion")
        or capabilities.get("platformVersion")
        or provider_options.get("osVersion")
        or provider_options.get("platformVersion")
    )
    udid = _pick_appium_value(entry, "udid") or capabilities.get("appium:udid")
    app_package = (
        _pick_appium_value(entry, "app_package", "appPackage")
        or capabilities.get("appium:appPackage")
    )
    app_activity = (
        _pick_appium_value(entry, "app_activity", "appActivity")
        or capabilities.get("appium:appActivity")
    )
    app_wait_activity = (
        _pick_appium_value(entry, "app_wait_activity", "appWaitActivity")
        or capabilities.get("appium:appWaitActivity")
    )
    bundle_id = (
        _pick_appium_value(entry, "bundle_id", "bundleId")
        or capabilities.get("appium:bundleId")
    )
    app_ref = (
        _pick_appium_value(entry, "app")
        or capabilities.get("appium:app")
        or capabilities.get("app")
    )

    capabilities["platformName"] = platform_name
    capabilities["appium:automationName"] = automation_name
    if device_name:
        capabilities["appium:deviceName"] = device_name
    if platform_version:
        capabilities["appium:platformVersion"] = platform_version
    if udid:
        capabilities["appium:udid"] = udid
    if app_ref:
        capabilities["appium:app"] = app_ref

    if str(platform_name).lower() == "ios":
        if bundle_id:
            capabilities["appium:bundleId"] = bundle_id
        capabilities.pop("appium:appPackage", None)
        capabilities.pop("appium:appActivity", None)
        capabilities.pop("appium:appWaitActivity", None)
    else:
        if app_package:
            capabilities["appium:appPackage"] = app_package
        if app_activity:
            capabilities["appium:appActivity"] = app_activity
        if app_wait_activity:
            capabilities["appium:appWaitActivity"] = app_wait_activity

    for source_key, capability_key in (
        ("no_reset", "appium:noReset"),
        ("noReset", "appium:noReset"),
        ("full_reset", "appium:fullReset"),
        ("fullReset", "appium:fullReset"),
        ("auto_grant_permissions", "appium:autoGrantPermissions"),
        ("autoGrantPermissions", "appium:autoGrantPermissions"),
    ):
        if source_key in entry and entry[source_key] is not None:
            capabilities[capability_key] = entry[source_key]

    if not any(capabilities.get(key) for key in ("appium:deviceName", "appium:udid", "browserName")):
        raise HTTPException(
            status_code=400,
            detail=f"Appium matrix entry {index} needs deviceName/device_name, udid, or browserName",
        )

    return {
        "label": str(label),
        "slug": str(slug),
        "platform_name": str(platform_name),
        "device_name": str(device_name) if device_name else None,
        "app_package": app_package,
        "bundle_id": bundle_id,
        "clean_app_before_each_run": _pick_appium_value(
            entry,
            "clean_app_before_each_run",
            "cleanAppBeforeEachRun",
        ),
        "allow_destructive_app_reset": _pick_appium_value(
            entry,
            "allow_destructive_app_reset",
            "allowDestructiveAppReset",
        ),
        "relaunch_before_test": _parse_bool(
            _pick_appium_value(entry, "relaunch_before_test", "relaunchBeforeTest"),
            default=True,
        ),
        "relaunch_before_step_retry": _parse_bool(
            _pick_appium_value(entry, "relaunch_before_step_retry", "relaunchBeforeStepRetry"),
            default=True,
        ),
        "capabilities": capabilities,
    }


def _filter_appium_devices(
    devices: list[dict[str, Any]],
    appium_device_filter: Optional[str],
) -> list[dict[str, Any]]:
    if not appium_device_filter or not appium_device_filter.strip():
        return devices

    wanted = {
        token.strip().lower()
        for token in appium_device_filter.split(",")
        if token.strip()
    }
    selected = [
        device
        for device in devices
        if wanted
        & {
            str(device.get("slug") or "").lower(),
            str(device.get("label") or "").lower(),
            str(device.get("device_name") or "").lower(),
        }
    ]
    if not selected:
        raise HTTPException(
            status_code=400,
            detail="appium_device_filter did not match any runtime devices",
        )
    return selected


def _build_appium_device_runtime_env(
    *,
    device: dict[str, Any],
    appium_server_url: Optional[str],
) -> dict[str, str]:
    runtime_env = _build_appium_runtime_env(
        appium_server_url=appium_server_url,
        appium_device_filter=None,
        appium_device_matrix=None,
    )
    cloud_url = _is_cloud_appium_url(appium_server_url or runtime_env.get("APPIUM_SERVER_URL"))
    clean_app = _parse_bool(
        device.get("clean_app_before_each_run"),
        default=not cloud_url,
    )
    allow_destructive_reset = _parse_bool(
        device.get("allow_destructive_app_reset"),
        default=clean_app and not cloud_url,
    )
    context = {
        "label": device["label"],
        "slug": device["slug"],
        "platform_name": device.get("platform_name"),
        "device_name": device.get("device_name"),
        "app_package": device.get("app_package"),
        "bundle_id": device.get("bundle_id"),
        "clean_app_before_each_run": clean_app,
        "allow_destructive_app_reset": allow_destructive_reset,
        "relaunch_before_test": device.get("relaunch_before_test", True),
        "relaunch_before_step_retry": device.get("relaunch_before_step_retry", True),
    }
    runtime_env.update(
        {
            "APPIUM_CAPABILITIES_JSON": json.dumps(
                device["capabilities"],
                separators=(",", ":"),
            ),
            "APPIUM_DEVICE_CONTEXT_JSON": json.dumps(
                context,
                separators=(",", ":"),
            ),
            "APPIUM_DEVICE_LABEL": device["label"],
            "APPIUM_DEVICE_SLUG": device["slug"],
            "APPIUM_RELAUNCH_BEFORE_TEST": str(context["relaunch_before_test"]).lower(),
            "APPIUM_RELAUNCH_BEFORE_STEP_RETRY": str(context["relaunch_before_step_retry"]).lower(),
            "APPIUM_CLEAN_APP_BEFORE_EACH_RUN": str(clean_app).lower(),
            "APPIUM_ALLOW_DESTRUCTIVE_APP_RESET": str(allow_destructive_reset).lower(),
        }
    )
    return runtime_env


def _resolve_result_run_dir(result) -> Path:
    run_dir_temp = Path(result.working_dir)
    project_root = run_dir_temp.parents[1] if len(run_dir_temp.parents) > 1 else run_dir_temp.parent
    archive_root = (
        project_root / "successful_runs"
        if result.semantic_status == "passed"
        else project_root / "failed_runs"
    )
    run_dir = archive_root / result.run_id
    return run_dir if run_dir.exists() else run_dir_temp


def _ensure_final_script(
    *,
    run_dir: Path,
    script_path: Path,
    request_id: str,
    run_id: str,
) -> None:
    script_ext = script_path.suffix or ".py"
    final_script_path = run_dir / f"final_script{script_ext}"
    if final_script_path.exists():
        return

    final_script_path.write_text(
        script_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    logger.info(
        "FINAL_SCRIPT_EMITTED | request_id=%s | run_id=%s | path=%s",
        request_id,
        run_id,
        str(final_script_path),
    )


def _zip_run_dir(run_dir: Path, *, result=None) -> Path:
    zip_path = run_dir.parent / f"{run_dir.name}.zip"
    manifest = None
    if result is not None:
        manifest = {
            "run_id": getattr(result, "run_id", run_dir.name),
            "matrix_run_id": None,
            "semantic_status": getattr(result, "semantic_status", None),
            "artifact_zip_path": str(zip_path),
            "failed_step_index": _read_failed_step_index(run_dir),
        }
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        if manifest:
            zipf.writestr("execution_manifest.json", json.dumps(manifest, indent=2))
        for file_path in run_dir.rglob("*"):
            if file_path.is_file():
                zipf.write(
                    file_path,
                    arcname=file_path.relative_to(run_dir),
                )
    return zip_path


def _write_appium_matrix_zip(
    *,
    matrix_run_id: str,
    matrix_results: list[dict[str, Any]],
    semantic_status: str,
) -> Path:
    first_run_dir = matrix_results[0]["run_dir"]
    project_root = (
        first_run_dir.parent.parent
        if first_run_dir.parent.name in {"successful_runs", "failed_runs"}
        else first_run_dir.parents[1]
    )
    bundle_root = project_root / ("successful_runs" if semantic_status == "passed" else "failed_runs")
    bundle_root.mkdir(parents=True, exist_ok=True)
    zip_path = bundle_root / f"{matrix_run_id}.zip"

    summary = {
        "run_id": matrix_run_id,
        "status": semantic_status,
        "kind": "appium_device_matrix",
        "runs": [
            {
                "folder": item["device"]["slug"],
                "run_id": item["result"].run_id,
                "status": item["result"].semantic_status,
                "duration_ms": item["duration_ms"],
                "device": {
                    "label": item["device"]["label"],
                    "slug": item["device"]["slug"],
                    "platform_name": item["device"].get("platform_name"),
                    "device_name": item["device"].get("device_name"),
                },
            }
            for item in matrix_results
        ],
    }
    manifest = {
        "run_id": matrix_run_id,
        "matrix_run_id": matrix_run_id,
        "semantic_status": semantic_status,
        "artifact_zip_path": str(zip_path),
        "failed_step_index": next(
            (
                _read_failed_step_index(item["run_dir"])
                for item in matrix_results
                if item["result"].semantic_status != "passed"
            ),
            None,
        ),
    }

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        written_entries: set[str] = set()

        def _write_json_once(arcname: str, payload: Any) -> None:
            if arcname in written_entries:
                logger.warning("APPEND_MATRIX_ZIP_DUPLICATE_SKIPPED | arcname=%s", arcname)
                return
            zipf.writestr(arcname, json.dumps(payload, indent=2))
            written_entries.add(arcname)

        def _write_file_once(file_path: Path, arcname: str) -> None:
            if arcname in written_entries:
                logger.warning("APPEND_MATRIX_ZIP_DUPLICATE_SKIPPED | arcname=%s", arcname)
                return
            zipf.write(file_path, arcname=arcname)
            written_entries.add(arcname)

        _write_json_once("matrix_summary.json", summary)
        _write_json_once("execution_manifest.json", manifest)
        for item in matrix_results:
            prefix = item["device"]["slug"]
            run_dir = item["run_dir"]
            device_summary = {
                "run_id": item["result"].run_id,
                "matrix_run_id": matrix_run_id,
                "semantic_status": item["result"].semantic_status,
                "duration_ms": item["duration_ms"],
                "failed_step_index": _read_failed_step_index(run_dir),
                "device": {
                    "label": item["device"]["label"],
                    "slug": item["device"]["slug"],
                    "platform_name": item["device"].get("platform_name"),
                    "device_name": item["device"].get("device_name"),
                },
            }
            _write_json_once(f"{prefix}/run_summary.json", device_summary)
            _write_json_once(
                f"{prefix}/appium_capabilities.json",
                item["device"].get("capabilities") or {},
            )
            for file_path in run_dir.rglob("*"):
                if file_path.is_file():
                    _write_file_once(
                        file_path,
                        arcname=f"{prefix}/{file_path.relative_to(run_dir).as_posix()}",
                    )

    return zip_path


def _read_failed_step_index(run_dir: Path) -> Optional[int]:
    for summary_path in (
        run_dir / "failures" / "summary.json",
        run_dir / "success" / "summary.json",
    ):
        if not summary_path.exists():
            continue
        try:
            data = json.loads(summary_path.read_text(encoding="utf-8"))
            value = data.get("failed_step_index")
            return int(value) if value is not None else None
        except Exception:
            return None
    return None


def _created_dirs_for_result(result) -> list[str]:
    created_dirs = list(getattr(result, "metadata", {}).get("created_run_dirs", []) or [])
    if result.working_dir and result.working_dir not in created_dirs:
        created_dirs.append(result.working_dir)
    return created_dirs


def _pick_appium_value(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping.get(key) is not None:
            return mapping.get(key)
    return None


def _provider_options(capabilities: dict[str, Any]) -> dict[str, Any]:
    for key in ("bstack:options", "sauce:options"):
        value = capabilities.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _is_cloud_appium_url(appium_server_url: Optional[str]) -> bool:
    if not appium_server_url:
        return False
    host = (urlparse(appium_server_url).hostname or "").lower()
    return any(
        token in host
        for token in (
            "browserstack.com",
            "saucelabs.com",
            "sauce-ondemand.com",
            "testingbot.com",
            "lambdatest.com",
        )
    )


def _parse_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _slugify_appium_device(value: Any) -> str:
    import re

    return re.sub(r"[^A-Za-z0-9]+", "_", str(value or "").strip().lower()).strip("_") or "device"


# --------------------------------------------------
# Database Persistence
# --------------------------------------------------

async def _save_execution_record(
    *,
    run_id: str,
    script_path: str,
    script_hash: str,
    result,
    duration_ms: int,
    request_id: str,
):
    """Save execution record to database."""
    try:
        repo = await get_repository()
        
        raw_meta = getattr(result, "metadata", {})
        meta = {}
        if isinstance(raw_meta, dict) and type(raw_meta).__name__ not in ('MagicMock', 'AsyncMock', 'Mock'):
            meta = raw_meta

        repairs_attempted = int(meta.get("repairs_attempted", 0) or 0)
        repairs_successful = int(meta.get("repairs_successful", 0) or 0)

        record = ExecutionRecord(
            run_id=run_id,
            script_path=script_path,
            script_hash=script_hash,
            status=result.semantic_status,
            exit_code=result.exit_code,
            duration_ms=duration_ms,
            stdout=result.stdout[:10000] if result.stdout else None,  # Truncate
            stderr=result.stderr[:10000] if result.stderr else None,
            repairs_attempted=repairs_attempted,
            repairs_successful=repairs_successful,
            request_id=request_id,
            metadata=meta,
        )
        
        await repo.save_execution(record)
        logger.debug("Saved execution record: %s", record.id)
    except Exception as e:
        # Don't fail the request if database save fails
        logger.warning("Failed to save execution record: %s", e)

