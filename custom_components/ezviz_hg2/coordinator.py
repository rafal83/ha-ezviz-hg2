"""Data coordinator for EZVIZ HG2 devices."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import timedelta
import logging
from time import monotonic
from typing import Any, override

from pyezvizapi.exceptions import (
    EzvizAuthTokenExpired,
    EzvizAuthVerificationCode,
    HTTPError,
    InvalidURL,
    PyEzvizError,
)

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import EzvizHg2Api
from .ble import EzvizHg2BleController
from .const import DOMAIN, FULL_REFRESH_INTERVAL, SUBENTRY_TYPE_GATE
from .device import is_hg2, is_supported_device, resolve_gate_route, set_door_status

_LOGGER = logging.getLogger(__name__)


def add_entities_by_gate_subentry(
    async_add_entities: AddConfigEntryEntitiesCallback,
    by_subentry: dict[str | None, list[Entity]],
) -> None:
    """Call ``async_add_entities`` once per gate subentry group.

    Passing ``config_subentry_id=None`` explicitly is *not* the same as
    omitting the argument: Home Assistant treats an explicit ``None`` as
    actively (re)assigning the device to "no subentry", and doing that
    repeatedly across platforms that otherwise never touch
    ``config_subentry_id`` (number/select/switch/sensor) makes it look like
    the device keeps moving between subentries, which HA warns about (and
    will refuse in 2027.8.0). So the argument is only passed at all when
    there is a real subentry to assign.
    """
    for subentry_id, entities in by_subentry.items():
        if not entities:
            continue
        if subentry_id is None:
            async_add_entities(entities)
        else:
            async_add_entities(entities, config_subentry_id=subentry_id)


@dataclass
class GateStatusFreshness:
    """Whether one HG2's cached ``DoorStatus`` reflects a recent, successful poll.

    ``available`` is ``False`` right after a poll failure even though a
    previously cached ``DoorStatus`` may still sit in device data; consumers
    must check this flag before trusting that cached value instead of
    assuming any present value is current.
    """

    available: bool
    updated_at: float | None


type EzvizHg2ConfigEntry = ConfigEntry["EzvizHg2Coordinator"]


class EzvizHg2Coordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll EZVIZ and retain both HG2 matches and safe inventory metadata."""

    config_entry: EzvizHg2ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: EzvizHg2ConfigEntry,
        api: EzvizHg2Api,
        scan_interval: int,
        ble_controllers: dict[str, EzvizHg2BleController] | None = None,
    ) -> None:
        self.api = api
        # Keyed by HG2 serial: each gate's BLE fallback is configured
        # independently through its own "gate" config subentry, so an
        # account with several HG2 devices does not share one BLE target.
        self.ble_controllers = ble_controllers or {}
        self.all_devices: dict[str, Any] = {}
        self.gate_status_freshness: dict[str, GateStatusFreshness] = {}
        self._last_full_refresh = 0.0
        super().__init__(
            hass,
            logger=_LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
            always_update=True,
        )

    def gate_subentry_id(self, serial: str) -> str | None:
        """Return the "gate" config subentry id configured for a serial, if any."""
        for subentry_id, subentry in self.config_entry.subentries.items():
            if subentry.subentry_type == SUBENTRY_TYPE_GATE and subentry.unique_id == serial:
                return subentry_id
        return None

    def gate_settings(self, serial: str) -> dict[str, Any]:
        """Return the "gate" config subentry data configured for a serial, if any."""
        for subentry in self.config_entry.subentries.values():
            if subentry.subentry_type == SUBENTRY_TYPE_GATE and subentry.unique_id == serial:
                return dict(subentry.data)
        return {}

    @override
    async def _async_update_data(self) -> dict[str, Any]:
        if (
            not self.all_devices
            or monotonic() - self._last_full_refresh >= FULL_REFRESH_INTERVAL
        ):
            try:
                devices = await self.hass.async_add_executor_job(self.api.refresh)
            except (EzvizAuthTokenExpired, EzvizAuthVerificationCode) as err:
                raise ConfigEntryAuthFailed from err
            except (HTTPError, InvalidURL, PyEzvizError) as err:
                raise UpdateFailed(f"EZVIZ cloud request failed: {err}") from err
            self.all_devices = devices
            self._last_full_refresh = monotonic()
        else:
            devices = deepcopy(self.all_devices)

        for serial, device in devices.items():
            if not isinstance(device, dict) or not is_hg2(device):
                continue
            route = resolve_gate_route(device)
            if route is None:
                continue
            try:
                response = await self.hass.async_add_executor_job(
                    self.api.get_iot_feature,
                    serial,
                    route.resource_id,
                    route.local_index,
                    route.status_domain,
                    route.status_feature,
                )
            except (HTTPError, InvalidURL, PyEzvizError) as err:
                # One HG2 failing to report its door status must not fail
                # the whole account's coordinator update; other devices
                # (and their own status) stay usable.
                _LOGGER.debug(
                    "Unable to refresh HG2 door status for %s: %s", serial, err
                )
                previous = self.gate_status_freshness.get(serial)
                self.gate_status_freshness[serial] = GateStatusFreshness(
                    available=False,
                    updated_at=previous.updated_at if previous else None,
                )
                continue
            data = response.get("data")
            if isinstance(data, dict):
                set_door_status(device, data.get("doorStatus"), route)
            self.gate_status_freshness[serial] = GateStatusFreshness(
                available=True, updated_at=monotonic()
            )
        self.all_devices = devices
        return {
            serial: device
            for serial, device in devices.items()
            if isinstance(device, dict) and is_supported_device(device)
        }
