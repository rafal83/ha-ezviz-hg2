"""Cover platform for EZVIZ HG2 gate controllers."""

from __future__ import annotations

from collections.abc import Callable
import logging
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

from .api import should_fallback_to_ble
from .const import CONF_CLOSE_DURATION, CONF_OPEN_DURATION, DOMAIN
from .coordinator import EzvizHg2ConfigEntry, EzvizHg2Coordinator
from .device import (
    CommandRoute,
    decide_command_route,
    get_device_info,
    get_door_status,
    get_hg2_capabilities,
    is_cloud_offline,
    resolve_gate_route,
)
from .travel import MovementEstimator, inverse_eased_fraction

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EzvizHg2ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up covers for discovered HG2 devices.

    Each gate's travel duration lives in its own "gate" config subentry
    (see config_flow.py), so entities are grouped and added per subentry —
    a single ``async_add_entities`` call only accepts one subentry id.
    """
    coordinator = entry.runtime_data
    by_subentry: dict[str | None, list[EzvizHg2Cover]] = {}
    for serial, device in coordinator.data.items():
        if not isinstance(device, dict) or not get_hg2_capabilities(device).gate_control:
            continue
        settings = coordinator.gate_settings(serial)
        cover = EzvizHg2Cover(
            coordinator,
            serial,
            settings.get(CONF_OPEN_DURATION),
            settings.get(CONF_CLOSE_DURATION),
        )
        by_subentry.setdefault(coordinator.gate_subentry_id(serial), []).append(cover)
    for subentry_id, covers in by_subentry.items():
        async_add_entities(covers, config_subentry_id=subentry_id)


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
        self._movement = MovementEstimator()
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

    def _gate_status_fresh(self) -> bool:
        """Return whether the last DoorStatus poll for this HG2 succeeded.

        Missing freshness data (no poll attempted yet) is treated as fresh
        so a brand-new device is not immediately reported as stale.
        """
        freshness = self.coordinator.gate_status_freshness.get(self._serial)
        return freshness is None or freshness.available

    @property
    def available(self) -> bool:
        device = self.coordinator.data.get(self._serial)
        if not isinstance(device, dict):
            return False
        cloud_available = super().available and resolve_gate_route(device) is not None
        ble = self.coordinator.ble_controllers.get(self._serial)
        ble_available = ble is not None and ble.is_present()
        return cloud_available or ble_available

    @property
    def device_info(self) -> DeviceInfo:
        info = get_device_info(self.coordinator.data[self._serial])
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
        device = self.coordinator.data.get(self._serial)
        if not isinstance(device, dict) or not self._gate_status_fresh():
            return None
        status = get_door_status(device)
        if status == 0:
            return True
        if status == 1:
            return False
        return None

    @property
    def is_opening(self) -> bool:
        self._movement.position_at(monotonic())
        return self._movement.target == 100.0

    @property
    def is_closing(self) -> bool:
        self._movement.position_at(monotonic())
        return self._movement.target == 0.0

    @property
    def current_cover_position(self) -> int | None:
        """Return the approximate travel position, estimated from elapsed time.

        The EZVIZ cloud only reports closed vs. not-closed, so this is a
        rough estimate based on the configured full-travel durations. It is
        only reported once the travel durations are calibrated.
        """
        if not self._calibrated:
            return None
        position = self._movement.position_at(monotonic())
        return None if position is None else round(position)

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

    def _handle_coordinator_update(self) -> None:
        device = self.coordinator.data.get(self._serial)
        status = (
            get_door_status(device)
            if isinstance(device, dict) and self._gate_status_fresh()
            else None
        )
        if status == 0:
            self._movement.position = 0.0
            self._movement.clear()
        # status == 1 only means "not closed": EZVIZ never reports a real
        # percentage. Without an in-progress movement estimate there is no
        # way to know whether the gate is at 10% or 90%, so the position is
        # deliberately left unknown (None) rather than assumed to be 100%.
        super()._handle_coordinator_update()

    async def async_will_remove_from_hass(self) -> None:
        self._cancel_auto_stop()
        await super().async_will_remove_from_hass()

    async def _async_command(
        self, command: str, position: int | None = None
    ) -> None:
        device = self.coordinator.data[self._serial]
        ble = self.coordinator.ble_controllers.get(self._serial)
        ble_configured = ble is not None
        route = resolve_gate_route(device)
        command_route = decide_command_route(
            ble_configured=ble_configured,
            cloud_offline=is_cloud_offline(device),
            last_update_success=self.coordinator.last_update_success,
            has_route=route is not None,
        )
        if command_route == CommandRoute.BLE_CLOUD_OFFLINE:
            _LOGGER.info(
                "Cloud is unavailable for HG2 %s; sending %s through authenticated BLE",
                self._serial,
                command,
            )
            try:
                await ble.async_send(command)
            except Exception as err:
                raise HomeAssistantError(
                    f"EZVIZ HG2 BLE fallback failed: {err}"
                ) from err
            return
        if command_route == CommandRoute.BLE_NO_CLOUD_ROUTE:
            try:
                await ble.async_send(command)
            except Exception as err:
                raise HomeAssistantError(
                    f"EZVIZ HG2 BLE fallback failed: {err}"
                ) from err
            return
        if command_route == CommandRoute.NO_ROUTE:
            raise HomeAssistantError("EZVIZ HG2 resource route is unavailable")
        assert route is not None
        payload: dict[str, Any] = {"controlDoorCmd": command}
        if position is not None:
            payload["doorPercentage"] = position
        try:
            await self.hass.async_add_executor_job(
                self.coordinator.api.send_iot_action,
                self._serial,
                route.resource_id,
                route.local_index,
                route.action_domain,
                route.action_id,
                payload,
            )
        except Exception as err:
            if should_fallback_to_ble(err):
                if not ble_configured:
                    raise HomeAssistantError(
                        f"EZVIZ rejected the gate command: {err}"
                    ) from err
                _LOGGER.info(
                    "Cloud explicitly rejected %s for HG2 %s; using authenticated BLE",
                    command,
                    self._serial,
                )
                try:
                    await ble.async_send(command)
                except Exception as ble_err:
                    raise HomeAssistantError(
                        "EZVIZ cloud rejected the command and BLE fallback failed: "
                        f"{ble_err}"
                    ) from ble_err
                return
            raise HomeAssistantError(
                "EZVIZ cloud command failed after transmission; BLE was not retried "
                f"because the cloud outcome is ambiguous: {err}"
            ) from err
        await self.coordinator.async_request_refresh()

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the gate.

        The movement estimate only starts once the command is confirmed to
        have reached the cloud or BLE successfully, so a failed command
        never leaves the cover reporting a false "opening" state.
        """
        self._cancel_auto_stop()
        await self._async_command("open")
        self._movement.start(100.0, self._open_duration, now=monotonic())

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the gate."""
        self._cancel_auto_stop()
        await self._async_command("close")
        self._movement.start(0.0, self._close_duration, now=monotonic())

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Pause gate movement."""
        self._cancel_auto_stop()
        await self._async_command("pause")
        now = monotonic()
        self._movement.position = self._movement.position_at(now)
        self._movement.clear()

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Move toward a target position, timed via the same travel model."""
        if not self._calibrated:
            raise HomeAssistantError(
                "EZVIZ HG2 travel duration is not calibrated"
            )
        target_position = float(kwargs[ATTR_POSITION])
        current = self._movement.position_at(monotonic())
        if current is None:
            current = 0.0 if target_position >= 50 else 100.0
        if abs(target_position - current) < 1:
            return
        extreme = 100.0 if target_position > current else 0.0
        duration = self._open_duration if extreme == 100.0 else self._close_duration
        fraction = inverse_eased_fraction(
            (target_position - current) / (extreme - current)
        )
        self._cancel_auto_stop()
        await self._async_command("open" if extreme == 100.0 else "close")
        self._movement.start(extreme, duration, now=monotonic())
        self._schedule_auto_stop(fraction * duration)
