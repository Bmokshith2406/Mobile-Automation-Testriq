import asyncio

import pytest

from app.core.cost_estimator import CostEstimator
from app.core.token_tracker import add_input_tokens, get_total_tokens, reset_tokens
from app.models.cir import (
    ActionType,
    AssertionType,
    CIRAction,
    CIRAssertion,
    CIRBlock,
    CIRLocator,
    CIRTestCase,
    LocatorStrategy,
    NavigateType,
)
from app.models.appium import AppiumConfig
from app.core.context import active_framework_ctx
from app.models.matched_script import MatchedScript
from app.models import test_case as test_case_models
from app.models.context import CIRBlockContext
from app.services.framework_helpers.action_renderer import ActionRenderer
from app.services.framework_helpers.appium_templates import (
    generate_appium_guard,
    generate_appium_test_wrapper,
)
from app.services.build_helpers.cir_action_builders import CIRActionBuilder
from app.services.generators.base_generator import BaseGenerator
from app.services.generators.appium_generator import AppiumGenerator
from app.services.build_helpers.script_parser import ScriptParser
from app.services.cir_builder import CIRBuilder
from app.services.validator import CIRValidator
from app.services.webhook_notifier import WebhookNotifier


def test_cost_estimator_uses_configured_primary_model():
    estimator = CostEstimator()

    assert estimator.model


def test_script_parser_import_and_selenium_locator_parsing():
    locator = ScriptParser.extract_locator("driver.find_element(By.ID, 'username').click()")

    assert locator is not None
    assert locator.locator_value == "#username"


def test_script_parser_preserves_appium_native_locators():
    accessibility = ScriptParser.extract_locator(
        'driver.find_element(AppiumBy.ACCESSIBILITY_ID, "plus").click()'
    )
    resource_id = ScriptParser.extract_locator(
        'driver.find_element(AppiumBy.ID, "com.google.android.calculator:id/digit_5").click()'
    )

    assert accessibility is not None
    assert accessibility.locator_strategy == LocatorStrategy.test_id
    assert accessibility.locator_value == "plus"
    assert resource_id is not None
    assert resource_id.locator_strategy == LocatorStrategy.id
    assert resource_id.locator_value == "com.google.android.calculator:id/digit_5"


def test_action_builder_keeps_appium_id_locator_from_matched_script():
    token = active_framework_ctx.set("appium")
    try:
        action = asyncio.run(
            CIRActionBuilder().build_action_safe(
                atomic_intent="Click digit 5.",
                expected="5 is entered.",
                matched_script=MatchedScript(
                    language="python",
                    framework="appium",
                    raw_code=(
                        'element = driver.find_element(AppiumBy.ID, '
                        '"com.google.android.calculator:id/digit_5")\n'
                        "element.click()"
                    ),
                ),
            )
        )
    finally:
        active_framework_ctx.reset(token)

    assert action.target is not None
    assert action.target.locator_strategy == LocatorStrategy.id
    assert action.target.locator_value == "com.google.android.calculator:id/digit_5"
    CIRValidator().validate_blocks(
        [CIRBlock(block_id="STEP_01", intent="Click digit 5.", actions=[action])]
    )


def test_action_builder_detects_appium_driver_back_navigation():
    action = asyncio.run(
        CIRActionBuilder().build_action_safe(
            atomic_intent="Close the share/export menu",
            expected="The Canva editor is displayed again.",
            matched_script=MatchedScript(
                language="python",
                framework="appium",
                raw_code="driver.back()",
            ),
        )
    )

    assert action.action_type == ActionType.navigate
    assert action.navigate_type == NavigateType.back


def test_action_builder_handles_appium_enter_key_without_locator():
    token = active_framework_ctx.set("appium")
    try:
        action = asyncio.run(
            CIRActionBuilder().build_action_safe(
                atomic_intent="Press Enter",
                expected="The keyboard action is submitted.",
                matched_script=MatchedScript(
                    language="python",
                    framework="appium",
                    raw_code="driver.press_keycode(66)",
                ),
            )
        )

        assert action.action_type == ActionType.type
        assert action.target is None
        assert action.value == "\n"
        CIRValidator().validate_blocks(
            [CIRBlock(block_id="STEP_ENTER", intent="Press Enter", actions=[action])]
        )

        action_from_intent = asyncio.run(
            CIRActionBuilder().build_action_safe(
                atomic_intent="Press Enter",
                expected="The keyboard action is submitted.",
                matched_script=None,
            )
        )

        assert action_from_intent.action_type == ActionType.type
        assert action_from_intent.target is None
        assert action_from_intent.value == "\n"
    finally:
        active_framework_ctx.reset(token)


def test_appium_generator_renders_targetless_enter_key():
    generator = object.__new__(AppiumGenerator)
    action = CIRAction(action_type=ActionType.type, value="\n")

    rendered = "\n".join(generator._fallback_render_action(action))

    assert "driver.press_keycode(66)" in rendered
    assert "driver.switch_to.active_element.send_keys('\\n')" in rendered
    assert "element =" not in rendered


def test_base_generator_uses_reference_backed_cir_render_without_verifier():
    class StubVerifier:
        def __init__(self):
            self.called = False

        async def verify(self, **kwargs):
            self.called = True
            return {"verdict": "incorrect", "reason": "should not be called"}

    class StubModifier:
        async def modify(self, **kwargs):
            raise AssertionError("modifier should not be called")

    class StubGenerator(BaseGenerator):
        async def generate(self, cir_test_case, context_map) -> str:
            raise NotImplementedError

        def _fallback_render_action(self, action: CIRAction) -> list[str]:
            return ["    driver.back()"]

        def _generate_wait(self, action: CIRAction) -> list[str]:
            return []

    verifier = StubVerifier()
    generator = StubGenerator(verifier, StubModifier())
    block = CIRBlock(
        block_id="STEP_01",
        intent="Return to the previous screen.",
        actions=[
            CIRAction(
                action_type=ActionType.navigate,
                navigate_type=NavigateType.back,
            )
        ],
    )

    body, max_retries = asyncio.run(
        generator._build_step_body(
            block,
            CIRBlockContext(matched_script="  driver.back()\n"),
        )
    )

    assert body == ["driver.back()"]
    assert isinstance(max_retries, int)
    assert verifier.called is False


def test_appium_generator_emits_unique_function_per_logical_step():
    action = CIRAction(
        action_type=ActionType.click,
        target=CIRLocator(
            locator_strategy=LocatorStrategy.id,
            locator_value="com.android.deskclock:id/fab",
        ),
    )
    test_case = CIRTestCase(
        test_case_id="APPIUM_UNIQUE_STEPS",
        description="Two identical logical steps still need unique functions",
        appium_config=AppiumConfig(
            device_name="Pixel 7",
            app_package="com.google.android.deskclock",
            app_activity=".DeskClock",
        ),
        steps=[
            CIRBlock(block_id="STEP_01", intent="Tap add alarm", actions=[action]),
            CIRBlock(block_id="STEP_02", intent="Tap add alarm again", actions=[action]),
        ],
    )

    code = asyncio.run(
        AppiumGenerator().generate(
            test_case,
            {
                "STEP_01": CIRBlockContext(matched_script="driver.find_element(AppiumBy.ID, 'com.android.deskclock:id/fab').click()"),
                "STEP_02": CIRBlockContext(matched_script="driver.find_element(AppiumBy.ID, 'com.android.deskclock:id/fab').click()"),
            },
        )
    )

    assert "def _step_0_" in code
    assert "def _step_1_" in code
    assert code.count("_guarded_step(driver, _step_0_") == 1
    assert code.count("_guarded_step(driver, _step_1_") == 1


def test_appium_generator_allows_assertion_comments_in_guarded_steps():
    action = CIRAction(
        action_type=ActionType.assert_action,
        target=CIRLocator(
            locator_strategy=LocatorStrategy.test_id,
            locator_value="tab|Alarm",
        ),
        assertion=CIRAssertion(assert_type=AssertionType.element_is_visible),
    )
    test_case = CIRTestCase(
        test_case_id="APPIUM_ASSERT_COMMENT",
        description="Assertion steps should survive guarded integrity validation",
        appium_config=AppiumConfig(
            device_name="Pixel 7",
            app_package="com.google.android.deskclock",
            app_activity=".DeskClock",
        ),
        steps=[
            CIRBlock(
                block_id="STEP_01",
                intent="Verify that the Alarm tab is visible.",
                actions=[action],
            ),
        ],
    )

    code = asyncio.run(
        AppiumGenerator().generate(
            test_case,
            {
                "STEP_01": CIRBlockContext(
                    matched_script=(
                        'element = driver.find_element(AppiumBy.XPATH, '
                        '"//*[@text=\'Alarm\' or @content-desc=\'Alarm\']")\n'
                        "assert element.is_displayed()"
                    )
                ),
            },
        )
    )

    assert "# [ASSERT]" in code
    assert "_guarded_step(driver, _step_0_" in code


def test_cir_builder_role_upgrade_only_applies_to_playwright_scripts():
    builder = CIRBuilder()
    appium_script = MatchedScript(
        language="python",
        framework="appium",
        raw_code='driver.find_element(AppiumBy.ACCESSIBILITY_ID, "plus").click()',
    )
    playwright_script = MatchedScript(
        language="python",
        framework="playwright",
        raw_code='page.locator("button").click()',
    )

    assert builder._should_apply_role_upgrade(appium_script) is False
    assert builder._should_apply_role_upgrade(playwright_script) is True


def test_appium_test_case_allows_runtime_capabilities():
    payload = {
        "test_case_id": "APPIUM_RUNTIME_CONFIG",
        "description": "Appium config supplied by Executor-Regenerator",
        "target_framework": "appium",
        "steps": [
            {
                "step_id": "STEP_01",
                "description": "Tap something",
            }
        ],
    }

    test_case = test_case_models.TestCase.model_validate(payload)

    assert test_case.appium_config is None


def test_appium_config_accepts_camel_case_input_aliases():
    payload = {
        "test_case_id": "APPIUM_WITH_CONFIG",
        "description": "Has Appium config",
        "target_framework": "appium",
        "appium_config": {
            "deviceName": "Pixel_8_API_35",
            "appPackage": "com.example.app",
            "appActivity": ".MainActivity",
            "extraCapabilities": {
                "appium:appWaitActivity": ".MainActivity",
            },
        },
        "steps": [
            {
                "step_id": "STEP_01",
                "description": "Tap something",
            }
        ],
    }

    test_case = test_case_models.TestCase.model_validate(payload)

    assert test_case.appium_config is not None
    assert test_case.appium_config.device_name == "Pixel_8_API_35"
    assert test_case.appium_config.app_package == "com.example.app"
    assert test_case.appium_config.app_activity == ".MainActivity"
    assert test_case.appium_config.extra_capabilities == {
        "appium:appWaitActivity": ".MainActivity"
    }


def test_appium_template_emits_input_capabilities_and_relaunch_helpers():
    config = AppiumConfig(
        device_name="Pixel_8_API_35",
        app_package="com.example.app",
        app_activity=".MainActivity",
        extra_capabilities={"appium:appWaitActivity": ".MainActivity"},
    )

    rendered = "\n".join(
        generate_appium_test_wrapper([], "APPIUM_TC", "RUN_001", config)
    )

    assert "APPIUM_SERVER_URL = os.environ.get('APPIUM_SERVER_URL'" in rendered
    assert "'appium:deviceName': 'Pixel_8_API_35'" in rendered
    assert "'appium:appPackage': 'com.example.app'" in rendered
    assert "'appium:appActivity': '.MainActivity'" in rendered
    assert "'appium:appWaitActivity': '.MainActivity'" in rendered
    assert "'appium:noReset': True" in rendered
    assert "driver = webdriver.Remote(APPIUM_SERVER_URL, options=options)" in rendered
    assert "_recover_app_state(" in rendered
    assert "restart=True" in rendered


def test_appium_config_accepts_three_device_matrix_with_ios_target():
    config = AppiumConfig(
        app_package="com.example.android",
        app_activity=".MainActivity",
        app="bs://shared-app-id",
        devices=[
            {
                "label": "Pixel 7",
                "deviceName": "Google Pixel 7",
                "platformName": "Android",
                "platformVersion": "13.0",
            },
            {
                "label": "OnePlus Latest",
                "deviceName": "OnePlus 11",
                "platformName": "Android",
                "platformVersion": "13.0",
            },
            {
                "label": "iPhone Latest",
                "deviceName": "iPhone 15 Pro Max",
                "platformName": "iOS",
                "platformVersion": "17",
                "bundleId": "com.example.ios",
            },
        ],
    )

    assert len(config.devices) == 3
    assert config.devices[2].platform_name == "iOS"
    assert config.devices[2].bundle_id == "com.example.ios"


def test_appium_template_stays_device_agnostic_for_executor_matrix():
    import ast

    config = AppiumConfig(
        app_package="com.example.android",
        app_activity=".MainActivity",
    )

    rendered = "\n".join(
        generate_appium_guard()
        + [
            "",
            "def _step_0_login(driver):",
            "    pass",
            "",
        ]
        + generate_appium_test_wrapper(
            [
                "_guarded_step(driver, _step_0_login, '0__step_0_login', 0, 'pass', 'Tap Login', 1, artifacts_dir, success_dir, step_metrics, running_summary_path, device_context)"
            ],
            "APPIUM_MATRIX_TC",
            "RUN_001",
            config,
        )
    )

    ast.parse(rendered)
    assert "APPIUM_CAPABILITIES_JSON" in rendered
    assert "APPIUM_DEVICE_CONTEXT_JSON" in rendered
    assert "for device_config in APPIUM_DEVICE_MATRIX" not in rendered
    assert "APPIUM_DEVICE_MATRIX_JSON" not in rendered
    assert "APPIUM_DEVICE_FILTER" not in rendered
    assert "APPIUM_DEFAULT_DEVICE_MATRIX" not in rendered
    assert "device_context.json" in rendered
    assert "os.path.join(success_dir, step_name)" in rendered
    assert "os.path.join(artifacts_dir, 'failures', step_name)" in rendered
    assert "'device': device_context" in rendered
    assert "'devices': device_runs" not in rendered


def test_webhook_blocks_private_and_loopback_targets():
    notifier = WebhookNotifier()

    assert notifier._is_valid_url("http://169.254.169.254/latest/meta-data/") is False
    assert notifier._is_valid_url("http://[::1]/hook") is False
    assert notifier._is_valid_url("https://example.com/hook") is True


def test_token_tracker_aggregates_child_tasks():
    async def child():
        add_input_tokens(5)

    async def run():
        reset_tokens()
        await asyncio.gather(child(), child())
        return get_total_tokens()

    assert asyncio.run(run()) == 10


def test_playwright_title_assertion_uses_expected_value():
    action = CIRAction(
        action_type=ActionType.assert_action,
        assertion=CIRAssertion(
            assert_type=AssertionType.title_contains,
            expected_value="Dashboard",
        ),
    )

    rendered = "\n".join(ActionRenderer().render_action(action))

    assert "Dashboard" in rendered
    assert "re.compile(r'.+'" not in rendered
