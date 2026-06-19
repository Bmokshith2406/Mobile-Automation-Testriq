from typing import Any, List, Optional, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_ID_PATTERN = r"^[A-Za-z0-9_\-]+$"


class MatchedScript(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    language: Literal["python", "javascript"]
    framework: Literal["selenium", "playwright", "cypress", "appium"]
    raw_code: str = Field(..., min_length=5)

    @field_validator("raw_code")
    @classmethod
    def raw_code_must_be_meaningful(cls, value):
        if value.strip().lower() in {"todo", "# todo", "// todo", "pass"}:
            raise ValueError("raw_code must contain meaningful reference code")
        return value


class AppiumDeviceConfig(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        populate_by_name=True,
    )

    label: Optional[str] = None
    device_name: str = Field(..., min_length=1, alias="deviceName")
    platform_name: Optional[str] = Field(default=None, min_length=1, alias="platformName")
    automation_name: Optional[str] = Field(default=None, min_length=1, alias="automationName")
    platform_version: Optional[str] = Field(default=None, alias="platformVersion")
    udid: Optional[str] = None
    app_package: Optional[str] = Field(default=None, min_length=1, alias="appPackage")
    app_activity: Optional[str] = Field(default=None, min_length=1, alias="appActivity")
    bundle_id: Optional[str] = Field(default=None, min_length=1, alias="bundleId")
    app: Optional[str] = Field(default=None, min_length=1)
    app_wait_activity: Optional[str] = Field(default=None, alias="appWaitActivity")
    no_reset: Optional[bool] = Field(default=None, alias="noReset")
    full_reset: Optional[bool] = Field(default=None, alias="fullReset")
    auto_grant_permissions: Optional[bool] = Field(default=None, alias="autoGrantPermissions")
    relaunch_before_test: Optional[bool] = Field(default=None, alias="relaunchBeforeTest")
    relaunch_before_step_retry: Optional[bool] = Field(
        default=None,
        alias="relaunchBeforeStepRetry",
    )
    extra_capabilities: dict[str, Any] = Field(
        default_factory=dict,
        alias="extraCapabilities",
    )


class AppiumConfig(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        populate_by_name=True,
    )

    device_name: Optional[str] = Field(default=None, min_length=1, alias="deviceName")
    app_package: Optional[str] = Field(default=None, min_length=1, alias="appPackage")
    app_activity: Optional[str] = Field(default=None, min_length=1, alias="appActivity")
    bundle_id: Optional[str] = Field(default=None, min_length=1, alias="bundleId")
    app: Optional[str] = Field(default=None, min_length=1)
    platform_name: str = Field(default="Android", min_length=1, alias="platformName")
    automation_name: str = Field(default="UiAutomator2", min_length=1, alias="automationName")
    platform_version: Optional[str] = Field(default=None, alias="platformVersion")
    udid: Optional[str] = None
    app_wait_activity: Optional[str] = Field(default=None, alias="appWaitActivity")
    no_reset: bool = Field(default=True, alias="noReset")
    full_reset: bool = Field(default=False, alias="fullReset")
    auto_grant_permissions: bool = Field(default=False, alias="autoGrantPermissions")
    relaunch_before_test: bool = Field(default=True, alias="relaunchBeforeTest")
    relaunch_before_step_retry: bool = Field(default=True, alias="relaunchBeforeStepRetry")
    extra_capabilities: dict[str, Any] = Field(
        default_factory=dict,
        alias="extraCapabilities",
    )
    devices: List[AppiumDeviceConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_reset_flags(self):
        if self.no_reset and self.full_reset:
            raise ValueError("no_reset and full_reset cannot both be true")

        for device in self.devices:
            no_reset = self.no_reset if device.no_reset is None else device.no_reset
            full_reset = self.full_reset if device.full_reset is None else device.full_reset
            if no_reset and full_reset:
                label = device.label or device.device_name
                raise ValueError(f"no_reset and full_reset cannot both be true for {label}")

        return self

    @model_validator(mode="after")
    def validate_launch_targets(self):
        if not self.devices:
            if not any(
                [
                    self.device_name,
                    self.app_package,
                    self.app_activity,
                    self.bundle_id,
                    self.app,
                    self.extra_capabilities,
                ]
            ):
                return self

            if not self.device_name:
                return self

            self._validate_single_launch_target(
                platform_name=self.platform_name,
                device_name=self.device_name,
                app_package=self.app_package,
                app_activity=self.app_activity,
                bundle_id=self.bundle_id,
                app=self._effective_app(self.extra_capabilities, self.app),
            )
            return self

        seen_labels: set[str] = set()
        for index, device in enumerate(self.devices, start=1):
            platform_name = device.platform_name or self.platform_name
            label = device.label or device.device_name or f"device_{index}"
            if label in seen_labels:
                raise ValueError(f"Duplicate Appium device label: {label}")
            seen_labels.add(label)

            self._validate_single_launch_target(
                platform_name=platform_name,
                device_name=device.device_name,
                app_package=device.app_package or self.app_package,
                app_activity=device.app_activity or self.app_activity,
                bundle_id=device.bundle_id or self.bundle_id,
                app=self._effective_app(
                    {**self.extra_capabilities, **device.extra_capabilities},
                    device.app or self.app,
                ),
            )

        return self

    @staticmethod
    def _effective_app(extra_capabilities: dict[str, Any], app: Optional[str]) -> Optional[str]:
        value = app or extra_capabilities.get("appium:app") or extra_capabilities.get("app")
        return str(value) if value else None

    @staticmethod
    def _validate_single_launch_target(
        *,
        platform_name: str,
        device_name: str,
        app_package: Optional[str],
        app_activity: Optional[str],
        bundle_id: Optional[str],
        app: Optional[str],
    ) -> None:
        platform = (platform_name or "").strip().lower()
        if not device_name:
            raise ValueError("device_name is required for every Appium device")

        if platform == "ios":
            if not (bundle_id or app):
                raise ValueError("iOS Appium devices require bundle_id, app, or appium:app")
            return

        if not ((app_package and app_activity) or app):
            raise ValueError(
                "Android Appium devices require app_package/app_activity, app, or appium:app"
            )


class Prerequisite(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    prerequisite_id: str = Field(..., min_length=1, pattern=_ID_PATTERN)
    description: str = Field(..., min_length=1)
    matched_script: Optional[MatchedScript] = None


class Step(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    step_id: str = Field(..., min_length=1, pattern=_ID_PATTERN)
    description: str = Field(..., min_length=1)
    expected_outcome: Optional[str] = None
    matched_script: Optional[MatchedScript] = None

    @model_validator(mode="after")
    def normalize_expected_outcome(self):
        if self.expected_outcome is not None and not self.expected_outcome.strip():
            self.expected_outcome = None
        return self


class TestCase(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    test_case_id: str = Field(..., min_length=1, pattern=_ID_PATTERN)
    description: str = Field(..., min_length=1)
    feature: Optional[str] = None
    target_framework: Optional[Literal["playwright", "selenium", "cypress", "appium"]] = None
    appium_config: Optional[AppiumConfig] = None
    appium_server_url: Optional[str] = None
    appium_device_filter: Optional[str] = None
    appium_device_matrix: Optional[Any] = None
    webhook_url: Optional[str] = None
    prerequisites: List[Prerequisite] = Field(default_factory=list)
    steps: List[Step] = Field(..., min_length=1)

    @field_validator("steps")
    @classmethod
    def steps_not_empty(cls, value):
        if not value:
            raise ValueError("Test case must contain at least one step")
        return value

    @model_validator(mode="after")
    def ids_must_be_unique(self):
        step_ids = [step.step_id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("Duplicate step_id values are not allowed")

        prerequisite_ids = [prerequisite.prerequisite_id for prerequisite in self.prerequisites]
        if len(prerequisite_ids) != len(set(prerequisite_ids)):
            raise ValueError("Duplicate prerequisite_id values are not allowed")

        return self

    @model_validator(mode="after")
    def validate_appium_config(self):
        framework = (self.target_framework or "").lower().strip()
        if framework and framework != "appium" and self.appium_config is not None:
            raise ValueError("appium_config is only valid for target_framework=appium")
        return self


class PipelineRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    test_case: TestCase

    @model_validator(mode="before")
    @classmethod
    def accept_wrapped_or_flat_shape(cls, value):
        if not isinstance(value, dict):
            return value

        if "test_case" not in value:
            return {"test_case": value}

        nested = value.get("test_case")
        if not isinstance(nested, dict):
            return value

        merged = dict(nested)
        for key, item in value.items():
            if key == "test_case" or item is None:
                continue
            merged[key] = item

        return {"test_case": merged}


class PipelineRunResponse(BaseModel):
    status: str
    routing_path: str
    matched_probability: Optional[float] = None
    canonical_testcase_id: str
    testcase_id: str
    report_id: str
    executor_status: str
    executor_run_id: str = ""
    executor_duration: str = ""
    executor_artifact_kind: str = "single_run"
    executor_matrix_run_count: Optional[int] = None
    executor_failed_step_index: Optional[int] = None
    testcase_rag_status: str
    methods_rag_status: str
    duration: float
