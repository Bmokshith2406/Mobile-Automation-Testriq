# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# AUTO-GENERATED FILE - DO NOT EDIT MANUALLY
# Test Case ID : TC_PARABANK_END_TO_END_001
# Generated At : 2026-03-01T12:51:13 UTC
# Generator    : Test Case Script Generator for Playwright Python v2.0.0
# ------------------------------------------------------------
import re
import asyncio
import os
import inspect
import sys
import time
from datetime import datetime, timezone
import json
import hashlib
import traceback

from playwright.async_api import async_playwright, expect


async def _guarded_step(page, step_fn, step_name, step_index, step_code, step_intent, max_retries, artifacts_dir, success_dir, step_metrics, summary_path):

    attempts = 0
    start_total = time.monotonic()
    last_dom_hash = None

    for attempt in range(max_retries + 1):
        attempts += 1
        console_logs = []
        def on_console(msg):
            try:
                console_logs.append(msg.text)
            except Exception:
                console_logs.append(str(msg))

        page.on('console', on_console)

        try:
            started_at = datetime.now(timezone.utc).isoformat()
            await step_fn(page)
            ended_at = datetime.now(timezone.utc).isoformat()

            duration_total = round(time.monotonic() - start_total, 4)

            # -------------------------
            # SUCCESS ARTIFACT CAPTURE
            # -------------------------
            success_step_dir = os.path.join(success_dir, step_name)
            os.makedirs(success_step_dir, exist_ok=True)

            await page.screenshot(path=os.path.join(success_step_dir, 'screenshot.png'))

            with open(os.path.join(success_step_dir, 'console.txt'), 'w', encoding='utf-8') as f:
                f.write('\n'.join(console_logs))

            step_summary = {
                'step_index': step_index,
                'step_name': step_name,
                'intent': step_intent,
                'started_at': started_at,
                'ended_at': ended_at,
                'duration_sec': duration_total,
                'url': page.url,
                'attempts': attempts,
                'max_retries': max_retries,
                'status': 'passed',
                'flaky': attempts > 1,
                'step_code_hash': hashlib.sha256(step_code.encode()).hexdigest()[:12]
            }

            with open(os.path.join(success_step_dir, 'step_summary.json'), 'w', encoding='utf-8') as f:
                json.dump(step_summary, f, indent=2)

            step_metrics.append({
                'step_index': step_index,
                'step_name': step_name,
                'attempts': attempts,
                'max_retries': max_retries,
                'duration_total_sec': duration_total,
                'status': 'passed',
                'flaky': attempts > 1,
                'step_code_hash': hashlib.sha256(step_code.encode()).hexdigest()[:12]
            })

            tmp = summary_path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump({
                    'status': 'running',
                    'current_step_index': step_index,
                    'steps': step_metrics,
                }, f, indent=2)
            os.replace(tmp, summary_path)

            # Live status update
            with open(os.path.join(artifacts_dir, 'status.txt'), 'w', encoding='utf-8') as f:
                f.write('running')

            return

        except Exception as exc:
            failures_root = os.path.join(artifacts_dir, 'failures', step_name)
            attempt_dir = os.path.join(failures_root, f'attempt_{attempt + 1}')
            os.makedirs(attempt_dir, exist_ok=True)

            await page.screenshot(path=os.path.join(attempt_dir, 'screenshot.png'))

            dom = await page.content()
            dom_hash = hashlib.sha256(dom.encode()).hexdigest()

            if last_dom_hash != dom_hash or attempt == max_retries:
                with open(os.path.join(attempt_dir, 'dom.html'), 'w', encoding='utf-8') as f:
                    f.write(dom)

            last_dom_hash = dom_hash

            with open(os.path.join(attempt_dir, 'console.txt'), 'w', encoding='utf-8') as f:
                f.write('\n'.join(console_logs))
            with open(os.path.join(attempt_dir, 'intent.txt'), 'w', encoding='utf-8') as f:
                f.write(step_intent)

            with open(os.path.join(attempt_dir, 'error.txt'), 'w', encoding='utf-8') as f:
                f.write(f'{type(exc).__name__}: {exc}')

            with open(os.path.join(attempt_dir, 'traceback.txt'), 'w', encoding='utf-8') as f:
                f.write(traceback.format_exc())

            live_code = inspect.getsource(step_fn)

            with open(os.path.join(attempt_dir, 'step_code.py'), 'w', encoding='utf-8') as f:
                f.write(live_code)

            if attempt == max_retries:
                duration_total = round(time.monotonic() - start_total, 4)

                step_metrics.append({
                    'step_index': step_index,
                    'step_name': step_name,
                    'attempts': attempts,
                    'max_retries': max_retries,
                    'duration_total_sec': duration_total,
                    'status': 'failed',
                    'flaky': False,
                    'step_code_hash': hashlib.sha256(step_code.encode()).hexdigest()[:12]
                })

                tmp = summary_path + '.tmp'
                with open(tmp, 'w', encoding='utf-8') as f:
                    json.dump({
                        'status': 'failed',
                        'failed_step_index': step_index,
                        'steps': step_metrics,
                    }, f, indent=2)
                os.replace(tmp, summary_path)

                # Live failure status
                with open(os.path.join(artifacts_dir, 'status.txt'), 'w', encoding='utf-8') as f:
                    f.write('failed')

                raise

            await page.wait_for_timeout(1000)

        finally:
            try:
                if hasattr(page, 'off'):
                    page.off('console', on_console)
            except Exception:
                pass

async def _step_0_3fda4f10f510(page):
    await page.goto('https://parabank.parasoft.com/parabank/index.htm', wait_until='domcontentloaded')

async def _step_1_2f2a76d5f50f(page):
    await page.wait_for_selector('[name="username"]', timeout=10000, state='visible')
    locator = page.locator('[name="username"]')
    # [ASSERT]
    await expect(locator.first).to_be_visible(timeout=5000)

async def _step_2_e35ecbfe67d3(page):
    await page.wait_for_selector("input[name='username']", timeout=10000, state='visible')
    locator = page.locator("input[name='username']")
    target = locator.first
    await expect(target).to_be_visible(timeout=5000)
    await target.fill('john')

async def _step_3_58b7ea696c53(page):
    await page.wait_for_selector("input[name='password']", timeout=10000, state='visible')
    locator = page.locator("input[name='password']")
    target = locator.first
    await expect(target).to_be_visible(timeout=5000)
    await target.fill('demo')

async def _step_4_52eba612da99(page):
    await page.wait_for_selector("input[type='submit']", timeout=10000, state='visible')
    locator = page.locator("input[type='submit']")
    target = locator.first
    await expect(target).to_be_visible(timeout=5000)
    await target.click()

async def _step_5_2b7ba04154aa(page):
    locator = page.get_by_role('heading', name='Accounts Overview')
    # [ASSERT]
    await expect(locator.first).to_be_visible(timeout=5000)

async def _step_6_59a25a3cbfcc(page):
    locator = page.locator("a:has-text('Open New Account')")
    target = locator.first
    await expect(target).to_be_visible(timeout=5000)
    await target.click()

async def _step_7_826e7c434f2a(page):
    await page.wait_for_selector('select#type', timeout=10000, state='visible')
    locator = page.locator('select#type')
    target = locator.first
    await expect(target).to_be_visible(timeout=5000)
    await target.select_option('1')

async def _step_8_fe47d5187f7a(page):
    locator = page.get_by_role('button', name='Open New Account')
    target = locator.first
    await expect(target).to_be_visible(timeout=5000)
    await target.click()

async def _step_9_f2be48bb22e9(page):
    locator = page.locator("//*[normalize-space()='Congratulations, your account is now open.']")
    # [ASSERT]
    await expect(locator.first).to_have_text('Congratulations, your account is now open.', timeout=5000)

async def _step_10_1997a082a4fb(page):
    locator = page.get_by_text('Accounts Overview')
    target = locator.first
    await expect(target).to_be_visible(timeout=5000)
    await target.click()

async def _step_11_70d770862a49(page):
    locator = page.get_by_text('Transfer Funds')
    target = locator.first
    await expect(target).to_be_visible(timeout=5000)
    await target.click()

async def _step_12_477b6db4e226(page):
    await page.wait_for_selector('#amount', timeout=10000, state='visible')
    locator = page.locator('#amount')
    target = locator.first
    await expect(target).to_be_visible(timeout=5000)
    await target.fill('100')

async def _step_13_9913e0b207ce(page):
    locator = page.get_by_role('button', name='Transfer')
    target = locator.first
    await expect(target).to_be_visible(timeout=5000)
    await target.click()

async def _step_14_8f9d6f18ef3b(page):
    locator = page.locator("//*[normalize-space()='Transfer Complete!']")
    # [ASSERT]
    await expect(locator.first).to_have_text('Transfer Complete!', timeout=5000)

async def _step_15_4d18db3638a4(page):
    locator = page.locator("a:has-text('Log Out')")
    target = locator.first
    await expect(target).to_be_visible(timeout=5000)
    await target.click()


async def test_flow():

    # -------------------------
    # Initialization
    # -------------------------
    artifacts_root = os.environ.get('ARTIFACTS_DIR')

    if not artifacts_root:
        artifacts_root = os.path.join(os.getcwd(), 'artifacts')

    test_case_id = 'TC_PARABANK_END_TO_END_001'
    run_id = os.environ.get('RUN_ID', '20260301_125049')

    test_case_dir = os.path.join(artifacts_root, test_case_id, run_id)
    artifacts_dir = test_case_dir
    artifacts_dir = test_case_dir

    success_dir = os.path.join(test_case_dir, 'success')
    failures_dir = os.path.join(test_case_dir, 'failures')
    video_tmp_dir = os.path.join(test_case_dir, '_video_tmp')

    os.makedirs(success_dir, exist_ok=True)
    os.makedirs(failures_dir, exist_ok=True)
    os.makedirs(video_tmp_dir, exist_ok=True)

    running_summary_path = os.path.join(failures_dir, 'summary.json')

    step_metrics = []
    error = None
    summary = None

    started_at = datetime.now(timezone.utc).isoformat()
    finished_at = None

    status = 'running'
    exit_code = 1

    browser = None
    context = None

    # -------------------------
    # GUARANTEED INITIAL STATE
    # -------------------------
    with open(os.path.join(artifacts_dir, 'status.txt'), 'w', encoding='utf-8') as f:
        f.write('running')

    with open(os.path.join(artifacts_dir, 'exit_code.txt'), 'w', encoding='utf-8') as f:
        f.write('1')

    with open(os.path.join(artifacts_dir, 'started_at.txt'), 'w', encoding='utf-8') as f:
        f.write(started_at)

    with open(os.path.join(artifacts_dir, 'finished_at.txt'), 'w', encoding='utf-8') as f:
        f.write('')

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                record_video_dir=video_tmp_dir,
                record_video_size={'width': 1280, 'height': 720},
            )
            page = await context.new_page()

            # -------------------------
            # Execute steps
            # -------------------------
            await _guarded_step(page, _step_0_3fda4f10f510, '0__step_0_3fda4f10f510', 0, "await page.goto('https://parabank.parasoft.com/parabank/index.htm', wait_until='domcontentloaded')", "Navigate to https://parabank.parasoft.com/parabank/index.htm", 1, artifacts_dir, success_dir, step_metrics, running_summary_path)
            await _guarded_step(page, _step_1_2f2a76d5f50f, '1__step_1_2f2a76d5f50f', 1, "await page.wait_for_selector('[name=\"username\"]', timeout=10000, state='visible')\nlocator = page.locator('[name=\"username\"]')\n# [ASSERT]\nawait expect(locator.first).to_be_visible(timeout=5000)", "Assert username input field is visible.", 1, artifacts_dir, success_dir, step_metrics, running_summary_path)
            await _guarded_step(page, _step_2_e35ecbfe67d3, '2__step_2_e35ecbfe67d3', 2, "await page.wait_for_selector(\"input[name='username']\", timeout=10000, state='visible')\nlocator = page.locator(\"input[name='username']\")\ntarget = locator.first\nawait expect(target).to_be_visible(timeout=5000)\nawait target.fill('john')", "Type 'john' into username input field.", 1, artifacts_dir, success_dir, step_metrics, running_summary_path)
            await _guarded_step(page, _step_3_58b7ea696c53, '3__step_3_58b7ea696c53', 3, "await page.wait_for_selector(\"input[name='password']\", timeout=10000, state='visible')\nlocator = page.locator(\"input[name='password']\")\ntarget = locator.first\nawait expect(target).to_be_visible(timeout=5000)\nawait target.fill('demo')", "Type 'demo' into password input field.", 1, artifacts_dir, success_dir, step_metrics, running_summary_path)
            await _guarded_step(page, _step_4_52eba612da99, '4__step_4_52eba612da99', 4, "await page.wait_for_selector(\"input[type='submit']\", timeout=10000, state='visible')\nlocator = page.locator(\"input[type='submit']\")\ntarget = locator.first\nawait expect(target).to_be_visible(timeout=5000)\nawait target.click()", "Click login submit button.", 1, artifacts_dir, success_dir, step_metrics, running_summary_path)
            await _guarded_step(page, _step_5_2b7ba04154aa, '5__step_5_2b7ba04154aa', 5, "locator = page.get_by_role('heading', name='Accounts Overview')\n# [ASSERT]\nawait expect(locator.first).to_be_visible(timeout=5000)", "Assert text 'Accounts Overview' is visible.", 1, artifacts_dir, success_dir, step_metrics, running_summary_path)
            await _guarded_step(page, _step_6_59a25a3cbfcc, '6__step_6_59a25a3cbfcc', 6, "locator = page.locator(\"a:has-text('Open New Account')\")\ntarget = locator.first\nawait expect(target).to_be_visible(timeout=5000)\nawait target.click()", "Click link with text 'Open New Account'.", 1, artifacts_dir, success_dir, step_metrics, running_summary_path)
            await _guarded_step(page, _step_7_826e7c434f2a, '7__step_7_826e7c434f2a', 7, "await page.wait_for_selector('select#type', timeout=10000, state='visible')\nlocator = page.locator('select#type')\ntarget = locator.first\nawait expect(target).to_be_visible(timeout=5000)\nawait target.select_option('1')", "Select option value '1' in account type dropdown.", 1, artifacts_dir, success_dir, step_metrics, running_summary_path)
            await _guarded_step(page, _step_8_fe47d5187f7a, '8__step_8_fe47d5187f7a', 8, "locator = page.get_by_role('button', name='Open New Account')\ntarget = locator.first\nawait expect(target).to_be_visible(timeout=5000)\nawait target.click()", "Click button with value 'Open New Account'.", 1, artifacts_dir, success_dir, step_metrics, running_summary_path)
            await _guarded_step(page, _step_9_f2be48bb22e9, '9__step_9_f2be48bb22e9', 9, "locator = page.locator(\"//*[normalize-space()='Congratulations, your account is now open.']\")\n# [ASSERT]\nawait expect(locator.first).to_have_text('Congratulations, your account is now open.', timeout=5000)", "Assert text 'Congratulations, your account is now open.' is visible.", 1, artifacts_dir, success_dir, step_metrics, running_summary_path)
            await _guarded_step(page, _step_10_1997a082a4fb, '10__step_10_1997a082a4fb', 10, "locator = page.locator(\"a:has-text('Accounts Overview')\")\ntarget = locator.first\nawait expect(target).to_be_visible(timeout=5000)\nawait target.click()", "Click link with text 'Accounts Overview'.", 1, artifacts_dir, success_dir, step_metrics, running_summary_path)
            await _guarded_step(page, _step_11_70d770862a49, '11__step_11_70d770862a49', 11, "locator = page.locator(\"a:has-text('Transfer Funds')\")\ntarget = locator.first\nawait expect(target).to_be_visible(timeout=5000)\nawait target.click()", "Click link with text 'Transfer Funds'.", 1, artifacts_dir, success_dir, step_metrics, running_summary_path)
            await _guarded_step(page, _step_12_477b6db4e226, '12__step_12_477b6db4e226', 12, "await page.wait_for_selector('#amount', timeout=10000, state='visible')\nlocator = page.locator('#amount')\ntarget = locator.first\nawait expect(target).to_be_visible(timeout=5000)\nawait target.fill('100')", "Type '100' into input field with id 'amount'.", 1, artifacts_dir, success_dir, step_metrics, running_summary_path)
            await _guarded_step(page, _step_13_9913e0b207ce, '13__step_13_9913e0b207ce', 13, "locator = page.get_by_role('button', name='Transfer')\ntarget = locator.first\nawait expect(target).to_be_visible(timeout=5000)\nawait target.click()", "Click button with value 'Transfer'.", 1, artifacts_dir, success_dir, step_metrics, running_summary_path)
            await _guarded_step(page, _step_14_8f9d6f18ef3b, '14__step_14_8f9d6f18ef3b', 14, "locator = page.locator(\"//*[normalize-space()='Transfer Complete!']\")\n# [ASSERT]\nawait expect(locator.first).to_have_text('Transfer Complete!', timeout=5000)", "Assert text 'Transfer Complete!' is visible.", 1, artifacts_dir, success_dir, step_metrics, running_summary_path)
            await _guarded_step(page, _step_15_4d18db3638a4, '15__step_15_4d18db3638a4', 15, "locator = page.locator(\"a:has-text('Log Out')\")\ntarget = locator.first\nawait expect(target).to_be_visible(timeout=5000)\nawait target.click()", "Click link with text 'Log Out'.", 1, artifacts_dir, success_dir, step_metrics, running_summary_path)
            await _guarded_step(page, _step_1_2f2a76d5f50f, '16__step_1_2f2a76d5f50f', 16, "await page.wait_for_selector('[name=\"username\"]', timeout=10000, state='visible')\nlocator = page.locator('[name=\"username\"]')\n# [ASSERT]\nawait expect(locator.first).to_be_visible(timeout=5000)", "Assert username input field is visible.", 1, artifacts_dir, success_dir, step_metrics, running_summary_path)

        # -------------------------
        # Determine outcome
        # -------------------------
        passed = bool(step_metrics) and not any(
            s.get('status') == 'failed' for s in step_metrics
        )

        status = 'passed' if passed else 'failed'
        exit_code = 0 if passed else 1

        with open(os.path.join(artifacts_dir, 'status.txt'), 'w', encoding='utf-8') as f:
            f.write(status)

        with open(os.path.join(artifacts_dir, 'exit_code.txt'), 'w', encoding='utf-8') as f:
            f.write(str(exit_code))

        # -------------------------
        # Video handling
        # -------------------------
        video_dst_dir = (
            os.path.join(success_dir, 'video')
            if passed
            else os.path.join(failures_dir, 'video')
        )
        os.makedirs(video_dst_dir, exist_ok=True)

        failed_step = next(
            (s for s in step_metrics if s.get('status') == 'failed'),
            None,
        )

        for root, _, files in os.walk(video_tmp_dir):
            for f in files:
                if f.endswith('.webm'):
                    src = os.path.join(root, f)
                    if not passed and failed_step:
                        dst = os.path.join(
                            video_dst_dir,
                            f"failed_at_step_{failed_step.get('step_index')}.webm",
                        )
                    else:
                        dst = os.path.join(video_dst_dir, f)
                    os.replace(src, dst)

        # -------------------------
        # Final summary
        # -------------------------
        summary = {
            'test_case_id': 'TC_PARABANK_END_TO_END_001',
            'run_id': '20260301_125049',
            'status': status,
            'error': error,
            'steps': step_metrics,
            'failed_step_index': next(
                (s.get('step_index') for s in step_metrics if s.get('status') == 'failed'),
                None,
            ),
        }

        final_summary_path = (
            os.path.join(success_dir, 'summary.json')
            if passed
            else running_summary_path
        )

        tmp = final_summary_path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2)
        os.replace(tmp, final_summary_path)

    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        raise

    finally:
        finished_at = datetime.now(timezone.utc).isoformat()

        try:
            if context:
                await context.close()
            if browser:
                await browser.close()
        except Exception:
            pass

        if summary is None:
            summary = {
                'test_case_id': 'TC_PARABANK_END_TO_END_001',
                'run_id': '20260301_125049',
                'status': 'failed',
                'error': error or 'Execution terminated before summary generation',
                'steps': step_metrics,
                'failed_step_index': None,
            }

        with open(os.path.join(artifacts_dir, 'status.txt'), 'w', encoding='utf-8') as f:
            f.write(summary['status'])

        with open(os.path.join(artifacts_dir, 'exit_code.txt'), 'w', encoding='utf-8') as f:
            f.write(str(exit_code))

        with open(os.path.join(artifacts_dir, 'started_at.txt'), 'w', encoding='utf-8') as f:
            f.write(started_at)

        with open(os.path.join(artifacts_dir, 'finished_at.txt'), 'w', encoding='utf-8') as f:
            f.write(finished_at)

    return summary


if __name__ == '__main__':
    import traceback
    import sys

    exit_code = 1

    try:
        summary = asyncio.run(test_flow())
        status = summary.get('status') if isinstance(summary, dict) else None
        exit_code = 0 if status == 'passed' else 1
    except BaseException:
        traceback.print_exc()
        exit_code = 1

    sys.exit(exit_code)
