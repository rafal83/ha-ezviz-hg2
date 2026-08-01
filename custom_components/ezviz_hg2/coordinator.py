"""Data coordinator for EZVIZ HG2 devices."""

from __future__ import annotations

from copy import deepcopy
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
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import EzvizHg2Api
from .const import DOMAIN, FULL_REFRESH_INTERVAL

_LOGGER = logging.getLogger(__name__)


def _device_info(device: dict[str, Any]) -> dict[str, Any]:
    value = device.get("deviceInfos")
    return value if isinstance(value, dict) else {}


def _searchable_device_text(device: dict[str, Any]) -> str:
    info = _device_info(device)
    fields = (
        info.get("name"),
        info.get("model"),
        info.get("deviceCategory"),
        info.get("deviceSubCategory"),
        info.get("productName"),
        info.get("deviceType"),
    )
    return " ".join(str(value) for value in fields if value).upper()


def is_supported_device(device: dict[str, Any]) -> bool:
    """Return whether a raw EZVIZ device is relevant to this integration."""
    text = _searchable_device_text(device)
    return "HG2" in text or "CH3" in text


def _is_hg2(device: dict[str, Any]) -> bool:
    return "HG2" in _searchable_device_text(device)


def _set_door_status(device: dict[str, Any], values: Any) -> None:
    """Update the cached HG2 door status with a direct feature response."""
    if not isinstance(values, list):
        return
    feature_info = device.setdefault("FEATURE_INFO", {})
    index = feature_info.setdefault("0", {})
    resource = index.setdefault("global", {})
    door = resource.setdefault("Door", {})
    status = door.setdefault("DoorStatus", {})
    status["doorStatus"] = values


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
    ) -> None:
        self.api = api
        self.all_devices: dict[str, Any] = {}
        self._last_full_refresh = 0.0
        super().__init__(
            hass,
            logger=_LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
            always_update=True,
        )

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
            if not isinstance(device, dict) or not _is_hg2(device):
                continue
            try:
                response = await self.hass.async_add_executor_job(
                    self.api.get_iot_feature,
                    serial,
                    "global",
                    "0",
                    "Door",
                    "DoorStatus",
                )
            except (HTTPError, InvalidURL, PyEzvizError) as err:
                _LOGGER.debug("Unable to refresh HG2 door status: %s", err)
                continue
            data = response.get("data")
            if isinstance(data, dict):
                _set_door_status(device, data.get("doorStatus"))
        self.all_devices = devices
        return {
            serial: device
            for serial, device in devices.items()
            if isinstance(device, dict) and is_supported_device(device)
        }
