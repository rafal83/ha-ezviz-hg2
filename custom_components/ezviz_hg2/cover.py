"""Cover platform for EZVIZ HG2 gate controllers."""

from __future__ import annotations

from typing import Any

from homeassistant.components.cover import (
    CoverEntity,
    CoverDeviceClass,
    CoverEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EzvizHg2ConfigEntry, EzvizHg2Coordinator

ACTION_DOMAIN = "RemoteControlDoor"
ACTION_ID = "RemoteControlDoor"


def _device_info(device: dict[str, Any]) -> dict[str, Any]:
    info = device.get("deviceInfos")
    return info if isinstance(info, dict) else {}


def _is_hg2(device: dict[str, Any]) -> bool:
    info = _device_info(device)
    return "HG2" in " ".join(
        str(info.get(key, ""))
        for key in ("model", "deviceSubCategory", "productName", "deviceType")
    ).upper()


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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EzvizHg2ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up covers for discovered HG2 devices."""
    coordinator = entry.runtime_data
    async_add_entities(
        EzvizHg2Cover(coordinator, serial)
        for serial, device in coordinator.data.items()
        if isinstance(device, dict) and _is_hg2(device)
    )


class EzvizHg2Cover(CoordinatorEntity[EzvizHg2Coordinator], CoverEntity):
    """Represent an EZVIZ HG2 gate controller."""

    _attr_device_class = CoverDeviceClass.GATE
    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
    )

    def __init__(self, coordinator: EzvizHg2Coordinator, serial: str) -> None:
        super().__init__(coordinator)
        self._serial = serial
        self._attr_unique_id = f"{serial}_gate"

    @property
    def available(self) -> bool:
        device = self.coordinator.data.get(self._serial)
        return (
            super().available
            and isinstance(device, dict)
            and _route(device) is not None
        )

    @property
    def device_info(self) -> DeviceInfo:
        info = _device_info(self.coordinator.data[self._serial])
        return DeviceInfo(
            identifiers={(DOMAIN, self._serial)},
            name=str(info.get("name") or "EZVIZ HG2"),
            manufacturer="EZVIZ",
            model=str(info.get("model") or info.get("deviceSubCategory") or "HG2"),
            sw_version=info.get("version"),
            serial_number=self._serial,
        )

    @property
    def is_closed(self) -> bool | None:
        status = _door_status(self.coordinator.data[self._serial])
        if status == 0:
            return True
        if status == 1:
            return False
        return None

    async def _async_command(
        self, command: str, position: int | None = None
    ) -> None:
        device = self.coordinator.data[self._serial]
        route = _route(device)
        if route is None:
            raise HomeAssistantError("EZVIZ HG2 resource route is unavailable")
        payload: dict[str, Any] = {"controlDoorCmd": command}
        if position is not None:
            payload["doorPercentage"] = position
        try:
            await self.hass.async_add_executor_job(
                self.coordinator.api.send_iot_action,
                self._serial,
                "global",
                route[1],
                ACTION_DOMAIN,
                ACTION_ID,
                payload,
            )
        except Exception as err:
            raise HomeAssistantError(f"EZVIZ rejected the gate command: {err}") from err
        await self.coordinator.async_request_refresh()

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the gate."""
        await self._async_command("open")

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the gate."""
        await self._async_command("close")

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Pause gate movement."""
        await self._async_command("pause")
