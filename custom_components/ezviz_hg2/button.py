"""Action buttons for EZVIZ HG2 devices."""

from __future__ import annotations

import asyncio
from time import monotonic
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_CLOSE_DURATION,
    CONF_OPEN_DURATION,
    DOMAIN,
    MAX_TRAVEL_DURATION,
    MIN_TRAVEL_DURATION,
)
from .coordinator import EzvizHg2Coordinator
from .entity import EzvizFeatureEntity, FeatureDefinition, device_info, device_model

DOOR_ACTION_DOMAIN = "RemoteControlDoor"
DOOR_ACTION_ID = "RemoteControlDoor"
CALIBRATION_OPEN_SETTLE = 45
CALIBRATION_TIMEOUT = MAX_TRAVEL_DURATION + 30


def _route(device: dict[str, Any]) -> tuple[str, str] | None:
    resources = device.get("resourceInfos")
    if not isinstance(resources, list):
        return None
    for resource in resources:
        if not isinstance(resource, dict) or not resource.get("resourceId"):
            continue
        return str(resource["resourceId"]), str(resource.get("localIndex", "0"))
    return None


def _door_status(device: dict[str, Any]) -> int | None:
    feature_info = device.get("FEATURE_INFO")
    if not isinstance(feature_info, dict):
        return None
    index = feature_info.get("0", feature_info.get(0))
    if not isinstance(index, dict):
        return None
    global_resource = index.get("global")
    if not isinstance(global_resource, dict):
        return None
    door = global_resource.get("Door")
    if not isinstance(door, dict):
        return None
    status = door.get("DoorStatus")
    if not isinstance(status, dict):
        return None
    values = status.get("doorStatus")
    if not isinstance(values, list) or not values:
        return None
    value = values[0]
    return value if isinstance(value, int) else None


def _device_info(device: dict[str, Any]) -> dict[str, Any]:
    info = device.get("deviceInfos")
    return info if isinstance(info, dict) else {}


def _custom_open_mode(device: dict[str, Any]) -> int | None:
    features = device.get("FEATURE_INFO")
    if not isinstance(features, dict):
        return None
    index = features.get("0", features.get(0))
    if not isinstance(index, dict):
        return None
    global_resource = index.get("global")
    if not isinstance(global_resource, dict):
        return None
    controller = global_resource.get("ChannelControllerMgr")
    if not isinstance(controller, dict):
        return None
    config = controller.get("MotorParamCfg")
    if not isinstance(config, dict):
        return None
    mode = config.get("customMode")
    return mode if isinstance(mode, int) else None


CALIBRATION = FeatureDefinition(
    key="travel_calibration",
    name="Calibrer la course",
    models=frozenset({"HG2"}),
    local_index="0",
    resource="global",
    domain="ChannelControllerMgr",
    feature="MotorParamCfg",
    value_path=("travelCalibration",),
    icon="mdi:gate-arrow-right",
    enabled_default=False,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up potentially disruptive HG2 action buttons disabled by default."""
    coordinator: EzvizHg2Coordinator = entry.runtime_data
    hg2_serials = [
        serial
        for serial, device in coordinator.data.items()
        if isinstance(device, dict) and device_model(device) == "HG2"
    ]
    async_add_entities(
        EzvizTravelCalibrationButton(coordinator, entry, serial, CALIBRATION)
        for serial in hg2_serials
    )
    async_add_entities(
        EzvizTravelDurationCalibrationButton(coordinator, entry, serial)
        for serial in hg2_serials
    )
    async_add_entities(
        EzvizTravelDurationResetButton(coordinator, entry, serial)
        for serial in hg2_serials
    )
    async_add_entities(
        EzvizCustomOpenButton(coordinator, entry, serial)
        for serial in hg2_serials
    )


class EzvizTravelCalibrationButton(EzvizFeatureEntity, ButtonEntity):
    """Start the HG2 motor travel calibration."""

    _attr_entity_category = EntityCategory.CONFIG

    async def async_press(self) -> None:
        try:
            await self.hass.async_add_executor_job(
                self.coordinator.api.send_iot_action,
                self._serial,
                "global",
                "0",
                "ChannelControllerMgr",
                "TravelCalibrationCtrl",
                {},
            )
        except Exception as err:
            raise HomeAssistantError(f"EZVIZ rejected calibration: {err}") from err
        await self.coordinator.async_request_refresh()


class _EzvizGateButton(CoordinatorEntity[EzvizHg2Coordinator], ButtonEntity):
    """Shared device linkage for HG2 gate travel-calibration buttons."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False

    def __init__(
        self, coordinator: EzvizHg2Coordinator, entry: ConfigEntry, serial: str
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._serial = serial

    @property
    def device_info(self) -> DeviceInfo:
        info = device_info(self.coordinator.data[self._serial])
        return DeviceInfo(
            identifiers={(DOMAIN, self._serial)},
            name=str(info.get("name") or "EZVIZ HG2"),
            manufacturer="EZVIZ",
            model=str(info.get("model") or info.get("deviceSubCategory") or "HG2"),
            sw_version=info.get("version"),
            serial_number=self._serial,
        )


class EzvizTravelDurationCalibrationButton(_EzvizGateButton):
    """Time a full close cycle and use it for both cover travel directions.

    The EZVIZ cloud only ever confirms a fully closed gate, so this opens the
    gate, waits long enough for it to settle fully open, then times the close
    down to a confirmed closed status. Both open_duration and close_duration
    are set to that measurement, assuming a roughly symmetrical travel.
    """

    _attr_translation_key = "calibrate_travel_duration"
    _attr_icon = "mdi:timer-sync-outline"

    def __init__(
        self, coordinator: EzvizHg2Coordinator, entry: ConfigEntry, serial: str
    ) -> None:
        super().__init__(coordinator, entry, serial)
        self._attr_unique_id = f"{serial}_calibrate_travel_duration"

    async def _async_send_door_command(self, command: str) -> None:
        device = self.coordinator.data[self._serial]
        route = _route(device)
        if route is None:
            raise HomeAssistantError("EZVIZ HG2 resource route is unavailable")
        try:
            await self.hass.async_add_executor_job(
                self.coordinator.api.send_iot_action,
                self._serial,
                "global",
                route[1],
                DOOR_ACTION_DOMAIN,
                DOOR_ACTION_ID,
                {"controlDoorCmd": command},
            )
        except Exception as err:
            raise HomeAssistantError(f"EZVIZ rejected the gate command: {err}") from err

    async def async_press(self) -> None:
        await self._async_send_door_command("open")
        await asyncio.sleep(CALIBRATION_OPEN_SETTLE)

        start = monotonic()
        await self._async_send_door_command("close")

        closed = False
        while monotonic() - start < CALIBRATION_TIMEOUT:
            await asyncio.sleep(2)
            await self.coordinator.async_request_refresh()
            device = self.coordinator.data.get(self._serial)
            if isinstance(device, dict) and _door_status(device) == 0:
                closed = True
                break
        if not closed:
            raise HomeAssistantError(
                "EZVIZ HG2 calibration timed out waiting for the gate to close"
            )

        duration = min(
            MAX_TRAVEL_DURATION,
            max(MIN_TRAVEL_DURATION, round(monotonic() - start)),
        )
        self.hass.config_entries.async_update_entry(
            self._entry,
            options={
                **self._entry.options,
                CONF_OPEN_DURATION: duration,
                CONF_CLOSE_DURATION: duration,
            },
        )


class EzvizTravelDurationResetButton(_EzvizGateButton):
    """Clear the measured or manually entered travel durations.

    Without a calibration, the cover reports no position estimate at all.
    """

    _attr_translation_key = "reset_travel_duration"
    _attr_icon = "mdi:timer-remove-outline"

    def __init__(
        self, coordinator: EzvizHg2Coordinator, entry: ConfigEntry, serial: str
    ) -> None:
        super().__init__(coordinator, entry, serial)
        self._attr_unique_id = f"{serial}_reset_travel_duration"

    async def async_press(self) -> None:
        options = dict(self._entry.options)
        options.pop(CONF_OPEN_DURATION, None)
        options.pop(CONF_CLOSE_DURATION, None)
        self.hass.config_entries.async_update_entry(self._entry, options=options)


class EzvizCustomOpenButton(_EzvizGateButton):
    """Open the gate to its configured custom distance."""

    _attr_translation_key = "custom_open"
    _attr_icon = "mdi:gate-arrow-right"
    _attr_entity_category = None
    _attr_entity_registry_enabled_default = True

    def __init__(
        self, coordinator: EzvizHg2Coordinator, entry: ConfigEntry, serial: str
    ) -> None:
        super().__init__(coordinator, entry, serial)
        self._attr_unique_id = f"{serial}_custom_open"

    @property
    def available(self) -> bool:
        device = self.coordinator.data.get(self._serial)
        return (
            isinstance(device, dict)
            and super().available
            and _device_info(device).get("status") != 0
            and _route(device) is not None
        )

    async def async_press(self) -> None:
        device = self.coordinator.data[self._serial]
        mode = _custom_open_mode(device)
        if mode is None or mode <= 0:
            raise HomeAssistantError(
                "Configure a custom opening distance before using this button"
            )
        route = _route(device)
        if route is None:
            raise HomeAssistantError("EZVIZ HG2 resource route is unavailable")

        try:
            await self.hass.async_add_executor_job(
                self.coordinator.api.send_iot_action,
                self._serial,
                "global",
                route[1],
                DOOR_ACTION_DOMAIN,
                DOOR_ACTION_ID,
                {"controlDoorCmd": "custom"},
            )
        except Exception as err:
            raise HomeAssistantError(
                "EZVIZ cloud custom command failed after transmission; BLE was not "
                f"retried because the cloud outcome is ambiguous: {err}"
            ) from err
        await self.coordinator.async_request_refresh()
