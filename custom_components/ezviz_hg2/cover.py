"""Cover platform for EZVIZ HG2 gate controllers."""

from __future__ import annotations

from collections.abc import Callable
from time import monotonic
from typing import Any

from homeassistant.components.cover import (
    ATTR_POSITION,
    CoverEntity,
    CoverDeviceClass,
    CoverEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_CLOSE_DURATION, CONF_OPEN_DURATION, DOMAIN
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


def _eased_fraction(fraction: float) -> float:
    """Smoothstep 0..1: slow at both ends, matching the gate motor's ramp."""
    fraction = min(1.0, max(0.0, fraction))
    return fraction * fraction * (3 - 2 * fraction)


def _inverse_eased_fraction(target_fraction: float) -> float:
    """Invert the smoothstep easing via Newton's method."""
    target_fraction = min(1.0, max(0.0, target_fraction))
    guess = target_fraction
    for _ in range(20):
        value = guess * guess * (3 - 2 * guess) - target_fraction
        slope = 6 * guess * (1 - guess)
        if abs(slope) < 1e-9:
            break
        guess = min(1.0, max(0.0, guess - value / slope))
    return guess


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EzvizHg2ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up covers for discovered HG2 devices."""
    coordinator = entry.runtime_data
    open_duration = entry.options.get(CONF_OPEN_DURATION)
    close_duration = entry.options.get(CONF_CLOSE_DURATION)
    async_add_entities(
        EzvizHg2Cover(coordinator, serial, open_duration, close_duration)
        for serial, device in coordinator.data.items()
        if isinstance(device, dict) and _is_hg2(device)
    )


class EzvizHg2Cover(CoordinatorEntity[EzvizHg2Coordinator], CoverEntity):
    """Represent an EZVIZ HG2 gate controller."""

    _attr_device_class = CoverDeviceClass.GATE
    _attr_has_entity_name = True
    _attr_name = None
    _attr_assumed_state = True

    def __init__(
        self,
        coordinator: EzvizHg2Coordinator,
        serial: str,
        open_duration: float | None,
        close_duration: float | None,
    ) -> None:
        super().__init__(coordinator)
        self._serial = serial
        self._attr_unique_id = f"{serial}_gate"
        self._open_duration = open_duration
        self._close_duration = close_duration
        self._position: float | None = None
        self._movement_start: float | None = None
        self._movement_start_position: float | None = None
        self._movement_target: float | None = None
        self._movement_duration: float | None = None
        self._auto_stop_unsub: Callable[[], None] | None = None

    @property
    def _calibrated(self) -> bool:
        return self._open_duration is not None and self._close_duration is not None

    @property
    def supported_features(self) -> CoverEntityFeature:
        features = (
            CoverEntityFeature.OPEN
            | CoverEntityFeature.CLOSE
            | CoverEntityFeature.STOP
        )
        if self._calibrated:
            features |= CoverEntityFeature.SET_POSITION
        return features

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

    @property
    def is_opening(self) -> bool:
        self._estimated_position()
        return self._movement_target == 100.0

    @property
    def is_closing(self) -> bool:
        self._estimated_position()
        return self._movement_target == 0.0

    @property
    def current_cover_position(self) -> int | None:
        """Return the approximate travel position, estimated from elapsed time.

        The EZVIZ cloud only reports closed vs. not-closed, so this is a
        rough estimate based on the configured full-travel durations. It is
        only reported once the travel durations are calibrated.
        """
        if not self._calibrated:
            return None
        position = self._estimated_position()
        return None if position is None else round(position)

    def _estimated_position(self) -> float | None:
        if self._movement_start is None or not self._movement_duration:
            return self._position
        elapsed = monotonic() - self._movement_start
        fraction = _eased_fraction(elapsed / self._movement_duration)
        if fraction >= 1.0:
            self._position = self._movement_target
            self._clear_movement()
            return self._position
        return self._movement_start_position + fraction * (
            self._movement_target - self._movement_start_position
        )

    def _clear_movement(self) -> None:
        self._movement_start = None
        self._movement_start_position = None
        self._movement_target = None
        self._movement_duration = None

    def _cancel_auto_stop(self) -> None:
        if self._auto_stop_unsub is not None:
            self._auto_stop_unsub()
            self._auto_stop_unsub = None

    def _schedule_auto_stop(self, delay: float) -> None:
        self._cancel_auto_stop()

        async def _auto_stop(_now: Any) -> None:
            self._auto_stop_unsub = None
            await self.async_stop_cover()

        self._auto_stop_unsub = async_call_later(self.hass, delay, _auto_stop)

    def _start_movement(self, target: float, duration: float | None) -> None:
        if duration is None:
            return
        current = self._estimated_position()
        if current is None:
            current = 0.0 if target == 100.0 else 100.0
        self._position = current
        self._movement_start = monotonic()
        self._movement_start_position = current
        self._movement_target = target
        self._movement_duration = duration

    def _handle_coordinator_update(self) -> None:
        device = self.coordinator.data.get(self._serial)
        status = _door_status(device) if isinstance(device, dict) else None
        if status == 0:
            self._position = 0.0
            self._clear_movement()
        elif (
            status == 1
            and self._calibrated
            and self._position is None
            and self._movement_start is None
        ):
            self._position = 100.0
        super()._handle_coordinator_update()

    async def async_will_remove_from_hass(self) -> None:
        self._cancel_auto_stop()
        await super().async_will_remove_from_hass()

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
        self._cancel_auto_stop()
        self._start_movement(100.0, self._open_duration)
        await self._async_command("open")

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the gate."""
        self._cancel_auto_stop()
        self._start_movement(0.0, self._close_duration)
        await self._async_command("close")

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Pause gate movement."""
        self._cancel_auto_stop()
        self._position = self._estimated_position()
        self._clear_movement()
        await self._async_command("pause")

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Move toward a target position, timed via the same travel model."""
        if not self._calibrated:
            raise HomeAssistantError(
                "EZVIZ HG2 travel duration is not calibrated"
            )
        target_position = float(kwargs[ATTR_POSITION])
        current = self._estimated_position()
        if current is None:
            current = 0.0 if target_position >= 50 else 100.0
        if abs(target_position - current) < 1:
            return
        extreme = 100.0 if target_position > current else 0.0
        duration = self._open_duration if extreme == 100.0 else self._close_duration
        fraction = _inverse_eased_fraction(
            (target_position - current) / (extreme - current)
        )
        self._cancel_auto_stop()
        self._start_movement(extreme, duration)
        await self._async_command("open" if extreme == 100.0 else "close")
        self._schedule_auto_stop(fraction * duration)
