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


class EzvizTravelDurationCalibrationButton(
    CoordinatorEntity[EzvizHg2Coordinator], ButtonEntity
):
    """Time a full close cycle and use it for both cover travel directions.

    The EZVIZ cloud only ever confirms a fully closed gate, so this opens the
    gate, waits long enough for it to settle fully open, then times the close
    down to a confirmed closed status. Both open_duration and close_duration
    are set to that measurement, assuming a roughly symmetrical travel.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "calibrate_travel_duration"
    _attr_icon = "mdi:timer-sync-outline"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False

    def __init__(
        self, coordinator: EzvizHg2Coordinator, entry: ConfigEntry, serial: str
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._serial = serial
        self._attr_unique_id = f"{serial}_calibrate_travel_duration"

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
