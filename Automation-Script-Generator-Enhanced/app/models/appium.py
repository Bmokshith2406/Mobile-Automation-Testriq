from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator


class AppiumDeviceConfig(BaseModel):
    """
    Per-device Appium configuration accepted for backward-compatible payloads.

    Script Generator no longer bakes a device matrix into generated Appium
    scripts. Executor-Regenerator owns runtime device selection, but this model
    still accepts legacy matrix payloads and can be used as a capability source
    for a single generated script default.
    """

    label: Optional[str] = Field(
        default=None,
        description="Human-readable label used in generated artifacts.",
    )
    device_name: str = Field(
        ...,
        min_length=1,
        alias="deviceName",
        description="Appium deviceName capability.",
    )
    platform_name: Optional[str] = Field(
        default=None,
        alias="platformName",
        min_length=1,
    )
    automation_name: Optional[str] = Field(
        default=None,
        alias="automationName",
        min_length=1,
    )
    platform_version: Optional[str] = Field(
        default=None,
        alias="platformVersion",
    )
    udid: Optional[str] = None

    app_package: Optional[str] = Field(
        default=None,
        min_length=1,
        alias="appPackage",
        description="Android app package to launch.",
    )
    app_activity: Optional[str] = Field(
        default=None,
        min_length=1,
        alias="appActivity",
        description="Android app activity to launch.",
    )
    bundle_id: Optional[str] = Field(
        default=None,
        min_length=1,
        alias="bundleId",
        description="iOS bundleId to launch.",
    )
    app: Optional[str] = Field(
        default=None,
        min_length=1,
        description="Provider/local app reference for appium:app.",
    )
    app_wait_activity: Optional[str] = Field(
        default=None,
        alias="appWaitActivity",
    )

    no_reset: Optional[bool] = Field(default=None, alias="noReset")
    full_reset: Optional[bool] = Field(default=None, alias="fullReset")
    auto_grant_permissions: Optional[bool] = Field(
        default=None,
        alias="autoGrantPermissions",
    )
    relaunch_before_test: Optional[bool] = Field(
        default=None,
        alias="relaunchBeforeTest",
    )
    relaunch_before_step_retry: Optional[bool] = Field(
        default=None,
        alias="relaunchBeforeStepRetry",
    )
    extra_capabilities: dict[str, Any] = Field(
        default_factory=dict,
        alias="extraCapabilities",
        description="Additional Appium or provider-specific capabilities.",
    )

    model_config = {
        "populate_by_name": True,
        "str_strip_whitespace": True,
        "extra": "forbid",
    }


class AppiumConfig(BaseModel):
    """
    Appium launch/runtime configuration supplied by the caller.

    These values are intentionally request-owned because only the caller knows
    which device and app should be targeted in a local or cloud Appium grid.
    """

    device_name: Optional[str] = Field(
        default=None,
        min_length=1,
        alias="deviceName",
        description="Appium deviceName capability.",
    )
    app_package: Optional[str] = Field(
        default=None,
        min_length=1,
        alias="appPackage",
        description="Android app package to launch.",
    )
    app_activity: Optional[str] = Field(
        default=None,
        min_length=1,
        alias="appActivity",
        description="Android app activity to launch.",
    )
    bundle_id: Optional[str] = Field(
        default=None,
        min_length=1,
        alias="bundleId",
        description="iOS bundleId to launch.",
    )
    app: Optional[str] = Field(
        default=None,
        min_length=1,
        description="Provider/local app reference for appium:app.",
    )

    platform_name: str = Field(
        default="Android",
        alias="platformName",
        min_length=1,
    )
    automation_name: str = Field(
        default="UiAutomator2",
        alias="automationName",
        min_length=1,
    )
    platform_version: Optional[str] = Field(
        default=None,
        alias="platformVersion",
    )
    udid: Optional[str] = None
    app_wait_activity: Optional[str] = Field(
        default=None,
        alias="appWaitActivity",
    )

    no_reset: bool = Field(default=True, alias="noReset")
    full_reset: bool = Field(default=False, alias="fullReset")
    auto_grant_permissions: bool = Field(default=False, alias="autoGrantPermissions")

    relaunch_before_test: bool = Field(default=True, alias="relaunchBeforeTest")
    relaunch_before_step_retry: bool = Field(
        default=True,
        alias="relaunchBeforeStepRetry",
    )
    extra_capabilities: dict[str, Any] = Field(
        default_factory=dict,
        alias="extraCapabilities",
        description="Additional Appium or provider-specific capabilities.",
    )
    devices: list[AppiumDeviceConfig] = Field(
        default_factory=list,
        description=(
            "Optional legacy Appium device matrix. Executor-Regenerator owns "
            "runtime device selection; generated scripts remain device agnostic."
        ),
    )

    model_config = {
        "populate_by_name": True,
        "str_strip_whitespace": True,
        "extra": "forbid",
    }

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
            # Appium capabilities can be supplied at execution time by
            # Executor-Regenerator through APPIUM_CAPABILITIES_JSON, so an empty
            # config is valid for device-agnostic script generation.
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
                raise ValueError(
                    "iOS Appium devices require bundle_id, app, or appium:app"
                )
            return

        if not ((app_package and app_activity) or app):
            raise ValueError(
                "Android Appium devices require app_package/app_activity, app, or appium:app"
            )
