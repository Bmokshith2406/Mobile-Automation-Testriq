from pydantic import BaseModel, Field, model_validator
from typing import List, Optional
from enum import Enum

from app.models.appium import AppiumConfig

_ID_PATTERN = r"^[A-Za-z0-9_\-]+$"

# =========================
# ENUMS
# =========================

class ActionType(str, Enum):
    navigate = "navigate"
    click = "click"
    type = "type"
    clear = "clear"
    select = "select"
    assert_action = "assert_action"
    hover = "hover"
    scroll = "scroll"
    drag_drop = "drag_drop"
    upload_file = "upload_file"
    keyboard = "keyboard"
    switch_frame = "switch_frame"
    switch_window = "switch_window"
    execute_script = "execute_script"
    double_click = "double_click"
    right_click = "right_click"
    wait_for = "wait_for"


class NavigateType(str, Enum):
    url = "url"
    back = "back"
    forward = "forward"
    refresh = "refresh"


class LocatorStrategy(str, Enum):
    id = "id"
    name = "name"
    css = "css"
    xpath = "xpath"
    class_name = "class"
    tag = "tag"
    text = "text"

    # Playwright semantic locators
    role = "role"
    test_id = "test_id"
    placeholder = "placeholder"
    label = "label"
    uiautomator = "uiautomator"
    ios_class_chain = "ios_class_chain"
    ios_predicate_string = "ios_predicate_string"
    android_data_matcher = "android_data_matcher"


class WaitCondition(str, Enum):
    visible = "visible"
    hidden = "hidden"
    attached = "attached"
    detached = "detached"
    url_contains = "url_contains"
    clickable = "clickable"
    presence = "presence"
    text_present = "text_present"
    count_equals = "count_equals"
    staleness = "staleness"
    network_idle = "network_idle"
    load_state = "load_state"


class AssertionType(str, Enum):
    text_equals = "text_equals"
    text_contains = "text_contains"
    element_is_visible = "element_is_visible"
    url_contains = "url_contains"
    title_equals = "title_equals"
    title_contains = "title_contains"
    attribute_equals = "attribute_equals"
    attribute_contains = "attribute_contains"
    element_count = "element_count"
    element_enabled = "element_enabled"
    element_disabled = "element_disabled"
    element_checked = "element_checked"
    element_unchecked = "element_unchecked"
    element_value = "element_value"
    list_contains = "list_contains"
    page_source_contains = "page_source_contains"



class CIRBlockType(str, Enum):
    setup = "setup"
    step = "step"
    fallback = "fallback"
    teardown = "teardown"


# =========================
# CORE MODELS
# =========================

class CIRLocator(BaseModel):
    locator_strategy: LocatorStrategy
    locator_value: str = Field(..., min_length=1)

    @model_validator(mode="after")
    def validate_locator(self):
        v = self.locator_value.strip()

        if not v:
            raise ValueError("locator_value cannot be empty")

        if self.locator_strategy == LocatorStrategy.role:
            # role must be in format: role|name
            if "|" not in v:
                raise ValueError(
                    "role locator must be in format: 'role|name' (e.g., 'button|Login')"
                )

        return self


class CIRWait(BaseModel):
    condition: WaitCondition
    timeout: int = Field(default=15, ge=1, le=60)


class CIRAssertion(BaseModel):
    assert_type: AssertionType
    expected_value: Optional[str] = None

    @model_validator(mode="after")
    def validate_expected_value(self):
        if self.assert_type in {
            AssertionType.text_equals,
            AssertionType.text_contains,
            AssertionType.url_contains,
            AssertionType.title_equals,
            AssertionType.title_contains,
        } and not self.expected_value:

            raise ValueError(
                f"expected_value required for assertion type {self.assert_type}"
            )
        return self


class CIRAction(BaseModel):
    action_type: ActionType

    navigate_type: Optional[NavigateType] = None
    target: Optional[CIRLocator] = None
    value: Optional[str] = None
    value_mode: Optional[str] = Field(
        default="value",
        description="value | index | label"
    )

    wait: Optional[CIRWait] = None
    assertion: Optional[CIRAssertion] = None

    # For drag_drop
    drag_target: Optional[CIRLocator] = None

    # For keyboard
    key_combination: Optional[str] = None

    # For switch_frame / switch_window
    frame_locator: Optional[str] = None
    window_index: Optional[int] = None

    # For execute_script
    script_expression: Optional[str] = None

    # For scroll
    scroll_direction: Optional[str] = None
    scroll_amount: Optional[int] = None

    # For upload_file
    file_path_to_upload: Optional[str] = None

    # For wait_for
    wait_for_condition: Optional[str] = None
    wait_for_timeout: Optional[int] = None

    # For attribute assertions
    attribute_name: Optional[str] = None
    expected_count: Optional[int] = None

    @model_validator(mode="after")
    def validate_action_semantics(self):

        # -------------------------
        # NAVIGATE
        # -------------------------
        if self.action_type == ActionType.navigate:
            if not self.navigate_type:
                raise ValueError("navigate_type required for navigate action")

        # -------------------------
        # CLICK
        # -------------------------
        if self.action_type == ActionType.click:
            if not self.target:
                raise ValueError("target required for click action")

        # -------------------------
        # TYPE (TARGET OPTIONAL)
        # -------------------------
        if self.action_type == ActionType.type:
            if self.value is None:
                raise ValueError("value required for type action")
            # target is OPTIONAL → active element typing supported
        
        # -------------------------
        # CLEAR
        # -------------------------
        if self.action_type == ActionType.clear:
            if not self.target:
                raise ValueError("target required for clear action")


        # -------------------------
        # SELECT
        # -------------------------
        if self.action_type == ActionType.select:
            if not self.target:
                raise ValueError("target required for select action")
            if self.value is None:
                raise ValueError("value required for select action")
            if self.value_mode not in {"value", "index", "label"}:
                raise ValueError("invalid value_mode for select action")

        # -------------------------
        # ASSERT
        # -------------------------
        if self.action_type == ActionType.assert_action:
            if not self.assertion:
                raise ValueError("assertion required for assert action")

        if self.action_type == ActionType.hover:
            if not self.target:
                raise ValueError("target required for hover action")
        if self.action_type == ActionType.double_click:
            if not self.target:
                raise ValueError("target required for double_click action")
        if self.action_type == ActionType.right_click:
            if not self.target:
                raise ValueError("target required for right_click action")
        if self.action_type == ActionType.keyboard:
            if not self.key_combination:
                raise ValueError("key_combination required for keyboard action")
        if self.action_type == ActionType.upload_file:
            if not self.target:
                raise ValueError("target required for upload_file action")
            if not self.file_path_to_upload:
                raise ValueError("file_path_to_upload required for upload_file action")
        if self.action_type == ActionType.drag_drop:
            if not self.target:
                raise ValueError("target required for drag_drop action")
            if not self.drag_target:
                raise ValueError("drag_target required for drag_drop action")
        if self.action_type == ActionType.execute_script:
            if not self.script_expression:
                raise ValueError("script_expression required for execute_script action")

        return self


class CIRBlock(BaseModel):
    block_id: str = Field(
        ...,
        min_length=1,
        pattern=_ID_PATTERN,
    )
    intent: str
    actions: List[CIRAction] = Field(..., min_length=1)
    block_type: CIRBlockType = Field(default=CIRBlockType.step)


class CIRTestCase(BaseModel):
    test_case_id: str
    description: str
    appium_config: Optional[AppiumConfig] = None

    setup: List[CIRBlock] = Field(default_factory=list)
    steps: List[CIRBlock] = Field(..., min_length=1)
    teardown: List[CIRBlock] = Field(default_factory=list)

