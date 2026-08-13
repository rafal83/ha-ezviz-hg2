"""Diagnostics for EZVIZ HG2."""

from __future__ import annotations

from typing import Any

from dataclasses import asdict

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .coordinator import EzvizHg2Coordinator
from .device import get_hg2_capabilities, is_hg2

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
                "capabilities": (
                    asdict(get_hg2_capabilities(device)) if is_hg2(device) else None
                ),
            }
        )

    gate_status_freshness = {
        serial: {"available": state.available, "updated_at": state.updated_at}
        for serial, state in coordinator.gate_status_freshness.items()
    }

    return async_redact_data(
        {
            "matched_hg2": coordinator.data,
            "inventory": inventory,
            "gate_status_freshness": gate_status_freshness,
        },
        TO_REDACT,
    )
