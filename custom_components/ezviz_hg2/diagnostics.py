"""Diagnostics for EZVIZ HG2."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .coordinator import EzvizHg2Coordinator

TO_REDACT = {
    "deviceSerial",
    "serial",
    "sessionId",
    "rfSessionId",
    "streamToken",
    "token",
    "encryptPwd",
    "localIp",
    "netIp",
    "wanIp",
    "mac",
    "ssid",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return redacted data useful for implementing HG2 support."""
    coordinator: EzvizHg2Coordinator = entry.runtime_data
    inventory = []
    for serial, device in coordinator.all_devices.items():
        if not isinstance(device, dict):
            continue
        info = device.get("deviceInfos")
        if not isinstance(info, dict):
            info = {}
        inventory.append(
            {
                "serial": serial,
                "name": info.get("name"),
                "model": info.get("model"),
                "category": info.get("deviceCategory"),
                "subcategory": info.get("deviceSubCategory"),
            }
        )

    return async_redact_data(
        {
            "matched_hg2": coordinator.data,
            "inventory": inventory,
        },
        TO_REDACT,
    )
