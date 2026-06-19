# app/models/cir.py

from pydantic import BaseModel, Field, model_validator
from typing import List, Optional, Any
from enum import Enum


# =========================
# ENUMS
# =========================

class ActionType(str, Enum):
    navigate = "navigate"
    click = "click"
    type = "type"
    select = "select"
    assert_action = "assert"
    handle_dialog = "handle_dialog"
    # Enhanced: 11 new action types
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
    role = "role"
    test_id = "test_id"
    placeholder = "placeholder"
    label = "label"
    uiautomator = "uiautomator"
    # Enhanced: 3 new mobile locator strategies
    ios_class_chain = "ios_class_chain"
    ios_predicate_string = "ios_predicate_string"
    android_data_matcher = "android_data_matcher"


class WaitCondition(str, Enum):
    visible = "visible"
    hidden = "hidden"
    attached = "attached"
    detached = "detached"
    url_contains = "url_contains"
    # Enhanced: 7 new wait conditions
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
    # Enhanced: 10 new assertion types
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


class DialogAction(str, Enum):
    accept = "accept"
    dismiss = "dismiss"
    close = "close"


# =========================
# CORE MODELS
# =========================

class CIRLocator(BaseModel):
    locator_strategy: LocatorStrategy
    locator_value: str = Field(..., min_length=1)


class CIRWait(BaseModel):
    condition: WaitCondition
    timeout: int = Field(default=15, ge=1, le=60)


class StepWait(BaseModel):
    """
    Required by extraction layer.
    DO NOT REMOVE.
    """
    condition: WaitCondition = WaitCondition.visible
    timeout_seconds: int = Field(default=15, ge=1, le=60)


class CIRAssertion(BaseModel):
    assert_type: AssertionType
    expected_value: Optional[str] = None

    @model_validator(mode="after")
    def validate_expected_value(self):
        requires_expected = {
            AssertionType.text_equals,
            AssertionType.text_contains,
            AssertionType.url_contains,
            AssertionType.title_equals,
            AssertionType.title_contains,
            AssertionType.attribute_equals,
            AssertionType.attribute_contains,
            AssertionType.element_value,
            AssertionType.list_contains,
            AssertionType.page_source_contains,
        }
        if self.assert_type in requires_expected and not self.expected_value:
            raise ValueError(
                f"expected_value required for assertion type {self.assert_type}"
            )
        return self


# =========================
# DIALOG MODEL
# =========================

class CIRDialog(BaseModel):
    """
    Represents a runtime interruption (cookie banner, alert, modal).
    """
    action: DialogAction
    target: Optional[CIRLocator] = None


# =========================
# ACTION MODEL
# =========================

class CIRAction(BaseModel):
    action_type: ActionType

    # Shared / optional
    target: Optional[CIRLocator] = None
    locator: Optional[str] = None
    description: Optional[str] = None
    value: Optional[str] = None
    wait: Optional[CIRWait] = None

    # Navigate
    navigate_type: Optional[NavigateType] = None

    # Assert
    assertion: Optional[CIRAssertion] = None

    # Dialog
    dialog: Optional[CIRDialog] = None

    # Enhanced: new fields for expanded action types
    drag_target: Optional[CIRLocator] = None
    key_combination: Optional[str] = None
    frame_locator: Optional[str] = None
    window_index: Optional[int] = None
    script_expression: Optional[str] = None
    scroll_direction: Optional[str] = None
    scroll_amount: Optional[int] = None
    file_path_to_upload: Optional[str] = None
    wait_for_condition: Optional[WaitCondition] = None
    wait_for_timeout: Optional[int] = None
    attribute_name: Optional[str] = None
    expected_count: Optional[int] = None

    @model_validator(mode="before")
    @classmethod
    def populate_target_and_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            locator = data.get("locator")
            target = data.get("target")

            if locator and not target:
                strategy = LocatorStrategy.css
                val = locator
                if isinstance(locator, str):
                    if locator.startswith("text="):
                        strategy = LocatorStrategy.text
                        val = locator[5:].strip("'\"")
                    elif locator.startswith("xpath="):
                        strategy = LocatorStrategy.xpath
                        val = locator[6:]
                    elif locator.startswith("id="):
                        strategy = LocatorStrategy.id
                        val = locator[3:]
                data["target"] = {
                    "locator_strategy": strategy,
                    "locator_value": val
                }
            elif target and not locator:
                if isinstance(target, dict):
                    data["locator"] = target.get("locator_value")
                elif hasattr(target, "locator_value"):
                    data["locator"] = target.locator_value
        return data

    @model_validator(mode="after")
    def validate_action_semantics(self):
        if self.action_type == ActionType.navigate:
            if not self.navigate_type:
                raise ValueError("navigate_type required for navigate action")

        if self.action_type == ActionType.click:
            if not self.target:
                raise ValueError("target required for click action")

        if self.action_type == ActionType.type:
            if self.value is None:
                raise ValueError("value required for type action")

        if self.action_type == ActionType.select:
            if not self.target:
                raise ValueError("target required for select action")
            if not self.value:
                raise ValueError("value required for select action")

        if self.action_type == ActionType.assert_action:
            if not self.assertion:
                raise ValueError("assertion required for assert action")

        if self.action_type == ActionType.handle_dialog:
            if not self.dialog:
                raise ValueError("dialog required for handle_dialog action")

        if self.action_type == ActionType.hover:
            if not self.target:
                raise ValueError("target required for hover action")

        if self.action_type == ActionType.double_click:
            if not self.target:
                raise ValueError("target required for double_click action")

        if self.action_type == ActionType.right_click:
            if not self.target:
                raise ValueError("target required for right_click action")

        if self.action_type == ActionType.drag_drop:
            if not self.target:
                raise ValueError("source target required for drag_drop action")

        if self.action_type == ActionType.keyboard:
            if not self.key_combination:
                raise ValueError("key_combination required for keyboard action")

        if self.action_type == ActionType.execute_script:
            if not self.script_expression:
                raise ValueError("script_expression required for execute_script action")

        return self


# =========================
# BLOCKS & TESTCASE
# =========================

class CIRBlock(BaseModel):
    block_id: Optional[str] = None
    step_id: Optional[str] = None
    intent: str
    actions: List[CIRAction] = Field(default_factory=list)
    block_type: CIRBlockType = Field(default=CIRBlockType.step)
    meta: Optional[dict] = Field(default=None)

    @model_validator(mode="before")
    @classmethod
    def sync_block_and_step_id(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "step_id" in data and "block_id" not in data:
                data["block_id"] = data["step_id"]
            elif "block_id" in data and "step_id" not in data:
                data["step_id"] = data["block_id"]
        return data


class CIRTestCase(BaseModel):
    test_case_id: str
    description: str
    setup: List[CIRBlock] = Field(default_factory=list)
    steps: List[CIRBlock] = Field(default_factory=list)
    teardown: List[CIRBlock] = Field(default_factory=list)
