# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# AUTO-GENERATED FILE - DO NOT EDIT MANUALLY
# Test Case ID : APPIUM_CLOCK_ALARM_WORLD_TIMER_025
# Generated At : 2026-06-17T06:03:29 UTC
# Generator    : Test Case Script Generator for Automation Frameworks v1
# ------------------------------------------------------------
import os
import sys
import json
import time
import hashlib
import traceback
import re
import base64
from datetime import datetime, timezone
from appium import webdriver
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from appium.options.common.base import AppiumOptions

def _get_step_source(step_fn):
    try:
        with open(__file__, 'r', encoding='utf-8') as f:
            content = f.read()
        func_name = step_fn.__name__
        pattern = rf"def\s+{func_name}\s*\(\s*driver\s*\)\s*:"
        match = re.search(pattern, content)
        if not match: return ""
        start_pos = match.end()
        lines = content[start_pos:].splitlines()
        body_lines = []
        body_indent = None
        for line in lines:
            if not line.strip():
                if body_indent is not None: body_lines.append(line)
                continue
            indent = len(line) - len(line.lstrip())
            if body_indent is None: body_indent = indent
            if indent < body_indent: break
            body_lines.append(line[body_indent:] if len(line) >= body_indent else line)
        return "\n".join(body_lines).strip()
    except Exception:
        return ""

def _guarded_step(driver, step_fn, step_name, step_index, step_code, intent, max_retries, artifacts_dir, success_dir, step_metrics, running_summary_path, device_context=None):
    start_total = time.monotonic()
    attempts = 0
    passed = False
    error_message = None
    device_context = device_context or {}
    device_label = device_context.get('label')
    device_slug = device_context.get('slug')
    relaunch_before_retry = bool(device_context.get('relaunch_before_step_retry', APPIUM_RELAUNCH_BEFORE_STEP_RETRY))

    while attempts <= max_retries:
        attempts += 1
        try:
            if attempts > 1 and relaunch_before_retry:
                _recover_app_state(
                    driver,
                    app_package=device_context.get('app_package'),
                    bundle_id=device_context.get('bundle_id'),
                    restart=True,
                )
            started_at = datetime.now(timezone.utc).isoformat()
            step_fn(driver)
            ended_at = datetime.now(timezone.utc).isoformat()
            passed = True

            duration_total = round(time.monotonic() - start_total, 4)
            success_step_dir = os.path.join(success_dir, step_name)
            os.makedirs(success_step_dir, exist_ok=True)

            try: driver.save_screenshot(os.path.join(success_step_dir, 'screenshot.png'))
            except: pass

            try:
                logs = driver.get_log('logcat')
            except:
                try: logs = driver.get_log('syslog')
                except: logs = []

            if logs:
                with open(os.path.join(success_step_dir, 'console.txt'), 'w', encoding='utf-8') as f:
                    f.write('\n'.join(str(l) for l in logs))

            step_summary = {
                'step_index': step_index,
                'step_name': step_name,
                'intent': intent,
                'started_at': started_at,
                'ended_at': ended_at,
                'duration_sec': duration_total,
                'attempts': attempts,
                'max_retries': max_retries,
                'device_label': device_label,
                'device_slug': device_slug,
                'device_name': device_context.get('device_name'),
                'platform_name': device_context.get('platform_name'),
                'status': 'passed',
                'flaky': attempts > 1,
                'step_code_hash': hashlib.sha256(step_code.encode()).hexdigest()[:12]
            }
            with open(os.path.join(success_step_dir, 'step_summary.json'), 'w', encoding='utf-8') as f:
                json.dump(step_summary, f, indent=2)
            break
        except Exception as e:
            error_message = str(e)
            failures_root = os.path.join(artifacts_dir, 'failures', step_name)
            attempt_dir = os.path.join(failures_root, f'attempt_{attempts}')
            os.makedirs(attempt_dir, exist_ok=True)

            try: driver.save_screenshot(os.path.join(attempt_dir, 'screenshot.png'))
            except: pass

            try:
                with open(os.path.join(attempt_dir, 'dom.xml'), 'w', encoding='utf-8') as f:
                    f.write(driver.page_source)
            except: pass

            try:
                logs = driver.get_log('logcat')
            except:
                try: logs = driver.get_log('syslog')
                except: logs = []

            if logs:
                with open(os.path.join(attempt_dir, 'console.txt'), 'w', encoding='utf-8') as f:
                    f.write('\n'.join(str(l) for l in logs))

            with open(os.path.join(attempt_dir, 'device_context.json'), 'w', encoding='utf-8') as f:
                json.dump(device_context, f, indent=2)
            with open(os.path.join(attempt_dir, 'intent.txt'), 'w', encoding='utf-8') as f: f.write(intent)
            with open(os.path.join(attempt_dir, 'error.txt'), 'w', encoding='utf-8') as f: f.write(error_message)
            with open(os.path.join(attempt_dir, 'traceback.txt'), 'w', encoding='utf-8') as f: f.write(traceback.format_exc())
            with open(os.path.join(attempt_dir, 'step_code.py'), 'w', encoding='utf-8') as f: f.write(_get_step_source(step_fn))

            if attempts <= max_retries:
                print(f'Step {step_index} failed, retrying ({attempts}/{max_retries})...')
                time.sleep(1)

    duration = time.monotonic() - start_total
    metric = {
        'step_index': step_index,
        'step_name': step_name,
        'attempts': attempts,
        'max_retries': max_retries,
        'duration_total_sec': round(duration, 3),
        'device_label': device_label,
        'device_slug': device_slug,
        'device_name': device_context.get('device_name'),
        'platform_name': device_context.get('platform_name'),
        'status': 'passed' if passed else 'failed',
        'flaky': attempts > 1 and passed,
        'step_code_hash': hashlib.sha256(step_code.encode()).hexdigest()[:12]
    }
    if not passed:
        metric['error'] = error_message

    step_metrics.append(metric)

    with open(running_summary_path, 'w', encoding='utf-8') as f:
        json.dump({'status': 'running', 'device': device_context, 'steps': step_metrics}, f, indent=2)

    if not passed:
        device_suffix = f" on {device_label}" if device_label else ''
        raise RuntimeError(f'Step {step_index}{device_suffix} failed after {max_retries} retries: {error_message}')


def _step_0_eafdc5dd4f6e(driver):
    # [ASSERT]
    element = driver.find_element(AppiumBy.XPATH, "//*[@text='Alarm' or @content-desc='Alarm' or @text='Clock' or @content-desc='Clock']")
    assert element.is_displayed()

def _step_1_be3386dcda49(driver):
    element = driver.find_element(AppiumBy.XPATH, "//*[@text='Alarm' or @content-desc='Alarm']")
    element.click()

def _step_2_1b58e8fa8a9a(driver):
    element = driver.find_element(AppiumBy.XPATH, "//*[@content-desc='Add alarm' or @text='Add alarm' or contains(@resource-id, ':id/fab')]")
    element.click()

def _step_3_d870f57f1aa1(driver):
    element = driver.find_element(AppiumBy.XPATH, "//*[@text='7' or @content-desc='7']")
    element.click()

def _step_4_f790d4d79bca(driver):
    element = driver.find_element(AppiumBy.XPATH, "//*[@text='30' or @content-desc='30' or contains(@content-desc, '30 minutes')]")
    element.click()

def _step_5_d39d7f5276f8(driver):
    element = driver.find_element(AppiumBy.XPATH, "//*[@text='OK' or @content-desc='OK' or @text='Done' or @content-desc='Done']")
    element.click()

def _step_6_d74d7f3751ed(driver):
    # [ASSERT]
    element = driver.find_element(AppiumBy.XPATH, "//*[contains(@text, '7:30') or contains(@content-desc, '7:30')]")
    assert element.is_displayed()

def _step_7_53a9221dabc6(driver):
    element = driver.find_element(AppiumBy.XPATH, "//*[@text='Label' or @content-desc='Label' or contains(@resource-id, ':id/edit_label')]")
    element.click()

def _step_8_f3951e7702ce(driver):
    element = driver.find_element(AppiumBy.XPATH, "//*[@class='android.widget.EditText' or contains(@resource-id, ':id/label')]")
    element.send_keys('Morning Demo')

def _step_9_f7f79cffac71(driver):
    element = driver.find_element(AppiumBy.XPATH, "//*[@text='OK' or @content-desc='OK' or @text='Save' or @content-desc='Save']")
    element.click()

def _step_10_16191c097ab5(driver):
    driver.back()

def _step_11_314ce25acd55(driver):
    element = driver.find_element(AppiumBy.XPATH, "//*[@text='Clock' or @content-desc='Clock']")
    element.click()

def _step_12_5f442ebd6baa(driver):
    element = driver.find_element(AppiumBy.XPATH, "//*[@content-desc='Add city' or @text='Add city' or contains(@resource-id, ':id/fab')]")
    element.click()

def _step_13_e7d3b156aa6e(driver):
    element = driver.find_element(AppiumBy.XPATH, "//*[@class='android.widget.EditText' or contains(@text, 'Search') or contains(@content-desc, 'Search')]")
    element.send_keys('London')

def _step_14_e7381950470c(driver):
    try:
        driver.press_keycode(66)
    except Exception:
        driver.switch_to.active_element.send_keys('\n')

def _step_15_ab7dace411dc(driver):
    element = driver.find_element(AppiumBy.XPATH, "//*[contains(@text, 'London') or contains(@content-desc, 'London')]")
    element.click()

def _step_16_398025f99287(driver):
    # [ASSERT]
    element = driver.find_element(AppiumBy.XPATH, "//*[contains(@text, 'London') or contains(@content-desc, 'London')]")
    assert element.is_displayed()

def _step_17_0ac0e5dbafc4(driver):
    element = driver.find_element(AppiumBy.XPATH, "//*[@text='Timer' or @content-desc='Timer']")
    element.click()

def _step_18_046648fbeb96(driver):
    element = driver.find_element(AppiumBy.XPATH, "//*[@text='1' or @content-desc='1']")
    element.click()

def _step_19_7501cc6f5c8e(driver):
    element = driver.find_element(AppiumBy.XPATH, "//*[@text='0' or @content-desc='0']")
    element.click()

def _step_20_5f250dce0e4d(driver):
    element = driver.find_element(AppiumBy.XPATH, "//*[@text='Start' or @content-desc='Start']")
    element.click()

def _step_21_b206e21c25c4(driver):
    element = driver.find_element(AppiumBy.XPATH, "//*[@text='Pause' or @content-desc='Pause']")
    element.click()

def _step_22_6fe145a0bc83(driver):
    element = driver.find_element(AppiumBy.XPATH, "//*[@text='Reset' or @content-desc='Reset' or @text='Delete' or @content-desc='Delete']")
    element.click()

def _step_23_8be022668ab0(driver):
    element = driver.find_element(AppiumBy.XPATH, "//*[@text='Stopwatch' or @content-desc='Stopwatch']")
    element.click()

APPIUM_SERVER_URL = os.environ.get('APPIUM_SERVER_URL', 'http://34.46.45.187:4723/wd/hub')
APPIUM_DEFAULT_CAPABILITIES = {'appium:appActivity': 'com.android.deskclock.DeskClock',
 'appium:appPackage': 'com.google.android.deskclock',
 'appium:appWaitActivity': '*',
 'appium:autoGrantPermissions': False,
 'appium:automationName': 'UiAutomator2',
 'appium:deviceName': 'Pixel_7_API_36',
 'appium:fullReset': False,
 'appium:noReset': True,
 'platformName': 'Android'}
APPIUM_RELAUNCH_BEFORE_TEST = True
APPIUM_RELAUNCH_BEFORE_STEP_RETRY = True

def _parse_appium_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {'1', 'true', 'yes', 'on'}

def _slugify_appium_device(value):
    return re.sub(r'[^A-Za-z0-9]+', '_', str(value or '').strip().lower()).strip('_') or 'device'

def _load_appium_capabilities(default_capabilities):
    capabilities = dict(default_capabilities or {})
    raw = os.environ.get('APPIUM_CAPABILITIES_JSON') or os.environ.get('APPIUM_CAPABILITIES')
    if raw and raw.strip():
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError('APPIUM_CAPABILITIES_JSON must be a JSON object')
        if isinstance(parsed.get('capabilities'), dict):
            parsed = parsed['capabilities']
        capabilities.update(parsed)
    if not any(capabilities.get(k) for k in ('appium:deviceName', 'appium:udid', 'browserName')):
        raise ValueError('Appium capabilities are incomplete. Supply APPIUM_CAPABILITIES_JSON from Executor-Regenerator with at least appium:deviceName or appium:udid.')
    return capabilities

def _load_appium_device_context(capabilities):
    context = {}
    raw = os.environ.get('APPIUM_DEVICE_CONTEXT_JSON')
    if raw and raw.strip():
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError('APPIUM_DEVICE_CONTEXT_JSON must be a JSON object')
        context.update(parsed)
    platform_name = context.get('platform_name') or capabilities.get('platformName')
    device_name = context.get('device_name') or capabilities.get('appium:deviceName') or capabilities.get('deviceName')
    label = os.environ.get('APPIUM_DEVICE_LABEL') or context.get('label') or device_name or 'Appium Device'
    slug = os.environ.get('APPIUM_DEVICE_SLUG') or context.get('slug') or _slugify_appium_device(label)
    context.update({
        'label': label,
        'slug': slug,
        'platform_name': platform_name,
        'device_name': device_name,
        'app_package': context.get('app_package') or capabilities.get('appium:appPackage'),
        'bundle_id': context.get('bundle_id') or capabilities.get('appium:bundleId'),
        'relaunch_before_test': _parse_appium_bool(os.environ.get('APPIUM_RELAUNCH_BEFORE_TEST'), context.get('relaunch_before_test', APPIUM_RELAUNCH_BEFORE_TEST)),
        'relaunch_before_step_retry': _parse_appium_bool(os.environ.get('APPIUM_RELAUNCH_BEFORE_STEP_RETRY'), context.get('relaunch_before_step_retry', APPIUM_RELAUNCH_BEFORE_STEP_RETRY)),
    })
    return context

APPIUM_CAPABILITIES = _load_appium_capabilities(APPIUM_DEFAULT_CAPABILITIES)
APPIUM_DEVICE_CONTEXT = _load_appium_device_context(APPIUM_CAPABILITIES)
APPIUM_APP_PACKAGE = APPIUM_CAPABILITIES.get('appium:appPackage')
APPIUM_BUNDLE_ID = APPIUM_CAPABILITIES.get('appium:bundleId')

def _build_appium_options(capabilities):
    options = AppiumOptions()
    for key, value in capabilities.items():
        if value is not None:
            options.set_capability(key, value)
    return options

def _recover_app_state(driver, app_package=None, bundle_id=None, restart=False):
    app_id = app_package or bundle_id or APPIUM_APP_PACKAGE or APPIUM_BUNDLE_ID
    if not app_id:
        return
    if restart:
        try:
            driver.terminate_app(app_id)
        except Exception:
            pass
    try:
        driver.activate_app(app_id)
    except Exception:
        try:
            driver.execute_script('mobile: activateApp', {'appId': app_id})
        except Exception:
            pass

def test_flow():
    artifacts_root = os.environ.get('ARTIFACTS_DIR', os.path.join(os.getcwd(), 'artifacts'))
    test_case_dir = os.path.join(artifacts_root, 'APPIUM_CLOCK_ALARM_WORLD_TIMER_025', os.environ.get('RUN_ID', '20260617_060329'))
    artifacts_dir = test_case_dir
    success_dir = os.path.join(test_case_dir, 'success')
    failures_dir = os.path.join(test_case_dir, 'failures')
    os.makedirs(success_dir, exist_ok=True)
    os.makedirs(failures_dir, exist_ok=True)
    running_summary_path = os.path.join(failures_dir, 'summary.json')
    overall_status = 'failed'
    startup_error = None
    step_metrics = []
    driver = None
    device_context = dict(APPIUM_DEVICE_CONTEXT)

    with open(os.path.join(artifacts_dir, 'status.txt'), 'w', encoding='utf-8') as f: f.write('running')
    with open(os.path.join(artifacts_dir, 'exit_code.txt'), 'w', encoding='utf-8') as f: f.write('1')
    with open(os.path.join(artifacts_dir, 'started_at.txt'), 'w', encoding='utf-8') as f: f.write(datetime.now(timezone.utc).isoformat())

    try:
        print(f"Running Appium flow on {device_context.get('label')} ({device_context.get('platform_name')})")
        options = _build_appium_options(APPIUM_CAPABILITIES)
        driver = webdriver.Remote(APPIUM_SERVER_URL, options=options)
        driver.implicitly_wait(10)
        if device_context.get('relaunch_before_test'):
            _recover_app_state(
                driver,
                app_package=device_context.get('app_package'),
                bundle_id=device_context.get('bundle_id'),
                restart=True,
            )

        try: driver.start_recording_screen()
        except: pass

        # Steps
        _guarded_step(driver, _step_0_eafdc5dd4f6e, '0__step_0_eafdc5dd4f6e', 0, "# [ASSERT]\n    element = driver.find_element(AppiumBy.XPATH, \"//*[@text='Alarm' or @content-desc='Alarm' or @text='Clock' or @content-desc='Clock']\")\n    assert element.is_displayed()", "Visually confirm the presence of elements belonging to the Clock app", 1, artifacts_dir, success_dir, step_metrics, running_summary_path, device_context)
        _guarded_step(driver, _step_1_be3386dcda49, '1__step_1_be3386dcda49', 1, "element = driver.find_element(AppiumBy.XPATH, \"//*[@text='Alarm' or @content-desc='Alarm']\")\n    element.click()", "Tap the Alarm tab", 1, artifacts_dir, success_dir, step_metrics, running_summary_path, device_context)
        _guarded_step(driver, _step_2_1b58e8fa8a9a, '2__step_2_1b58e8fa8a9a', 2, "element = driver.find_element(AppiumBy.XPATH, \"//*[@content-desc='Add alarm' or @text='Add alarm' or contains(@resource-id, ':id/fab')]\")\n    element.click()", "Tap the add alarm button", 1, artifacts_dir, success_dir, step_metrics, running_summary_path, device_context)
        _guarded_step(driver, _step_3_d870f57f1aa1, '3__step_3_d870f57f1aa1', 3, "element = driver.find_element(AppiumBy.XPATH, \"//*[@text='7' or @content-desc='7']\")\n    element.click()", "Click on hour 7", 1, artifacts_dir, success_dir, step_metrics, running_summary_path, device_context)
        _guarded_step(driver, _step_4_f790d4d79bca, '4__step_4_f790d4d79bca', 4, "element = driver.find_element(AppiumBy.XPATH, \"//*[@text='30' or @content-desc='30' or contains(@content-desc, '30 minutes')]\")\n    element.click()", "Click on '30'", 1, artifacts_dir, success_dir, step_metrics, running_summary_path, device_context)
        _guarded_step(driver, _step_5_d39d7f5276f8, '5__step_5_d39d7f5276f8', 5, "element = driver.find_element(AppiumBy.XPATH, \"//*[@text='OK' or @content-desc='OK' or @text='Done' or @content-desc='Done']\")\n    element.click()", "Click 'OK' or 'Done'", 1, artifacts_dir, success_dir, step_metrics, running_summary_path, device_context)
        _guarded_step(driver, _step_6_d74d7f3751ed, '6__step_6_d74d7f3751ed', 6, "# [ASSERT]\n    element = driver.find_element(AppiumBy.XPATH, \"//*[contains(@text, '7:30') or contains(@content-desc, '7:30')]\")\n    assert element.is_displayed()", "Locate the 7:30 alarm", 1, artifacts_dir, success_dir, step_metrics, running_summary_path, device_context)
        _guarded_step(driver, _step_7_53a9221dabc6, '7__step_7_53a9221dabc6', 7, "element = driver.find_element(AppiumBy.XPATH, \"//*[@text='Label' or @content-desc='Label' or contains(@resource-id, ':id/edit_label')]\")\n    element.click()", "Click 'Label'", 1, artifacts_dir, success_dir, step_metrics, running_summary_path, device_context)
        _guarded_step(driver, _step_8_f3951e7702ce, '8__step_8_f3951e7702ce', 8, "element = driver.find_element(AppiumBy.XPATH, \"//*[@class='android.widget.EditText' or contains(@resource-id, ':id/label')]\")\n    element.send_keys('Morning Demo')", "Type 'Morning Demo' as the alarm label.", 1, artifacts_dir, success_dir, step_metrics, running_summary_path, device_context)
        _guarded_step(driver, _step_9_f7f79cffac71, '9__step_9_f7f79cffac71', 9, "element = driver.find_element(AppiumBy.XPATH, \"//*[@text='OK' or @content-desc='OK' or @text='Save' or @content-desc='Save']\")\n    element.click()", "Click the 'Save' button", 1, artifacts_dir, success_dir, step_metrics, running_summary_path, device_context)
        _guarded_step(driver, _step_10_16191c097ab5, '10__step_10_16191c097ab5', 10, "driver.back()", "Navigate back", 1, artifacts_dir, success_dir, step_metrics, running_summary_path, device_context)
        _guarded_step(driver, _step_11_314ce25acd55, '11__step_11_314ce25acd55', 11, "element = driver.find_element(AppiumBy.XPATH, \"//*[@text='Clock' or @content-desc='Clock']\")\n    element.click()", "Click the Clock tab.", 1, artifacts_dir, success_dir, step_metrics, running_summary_path, device_context)
        _guarded_step(driver, _step_12_5f442ebd6baa, '12__step_12_5f442ebd6baa', 12, "element = driver.find_element(AppiumBy.XPATH, \"//*[@content-desc='Add city' or @text='Add city' or contains(@resource-id, ':id/fab')]\")\n    element.click()", "Tap the add city button", 1, artifacts_dir, success_dir, step_metrics, running_summary_path, device_context)
        _guarded_step(driver, _step_13_e7d3b156aa6e, '13__step_13_e7d3b156aa6e', 13, "element = driver.find_element(AppiumBy.XPATH, \"//*[@class='android.widget.EditText' or contains(@text, 'Search') or contains(@content-desc, 'Search')]\")\n    element.send_keys('London')", "Type London in the city search field", 1, artifacts_dir, success_dir, step_metrics, running_summary_path, device_context)
        _guarded_step(driver, _step_14_e7381950470c, '14__step_14_e7381950470c', 14, "try:\n        driver.press_keycode(66)\n    except Exception:\n        driver.switch_to.active_element.send_keys('\\n')", "Press Enter", 1, artifacts_dir, success_dir, step_metrics, running_summary_path, device_context)
        _guarded_step(driver, _step_15_ab7dace411dc, '15__step_15_ab7dace411dc', 15, "element = driver.find_element(AppiumBy.XPATH, \"//*[contains(@text, 'London') or contains(@content-desc, 'London')]\")\n    element.click()", "Click 'London' in the search results", 1, artifacts_dir, success_dir, step_metrics, running_summary_path, device_context)
        _guarded_step(driver, _step_16_398025f99287, '16__step_16_398025f99287', 16, "# [ASSERT]\n    element = driver.find_element(AppiumBy.XPATH, \"//*[contains(@text, 'London') or contains(@content-desc, 'London')]\")\n    assert element.is_displayed()", "Locate 'London' in the world clock list", 1, artifacts_dir, success_dir, step_metrics, running_summary_path, device_context)
        _guarded_step(driver, _step_17_0ac0e5dbafc4, '17__step_17_0ac0e5dbafc4', 17, "element = driver.find_element(AppiumBy.XPATH, \"//*[@text='Timer' or @content-desc='Timer']\")\n    element.click()", "Click the Timer tab", 1, artifacts_dir, success_dir, step_metrics, running_summary_path, device_context)
        _guarded_step(driver, _step_18_046648fbeb96, '18__step_18_046648fbeb96', 18, "element = driver.find_element(AppiumBy.XPATH, \"//*[@text='1' or @content-desc='1']\")\n    element.click()", "Tap digit 1 in the timer keypad.", 1, artifacts_dir, success_dir, step_metrics, running_summary_path, device_context)
        _guarded_step(driver, _step_19_7501cc6f5c8e, '19__step_19_7501cc6f5c8e', 19, "element = driver.find_element(AppiumBy.XPATH, \"//*[@text='0' or @content-desc='0']\")\n    element.click()", "Tap digit 0", 1, artifacts_dir, success_dir, step_metrics, running_summary_path, device_context)
        _guarded_step(driver, _step_19_7501cc6f5c8e, '20__step_19_7501cc6f5c8e', 20, "element = driver.find_element(AppiumBy.XPATH, \"//*[@text='0' or @content-desc='0']\")\n    element.click()", "Tap digit 0 in the timer keypad", 1, artifacts_dir, success_dir, step_metrics, running_summary_path, device_context)
        _guarded_step(driver, _step_20_5f250dce0e4d, '21__step_20_5f250dce0e4d', 21, "element = driver.find_element(AppiumBy.XPATH, \"//*[@text='Start' or @content-desc='Start']\")\n    element.click()", "Click the 'Start' button.", 1, artifacts_dir, success_dir, step_metrics, running_summary_path, device_context)
        _guarded_step(driver, _step_21_b206e21c25c4, '22__step_21_b206e21c25c4', 22, "element = driver.find_element(AppiumBy.XPATH, \"//*[@text='Pause' or @content-desc='Pause']\")\n    element.click()", "Click the 'Pause' button", 1, artifacts_dir, success_dir, step_metrics, running_summary_path, device_context)
        _guarded_step(driver, _step_22_6fe145a0bc83, '23__step_22_6fe145a0bc83', 23, "element = driver.find_element(AppiumBy.XPATH, \"//*[@text='Reset' or @content-desc='Reset' or @text='Delete' or @content-desc='Delete']\")\n    element.click()", "Click the 'Reset' button.", 1, artifacts_dir, success_dir, step_metrics, running_summary_path, device_context)
        _guarded_step(driver, _step_23_8be022668ab0, '24__step_23_8be022668ab0', 24, "element = driver.find_element(AppiumBy.XPATH, \"//*[@text='Stopwatch' or @content-desc='Stopwatch']\")\n    element.click()", "Click the Stopwatch tab", 1, artifacts_dir, success_dir, step_metrics, running_summary_path, device_context)

        overall_status = 'passed'
        with open(os.path.join(artifacts_dir, 'status.txt'), 'w', encoding='utf-8') as f: f.write('passed')
        with open(os.path.join(artifacts_dir, 'exit_code.txt'), 'w', encoding='utf-8') as f: f.write('0')

    except Exception as e:
        startup_error = str(e) if not step_metrics else startup_error
        overall_status = 'failed'
        if not step_metrics:
            startup_dir = os.path.join(failures_dir, 'startup')
            os.makedirs(startup_dir, exist_ok=True)
            with open(os.path.join(startup_dir, 'error.txt'), 'w', encoding='utf-8') as f: f.write(str(e))
            with open(os.path.join(startup_dir, 'traceback.txt'), 'w', encoding='utf-8') as f: f.write(traceback.format_exc())
            with open(os.path.join(startup_dir, 'device_context.json'), 'w', encoding='utf-8') as f: json.dump(device_context, f, indent=2)
        with open(os.path.join(artifacts_dir, 'status.txt'), 'w', encoding='utf-8') as f: f.write('failed')
        with open(os.path.join(artifacts_dir, 'exit_code.txt'), 'w', encoding='utf-8') as f: f.write('1')
        raise e
    finally:
        if driver:
            try:
                video_b64 = driver.stop_recording_screen()
                if video_b64:
                    video_dst_dir = os.path.join(success_dir, 'video') if overall_status == 'passed' else os.path.join(failures_dir, 'video')
                    os.makedirs(video_dst_dir, exist_ok=True)
                    with open(os.path.join(video_dst_dir, 'recording.mp4'), 'wb') as f:
                        f.write(base64.b64decode(video_b64))
            except: pass
            try:
                driver.quit()
            except: pass

        with open(os.path.join(artifacts_dir, 'finished_at.txt'), 'w', encoding='utf-8') as f: f.write(datetime.now(timezone.utc).isoformat())
        passed = overall_status == 'passed'
        summary = {
            'test_case_id': 'APPIUM_CLOCK_ALARM_WORLD_TIMER_025',
            'run_id': os.environ.get('RUN_ID', '20260617_060329'),
            'status': overall_status,
            'device': device_context,
            'steps': step_metrics,
            'failed_step_index': next((s.get('step_index') for s in step_metrics if s.get('status') == 'failed'), None),
            'failed_device_slug': next((s.get('device_slug') for s in step_metrics if s.get('status') == 'failed'), device_context.get('slug') if overall_status == 'failed' else None),
            'failed_device_label': next((s.get('device_label') for s in step_metrics if s.get('status') == 'failed'), device_context.get('label') if overall_status == 'failed' else None),
        }
        if startup_error:
            summary['startup_error'] = startup_error
        summary_path = os.path.join(success_dir if passed else failures_dir, 'summary.json')
        try:
            tmp = summary_path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(summary, f, indent=2)
            os.replace(tmp, summary_path)
        except Exception:
            pass
if __name__ == '__main__':
    try:
        test_flow()
        sys.exit(0)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
