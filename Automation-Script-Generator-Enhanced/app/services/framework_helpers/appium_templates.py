from pprint import pformat
from typing import Any, List, Optional

from app.models.appium import AppiumConfig, AppiumDeviceConfig


def generate_appium_imports() -> List[str]:
    return [
        "import os",
        "import sys",
        "import json",
        "import time",
        "import hashlib",
        "import traceback",
        "import re",
        "import base64",
        "from datetime import datetime, timezone",
        "from appium import webdriver",
        "from appium.webdriver.common.appiumby import AppiumBy",
        "from selenium.webdriver.support.ui import WebDriverWait",
        "from selenium.webdriver.support import expected_conditions as EC",
        "from appium.options.common.base import AppiumOptions",
    ]


def generate_appium_guard() -> List[str]:
    return [
        "def _get_step_source(step_fn):",
        "    try:",
        "        with open(__file__, 'r', encoding='utf-8') as f:",
        "            content = f.read()",
        "        func_name = step_fn.__name__",
        "        pattern = rf\"def\\s+{func_name}\\s*\\(\\s*driver\\s*\\)\\s*:\"",
        "        match = re.search(pattern, content)",
        "        if not match: return \"\"",
        "        start_pos = match.end()",
        "        lines = content[start_pos:].splitlines()",
        "        body_lines = []",
        "        body_indent = None",
        "        for line in lines:",
        "            if not line.strip():",
        "                if body_indent is not None: body_lines.append(line)",
        "                continue",
        "            indent = len(line) - len(line.lstrip())",
        "            if body_indent is None: body_indent = indent",
        "            if indent < body_indent: break",
        "            body_lines.append(line[body_indent:] if len(line) >= body_indent else line)",
        "        return \"\\n\".join(body_lines).strip()",
        "    except Exception:",
        "        return \"\"",
        "",
        "def _guarded_step(driver, step_fn, step_name, step_index, step_code, intent, max_retries, artifacts_dir, success_dir, step_metrics, running_summary_path, device_context=None):",
        "    start_total = time.monotonic()",
        "    attempts = 0",
        "    passed = False",
        "    error_message = None",
        "    device_context = device_context or {}",
        "    device_label = device_context.get('label')",
        "    device_slug = device_context.get('slug')",
        "    relaunch_before_retry = bool(device_context.get('relaunch_before_step_retry', APPIUM_RELAUNCH_BEFORE_STEP_RETRY))",
        "",
        "    while attempts <= max_retries:",
        "        attempts += 1",
        "        try:",
        "            if attempts > 1 and relaunch_before_retry:",
        "                _recover_app_state(",
        "                    driver,",
        "                    app_package=device_context.get('app_package'),",
        "                    bundle_id=device_context.get('bundle_id'),",
        "                    restart=True,",
        "                )",
        "            started_at = datetime.now(timezone.utc).isoformat()",
        "            step_fn(driver)",
        "            ended_at = datetime.now(timezone.utc).isoformat()",
        "            passed = True",
        "",
        "            duration_total = round(time.monotonic() - start_total, 4)",
        "            success_step_dir = os.path.join(success_dir, step_name)",
        "            os.makedirs(success_step_dir, exist_ok=True)",
        "",
        "            try: driver.save_screenshot(os.path.join(success_step_dir, 'screenshot.png'))",
        "            except: pass",
        "",
        "            try:",
        "                logs = driver.get_log('logcat')",
        "            except:",
        "                try: logs = driver.get_log('syslog')",
        "                except: logs = []",
        "",
        "            if logs:",
        "                with open(os.path.join(success_step_dir, 'console.txt'), 'w', encoding='utf-8') as f:",
        "                    f.write('\\n'.join(str(l) for l in logs))",
        "",
        "            step_summary = {",
        "                'step_index': step_index,",
        "                'step_name': step_name,",
        "                'intent': intent,",
        "                'started_at': started_at,",
        "                'ended_at': ended_at,",
        "                'duration_sec': duration_total,",
        "                'attempts': attempts,",
        "                'max_retries': max_retries,",
        "                'device_label': device_label,",
        "                'device_slug': device_slug,",
        "                'device_name': device_context.get('device_name'),",
        "                'platform_name': device_context.get('platform_name'),",
        "                'status': 'passed',",
        "                'flaky': attempts > 1,",
        "                'step_code_hash': hashlib.sha256(step_code.encode()).hexdigest()[:12]",
        "            }",
        "            with open(os.path.join(success_step_dir, 'step_summary.json'), 'w', encoding='utf-8') as f:",
        "                json.dump(step_summary, f, indent=2)",
        "            break",
        "        except Exception as e:",
        "            error_message = str(e)",
        "            failures_root = os.path.join(artifacts_dir, 'failures', step_name)",
        "            attempt_dir = os.path.join(failures_root, f'attempt_{attempts}')",
        "            os.makedirs(attempt_dir, exist_ok=True)",
        "",
        "            try: driver.save_screenshot(os.path.join(attempt_dir, 'screenshot.png'))",
        "            except: pass",
        "",
        "            try:",
        "                with open(os.path.join(attempt_dir, 'dom.xml'), 'w', encoding='utf-8') as f:",
        "                    f.write(driver.page_source)",
        "            except: pass",
        "",
        "            try:",
        "                logs = driver.get_log('logcat')",
        "            except:",
        "                try: logs = driver.get_log('syslog')",
        "                except: logs = []",
        "",
        "            if logs:",
        "                with open(os.path.join(attempt_dir, 'console.txt'), 'w', encoding='utf-8') as f:",
        "                    f.write('\\n'.join(str(l) for l in logs))",
        "",
        "            with open(os.path.join(attempt_dir, 'device_context.json'), 'w', encoding='utf-8') as f:",
        "                json.dump(device_context, f, indent=2)",
        "            with open(os.path.join(attempt_dir, 'intent.txt'), 'w', encoding='utf-8') as f: f.write(intent)",
        "            with open(os.path.join(attempt_dir, 'error.txt'), 'w', encoding='utf-8') as f: f.write(error_message)",
        "            with open(os.path.join(attempt_dir, 'traceback.txt'), 'w', encoding='utf-8') as f: f.write(traceback.format_exc())",
        "            with open(os.path.join(attempt_dir, 'step_code.py'), 'w', encoding='utf-8') as f: f.write(_get_step_source(step_fn))",
        "",
        "            if attempts <= max_retries:",
        "                print(f'Step {step_index} failed, retrying ({attempts}/{max_retries})...')",
        "                time.sleep(1)",
        "",
        "    duration = time.monotonic() - start_total",
        "    metric = {",
        "        'step_index': step_index,",
        "        'step_name': step_name,",
        "        'attempts': attempts,",
        "        'max_retries': max_retries,",
        "        'duration_total_sec': round(duration, 3),",
        "        'device_label': device_label,",
        "        'device_slug': device_slug,",
        "        'device_name': device_context.get('device_name'),",
        "        'platform_name': device_context.get('platform_name'),",
        "        'status': 'passed' if passed else 'failed',",
        "        'flaky': attempts > 1 and passed,",
        "        'step_code_hash': hashlib.sha256(step_code.encode()).hexdigest()[:12]",
        "    }",
        "    if not passed:",
        "        metric['error'] = error_message",
        "",
        "    step_metrics.append(metric)",
        "",
        "    with open(running_summary_path, 'w', encoding='utf-8') as f:",
        "        json.dump({'status': 'running', 'device': device_context, 'steps': step_metrics}, f, indent=2)",
        "",
        "    if not passed:",
        "        device_suffix = f\" on {device_label}\" if device_label else ''",
        "        raise RuntimeError(f'Step {step_index}{device_suffix} failed after {max_retries} retries: {error_message}')",
        "",
    ]


def _first_defined(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _is_ios(platform_name: Optional[str]) -> bool:
    return (platform_name or "").strip().lower() == "ios"


def _default_automation(platform_name: Optional[str], configured: Optional[str]) -> str:
    if configured:
        return configured
    return "XCUITest" if _is_ios(platform_name) else "UiAutomator2"


def _merged_extra_capabilities(
    config: AppiumConfig,
    device: Optional[AppiumDeviceConfig],
) -> dict[str, Any]:
    capabilities = dict(config.extra_capabilities)
    if device:
        capabilities.update(device.extra_capabilities)
    return capabilities


def _app_reference(
    config: AppiumConfig,
    device: Optional[AppiumDeviceConfig],
    extra_capabilities: dict[str, Any],
) -> Optional[str]:
    return _first_defined(
        device.app if device else None,
        config.app,
        extra_capabilities.get("appium:app"),
        extra_capabilities.get("app"),
    )


def _appium_capabilities(
    config: AppiumConfig,
    device: Optional[AppiumDeviceConfig] = None,
) -> dict[str, Any]:
    platform_name = _first_defined(
        device.platform_name if device else None,
        config.platform_name,
        "Android",
    )
    configured_automation = _first_defined(
        device.automation_name if device else None,
        config.automation_name,
    )
    if _is_ios(platform_name) and configured_automation == "UiAutomator2":
        configured_automation = None
    automation_name = _default_automation(platform_name, configured_automation)
    device_name = _first_defined(device.device_name if device else None, config.device_name)
    platform_version = _first_defined(device.platform_version if device else None, config.platform_version)
    udid = _first_defined(device.udid if device else None, config.udid)
    app_package = _first_defined(device.app_package if device else None, config.app_package)
    app_activity = _first_defined(device.app_activity if device else None, config.app_activity)
    bundle_id = _first_defined(device.bundle_id if device else None, config.bundle_id)
    app_wait_activity = _first_defined(
        device.app_wait_activity if device else None,
        config.app_wait_activity,
    )
    no_reset = _first_defined(device.no_reset if device else None, config.no_reset)
    full_reset = _first_defined(device.full_reset if device else None, config.full_reset)
    auto_grant_permissions = _first_defined(
        device.auto_grant_permissions if device else None,
        config.auto_grant_permissions,
    )
    extra_capabilities = _merged_extra_capabilities(config, device)
    app = _app_reference(config, device, extra_capabilities)

    capabilities: dict[str, Any] = {
        "platformName": platform_name,
        "appium:automationName": automation_name,
    }

    optional = {
        "appium:deviceName": device_name,
        "appium:platformVersion": platform_version,
        "appium:udid": udid,
        "appium:app": app,
        "appium:noReset": no_reset,
        "appium:fullReset": full_reset,
    }
    if _is_ios(platform_name):
        optional["appium:bundleId"] = bundle_id
    else:
        optional["appium:appPackage"] = app_package
        optional["appium:appActivity"] = app_activity
        optional["appium:appWaitActivity"] = app_wait_activity
        optional["appium:autoGrantPermissions"] = auto_grant_permissions

    capabilities.update({k: v for k, v in optional.items() if v is not None})
    capabilities.update(extra_capabilities)
    return capabilities


def resolve_appium_device_matrix(config: AppiumConfig) -> List[dict[str, Any]]:
    """
    Legacy helper retained for callers that inspect AppiumConfig. Generated
    scripts no longer loop over this matrix; Executor-Regenerator does that at
    runtime and injects one capability set per run.
    """

    devices: list[Optional[AppiumDeviceConfig]] = list(config.devices) or [None]
    matrix: list[dict[str, Any]] = []

    for index, device in enumerate(devices, start=1):
        platform_name = _first_defined(
            device.platform_name if device else None,
            config.platform_name,
            "Android",
        )
        device_name = _first_defined(device.device_name if device else None, config.device_name)
        label = _first_defined(
            device.label if device else None,
            device_name,
            f"device_{index}",
        )
        matrix.append(
            {
                "label": label,
                "platform_name": platform_name,
                "device_name": device_name,
                "app_package": _first_defined(
                    device.app_package if device else None,
                    config.app_package,
                ),
                "bundle_id": _first_defined(
                    device.bundle_id if device else None,
                    config.bundle_id,
                ),
                "capabilities": _appium_capabilities(config, device),
            }
        )

    return matrix


def generate_appium_test_wrapper(
    step_calls: List[str],
    test_id: str,
    run_id: str,
    appium_config: AppiumConfig,
) -> List[str]:
    default_capabilities_literal = pformat(
        _appium_capabilities(appium_config),
        sort_dicts=True,
        width=100,
    )

    lines = [
        "APPIUM_SERVER_URL = os.environ.get('APPIUM_SERVER_URL', 'http://127.0.0.1:4723')",
        f"APPIUM_DEFAULT_CAPABILITIES = {default_capabilities_literal}",
        f"APPIUM_RELAUNCH_BEFORE_TEST = {repr(appium_config.relaunch_before_test)}",
        f"APPIUM_RELAUNCH_BEFORE_STEP_RETRY = {repr(appium_config.relaunch_before_step_retry)}",
        "",
        "def _parse_appium_bool(value, default=False):",
        "    if value is None:",
        "        return default",
        "    if isinstance(value, bool):",
        "        return value",
        "    return str(value).strip().lower() in {'1', 'true', 'yes', 'on'}",
        "",
        "def _is_cloud_appium_server(url):",
        "    value = (url or '').lower()",
        "    return any(token in value for token in ('browserstack.com', 'saucelabs.com', 'sauce-ondemand.com', 'testingbot.com', 'lambdatest.com'))",
        "",
        "def _slugify_appium_device(value):",
        "    return re.sub(r'[^A-Za-z0-9]+', '_', str(value or '').strip().lower()).strip('_') or 'device'",
        "",
        "def _load_appium_capabilities(default_capabilities):",
        "    capabilities = dict(default_capabilities or {})",
        "    raw = os.environ.get('APPIUM_CAPABILITIES_JSON') or os.environ.get('APPIUM_CAPABILITIES')",
        "    if raw and raw.strip():",
        "        parsed = json.loads(raw)",
        "        if not isinstance(parsed, dict):",
        "            raise ValueError('APPIUM_CAPABILITIES_JSON must be a JSON object')",
        "        if isinstance(parsed.get('capabilities'), dict):",
        "            parsed = parsed['capabilities']",
        "        capabilities.update(parsed)",
        "    if not any(capabilities.get(k) for k in ('appium:deviceName', 'appium:udid', 'browserName')):",
        "        raise ValueError('Appium capabilities are incomplete. Supply APPIUM_CAPABILITIES_JSON from Executor-Regenerator with at least appium:deviceName or appium:udid.')",
        "    return capabilities",
        "",
        "def _load_appium_device_context(capabilities):",
        "    context = {}",
        "    raw = os.environ.get('APPIUM_DEVICE_CONTEXT_JSON')",
        "    if raw and raw.strip():",
        "        parsed = json.loads(raw)",
        "        if not isinstance(parsed, dict):",
        "            raise ValueError('APPIUM_DEVICE_CONTEXT_JSON must be a JSON object')",
        "        context.update(parsed)",
        "    platform_name = context.get('platform_name') or capabilities.get('platformName')",
        "    device_name = context.get('device_name') or capabilities.get('appium:deviceName') or capabilities.get('deviceName')",
        "    label = os.environ.get('APPIUM_DEVICE_LABEL') or context.get('label') or device_name or 'Appium Device'",
        "    slug = os.environ.get('APPIUM_DEVICE_SLUG') or context.get('slug') or _slugify_appium_device(label)",
        "    default_clean = not _is_cloud_appium_server(APPIUM_SERVER_URL)",
        "    context.update({",
        "        'label': label,",
        "        'slug': slug,",
        "        'platform_name': platform_name,",
        "        'device_name': device_name,",
        "        'app_package': context.get('app_package') or capabilities.get('appium:appPackage'),",
        "        'bundle_id': context.get('bundle_id') or capabilities.get('appium:bundleId'),",
        "        'clean_app_before_each_run': _parse_appium_bool(os.environ.get('APPIUM_CLEAN_APP_BEFORE_EACH_RUN'), context.get('clean_app_before_each_run', default_clean)),",
        "        'allow_destructive_app_reset': _parse_appium_bool(os.environ.get('APPIUM_ALLOW_DESTRUCTIVE_APP_RESET'), context.get('allow_destructive_app_reset', False)),",
        "        'relaunch_before_test': _parse_appium_bool(os.environ.get('APPIUM_RELAUNCH_BEFORE_TEST'), context.get('relaunch_before_test', APPIUM_RELAUNCH_BEFORE_TEST)),",
        "        'relaunch_before_step_retry': _parse_appium_bool(os.environ.get('APPIUM_RELAUNCH_BEFORE_STEP_RETRY'), context.get('relaunch_before_step_retry', APPIUM_RELAUNCH_BEFORE_STEP_RETRY)),",
        "    })",
        "    return context",
        "",
        "APPIUM_CAPABILITIES = _load_appium_capabilities(APPIUM_DEFAULT_CAPABILITIES)",
        "APPIUM_DEVICE_CONTEXT = _load_appium_device_context(APPIUM_CAPABILITIES)",
        "APPIUM_APP_PACKAGE = APPIUM_CAPABILITIES.get('appium:appPackage')",
        "APPIUM_BUNDLE_ID = APPIUM_CAPABILITIES.get('appium:bundleId')",
        "",
        "def _build_appium_options(capabilities):",
        "    options = AppiumOptions()",
        "    for key, value in capabilities.items():",
        "        if value is not None:",
        "            options.set_capability(key, value)",
        "    return options",
        "",
        "def _recover_app_state(driver, app_package=None, bundle_id=None, restart=False):",
        "    app_id = app_package or bundle_id or APPIUM_APP_PACKAGE or APPIUM_BUNDLE_ID",
        "    if not app_id:",
        "        return",
        "    if restart:",
        "        try:",
        "            driver.terminate_app(app_id)",
        "        except Exception:",
        "            pass",
        "    try:",
        "        driver.activate_app(app_id)",
        "    except Exception:",
        "        try:",
        "            driver.execute_script('mobile: activateApp', {'appId': app_id})",
        "        except Exception:",
        "            pass",
        "",
        "def _clear_android_app_data(driver, app_package):",
        "    if not app_package:",
        "        return False",
        "    try:",
        "        driver.execute_script('mobile: shell', {'command': 'pm', 'args': ['clear', app_package]})",
        "        return True",
        "    except Exception:",
        "        try:",
        "            driver.reset()",
        "            return True",
        "        except Exception:",
        "            return False",
        "",
        "def _prepare_app_state(driver, device_context):",
        "    app_package = device_context.get('app_package')",
        "    bundle_id = device_context.get('bundle_id')",
        "    platform_name = (device_context.get('platform_name') or '').lower()",
        "    clean = bool(device_context.get('clean_app_before_each_run'))",
        "    allow_clear = bool(device_context.get('allow_destructive_app_reset'))",
        "    relaunch = bool(device_context.get('relaunch_before_test'))",
        "    app_id = app_package or bundle_id or APPIUM_APP_PACKAGE or APPIUM_BUNDLE_ID",
        "    if clean and app_id:",
        "        try:",
        "            driver.terminate_app(app_id)",
        "        except Exception:",
        "            pass",
        "        if allow_clear and platform_name != 'ios':",
        "            _clear_android_app_data(driver, app_package or APPIUM_APP_PACKAGE)",
        "        _recover_app_state(driver, app_package=app_package, bundle_id=bundle_id, restart=False)",
        "        return",
        "    if relaunch:",
        "        _recover_app_state(driver, app_package=app_package, bundle_id=bundle_id, restart=True)",
        "",
        "def test_flow():",
        "    artifacts_root = os.environ.get('ARTIFACTS_DIR', os.path.join(os.getcwd(), 'artifacts'))",
        f"    test_case_dir = os.path.join(artifacts_root, '{test_id}', os.environ.get('RUN_ID', '{run_id}'))",
        "    artifacts_dir = test_case_dir",
        "    success_dir = os.path.join(test_case_dir, 'success')",
        "    failures_dir = os.path.join(test_case_dir, 'failures')",
        "    os.makedirs(success_dir, exist_ok=True)",
        "    os.makedirs(failures_dir, exist_ok=True)",
        "    running_summary_path = os.path.join(failures_dir, 'summary.json')",
        "    overall_status = 'failed'",
        "    startup_error = None",
        "    step_metrics = []",
        "    driver = None",
        "    device_context = dict(APPIUM_DEVICE_CONTEXT)",
        "",
        "    with open(os.path.join(artifacts_dir, 'status.txt'), 'w', encoding='utf-8') as f: f.write('running')",
        "    with open(os.path.join(artifacts_dir, 'exit_code.txt'), 'w', encoding='utf-8') as f: f.write('1')",
        "    with open(os.path.join(artifacts_dir, 'started_at.txt'), 'w', encoding='utf-8') as f: f.write(datetime.now(timezone.utc).isoformat())",
        "    with open(os.path.join(artifacts_dir, 'appium_capabilities.json'), 'w', encoding='utf-8') as f: json.dump(APPIUM_CAPABILITIES, f, indent=2)",
        "",
        "    try:",
        "        print(f\"Running Appium flow on {device_context.get('label')} ({device_context.get('platform_name')})\")",
        "        options = _build_appium_options(APPIUM_CAPABILITIES)",
        "        driver = webdriver.Remote(APPIUM_SERVER_URL, options=options)",
        "        driver.implicitly_wait(10)",
        "        _prepare_app_state(driver, device_context)",
        "",
        "        try: driver.start_recording_screen()",
        "        except: pass",
        "",
        "        # Steps",
    ]

    for call in step_calls:
        lines.append(f"        {call}")

    lines.extend(
        [
            "",
            "        overall_status = 'passed'",
            "        with open(os.path.join(artifacts_dir, 'status.txt'), 'w', encoding='utf-8') as f: f.write('passed')",
            "        with open(os.path.join(artifacts_dir, 'exit_code.txt'), 'w', encoding='utf-8') as f: f.write('0')",
            "",
            "    except Exception as e:",
            "        startup_error = str(e) if not step_metrics else startup_error",
            "        overall_status = 'failed'",
            "        if not step_metrics:",
            "            startup_dir = os.path.join(failures_dir, 'startup')",
            "            os.makedirs(startup_dir, exist_ok=True)",
            "            with open(os.path.join(startup_dir, 'error.txt'), 'w', encoding='utf-8') as f: f.write(str(e))",
            "            with open(os.path.join(startup_dir, 'traceback.txt'), 'w', encoding='utf-8') as f: f.write(traceback.format_exc())",
            "            with open(os.path.join(startup_dir, 'device_context.json'), 'w', encoding='utf-8') as f: json.dump(device_context, f, indent=2)",
            "        with open(os.path.join(artifacts_dir, 'status.txt'), 'w', encoding='utf-8') as f: f.write('failed')",
            "        with open(os.path.join(artifacts_dir, 'exit_code.txt'), 'w', encoding='utf-8') as f: f.write('1')",
            "        raise e",
            "    finally:",
            "        if driver:",
            "            try:",
            "                video_b64 = driver.stop_recording_screen()",
            "                if video_b64:",
            "                    video_dst_dir = os.path.join(success_dir, 'video') if overall_status == 'passed' else os.path.join(failures_dir, 'video')",
            "                    os.makedirs(video_dst_dir, exist_ok=True)",
            "                    with open(os.path.join(video_dst_dir, 'recording.mp4'), 'wb') as f:",
            "                        f.write(base64.b64decode(video_b64))",
            "            except: pass",
            "            try:",
            "                driver.quit()",
            "            except: pass",
            "",
            "        with open(os.path.join(artifacts_dir, 'finished_at.txt'), 'w', encoding='utf-8') as f: f.write(datetime.now(timezone.utc).isoformat())",
            "        passed = overall_status == 'passed'",
            f"        summary = {{",
            f"            'test_case_id': '{test_id}',",
            f"            'run_id': os.environ.get('RUN_ID', '{run_id}'),",
            "            'status': overall_status,",
            "            'device': device_context,",
            "            'steps': step_metrics,",
            "            'failed_step_index': next((s.get('step_index') for s in step_metrics if s.get('status') == 'failed'), None),",
            "            'failed_device_slug': next((s.get('device_slug') for s in step_metrics if s.get('status') == 'failed'), device_context.get('slug') if overall_status == 'failed' else None),",
            "            'failed_device_label': next((s.get('device_label') for s in step_metrics if s.get('status') == 'failed'), device_context.get('label') if overall_status == 'failed' else None),",
            "        }",
            "        if startup_error:",
            "            summary['startup_error'] = startup_error",
            "        summary_path = os.path.join(success_dir if passed else failures_dir, 'summary.json')",
            "        try:",
            "            tmp = summary_path + '.tmp'",
            "            with open(tmp, 'w', encoding='utf-8') as f:",
            "                json.dump(summary, f, indent=2)",
            "            os.replace(tmp, summary_path)",
            "        except Exception:",
            "            pass",
        ]
    )
    return lines


def generate_appium_runner() -> List[str]:
    return [
        "if __name__ == '__main__':",
        "    try:",
        "        test_flow()",
        "        sys.exit(0)",
        "    except Exception:",
        "        traceback.print_exc()",
        "        sys.exit(1)",
    ]
