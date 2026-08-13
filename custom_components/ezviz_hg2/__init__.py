"""EZVIZ HG2 custom integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL, CONF_TIMEOUT, CONF_URL
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
import homeassistant.helpers.config_validation as cv

from .api import EzvizHg2Api
from .ble import EzvizHg2BleController
from .const import (
    ATTR_ACTION_ID,
    ATTR_COMMAND,
    ATTR_CONFIG_ENTRY_ID,
    ATTR_DOMAIN_ID,
    ATTR_FILTER,
    ATTR_LOCAL_INDEX,
    ATTR_PAYLOAD,
    ATTR_RESOURCE_ID,
    ATTR_SERIAL,
    CONF_BLE_ADDRESS,
    CONF_BLE_FALLBACK_ENABLED,
    CONF_BLE_VERIFY_CODE,
    CONF_RFSESSION_ID,
    CONF_SESSION_ID,
    DEFAULT_BLE_TIMEOUT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TIMEOUT,
    DOMAIN,
    SERVICE_SEND_IOT_ACTION,
    SERVICE_GET_CLOUD_METADATA,
    SERVICE_GET_IOT_FEATURE,
    SERVICE_GET_MANUAL_SCENES,
    SERVICE_SEND_BLE_COMMAND,
    SUBENTRY_TYPE_GATE,
)
from .coordinator import EzvizHg2ConfigEntry, EzvizHg2Coordinator

PLATFORMS = ["button", "cover", "number", "select", "sensor", "switch"]

SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_SERIAL): cv.string,
        vol.Required(ATTR_RESOURCE_ID): cv.string,
        vol.Required(ATTR_LOCAL_INDEX, default="0"): cv.string,
        vol.Required(ATTR_DOMAIN_ID): cv.string,
        vol.Required(ATTR_ACTION_ID): cv.string,
        vol.Optional(ATTR_PAYLOAD, default={}): dict,
    }
)

FEATURE_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_SERIAL): cv.string,
        vol.Required(ATTR_RESOURCE_ID): cv.string,
        vol.Required(ATTR_LOCAL_INDEX, default="0"): cv.string,
        vol.Required(ATTR_DOMAIN_ID): cv.string,
        vol.Required(ATTR_ACTION_ID): cv.string,
    }
)

CLOUD_METADATA_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Optional(ATTR_FILTER): cv.string,
    }
)

MANUAL_SCENES_SERVICE_SCHEMA = vol.Schema(
    {vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string}
)

BLE_COMMAND_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
        # Kept as a hidden optional field for existing YAML automations.
        vol.Optional(ATTR_SERIAL): cv.string,
        vol.Required(ATTR_COMMAND): vol.In(("open", "close", "pause")),
    }
)


async def _async_update_listener(
    hass: HomeAssistant, entry: EzvizHg2ConfigEntry
) -> None:
    """Reload the config entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(
    hass: HomeAssistant, entry: EzvizHg2ConfigEntry
) -> bool:
    """Set up EZVIZ HG2 from a config entry."""
    token = {
        CONF_SESSION_ID: entry.data[CONF_SESSION_ID],
        CONF_RFSESSION_ID: entry.data[CONF_RFSESSION_ID],
        "api_url": entry.data[CONF_URL],
    }
    api = EzvizHg2Api(token, entry.data.get(CONF_TIMEOUT, DEFAULT_TIMEOUT))
    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    ble_controllers: dict[str, EzvizHg2BleController] = {}
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_TYPE_GATE or not subentry.unique_id:
            continue
        if not subentry.data.get(CONF_BLE_FALLBACK_ENABLED, False):
            continue
        ble_verify_code = str(subentry.data.get(CONF_BLE_VERIFY_CODE, "")).strip()
        if len(ble_verify_code) != 6:
            continue
        ble_controllers[subentry.unique_id] = EzvizHg2BleController(
            hass,
            subentry.unique_id,
            ble_verify_code,
            str(subentry.data.get(CONF_BLE_ADDRESS, "")).strip() or None,
            min(
                float(entry.data.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)),
                DEFAULT_BLE_TIMEOUT,
            ),
        )
    coordinator = EzvizHg2Coordinator(
        hass, entry, api, scan_interval, ble_controllers
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    if not hass.services.has_service(DOMAIN, SERVICE_SEND_IOT_ACTION):
        async def async_send_iot_action(call: ServiceCall) -> dict[str, Any]:
            config_entry = hass.config_entries.async_get_entry(
                call.data[ATTR_CONFIG_ENTRY_ID]
            )
            if config_entry is None or config_entry.domain != DOMAIN:
                raise HomeAssistantError("Unknown EZVIZ HG2 config entry")
            runtime = config_entry.runtime_data
            if not isinstance(runtime, EzvizHg2Coordinator):
                raise HomeAssistantError("EZVIZ HG2 config entry is not loaded")
            if call.data[ATTR_SERIAL] not in runtime.data:
                raise HomeAssistantError(
                    "The requested serial is not a discovered HG2 device"
                )

            try:
                return await hass.async_add_executor_job(
                    runtime.api.send_iot_action,
                    call.data[ATTR_SERIAL],
                    call.data[ATTR_RESOURCE_ID],
                    call.data[ATTR_LOCAL_INDEX],
                    call.data[ATTR_DOMAIN_ID],
                    call.data[ATTR_ACTION_ID],
                    call.data[ATTR_PAYLOAD],
                )
            except Exception as err:
                raise HomeAssistantError(
                    f"EZVIZ rejected the experimental action: {err}"
                ) from err

        hass.services.async_register(
            DOMAIN,
            SERVICE_SEND_IOT_ACTION,
            async_send_iot_action,
            schema=SERVICE_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_GET_IOT_FEATURE):
        async def async_get_iot_feature(call: ServiceCall) -> dict[str, Any]:
            config_entry = hass.config_entries.async_get_entry(
                call.data[ATTR_CONFIG_ENTRY_ID]
            )
            if config_entry is None or config_entry.domain != DOMAIN:
                raise HomeAssistantError("Unknown EZVIZ HG2 config entry")
            runtime = config_entry.runtime_data
            if not isinstance(runtime, EzvizHg2Coordinator):
                raise HomeAssistantError("EZVIZ HG2 config entry is not loaded")
            if call.data[ATTR_SERIAL] not in runtime.data:
                raise HomeAssistantError(
                    "The requested serial is not a discovered HG2 or CH3 device"
                )
            try:
                return await hass.async_add_executor_job(
                    runtime.api.get_iot_feature,
                    call.data[ATTR_SERIAL],
                    call.data[ATTR_RESOURCE_ID],
                    call.data[ATTR_LOCAL_INDEX],
                    call.data[ATTR_DOMAIN_ID],
                    call.data[ATTR_ACTION_ID],
                )
            except Exception as err:
                raise HomeAssistantError(
                    f"EZVIZ feature request failed: {err}"
                ) from err

        hass.services.async_register(
            DOMAIN,
            SERVICE_GET_IOT_FEATURE,
            async_get_iot_feature,
            schema=FEATURE_SERVICE_SCHEMA,
            supports_response=SupportsResponse.ONLY,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_GET_CLOUD_METADATA):
        async def async_get_cloud_metadata(call: ServiceCall) -> dict[str, Any]:
            config_entry = hass.config_entries.async_get_entry(
                call.data[ATTR_CONFIG_ENTRY_ID]
            )
            if config_entry is None or config_entry.domain != DOMAIN:
                raise HomeAssistantError("Unknown EZVIZ HG2 config entry")
            runtime = config_entry.runtime_data
            if not isinstance(runtime, EzvizHg2Coordinator):
                raise HomeAssistantError("EZVIZ HG2 config entry is not loaded")
            try:
                return await hass.async_add_executor_job(
                    runtime.api.get_cloud_metadata,
                    call.data.get(ATTR_FILTER),
                )
            except Exception as err:
                raise HomeAssistantError(
                    f"EZVIZ metadata request failed: {err}"
                ) from err

        hass.services.async_register(
            DOMAIN,
            SERVICE_GET_CLOUD_METADATA,
            async_get_cloud_metadata,
            schema=CLOUD_METADATA_SERVICE_SCHEMA,
            supports_response=SupportsResponse.ONLY,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_GET_MANUAL_SCENES):
        async def async_get_manual_scenes(call: ServiceCall) -> dict[str, Any]:
            config_entry = hass.config_entries.async_get_entry(
                call.data[ATTR_CONFIG_ENTRY_ID]
            )
            if config_entry is None or config_entry.domain != DOMAIN:
                raise HomeAssistantError("Unknown EZVIZ HG2 config entry")
            runtime = config_entry.runtime_data
            if not isinstance(runtime, EzvizHg2Coordinator):
                raise HomeAssistantError("EZVIZ HG2 config entry is not loaded")
            try:
                return await hass.async_add_executor_job(
                    runtime.api.get_manual_scenes
                )
            except Exception as err:
                raise HomeAssistantError(
                    f"EZVIZ manual scene request failed: {err}"
                ) from err

        hass.services.async_register(
            DOMAIN,
            SERVICE_GET_MANUAL_SCENES,
            async_get_manual_scenes,
            schema=MANUAL_SCENES_SERVICE_SCHEMA,
            supports_response=SupportsResponse.ONLY,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_SEND_BLE_COMMAND):
        async def async_send_ble_command(call: ServiceCall) -> None:
            config_entry = hass.config_entries.async_get_entry(
                call.data[ATTR_CONFIG_ENTRY_ID]
            )
            if config_entry is None or config_entry.domain != DOMAIN:
                raise HomeAssistantError("Unknown EZVIZ HG2 config entry")
            runtime = config_entry.runtime_data
            if not isinstance(runtime, EzvizHg2Coordinator):
                raise HomeAssistantError("EZVIZ HG2 config entry is not loaded")
            if not runtime.ble_controllers:
                raise HomeAssistantError(
                    "BLE fallback is not configured for any HG2 on this entry"
                )
            requested_serial = call.data.get(ATTR_SERIAL)
            if requested_serial is not None:
                controller = runtime.ble_controllers.get(requested_serial.upper())
                if controller is None:
                    raise HomeAssistantError(
                        "The supplied serial has no BLE fallback configured "
                        "for this entry"
                    )
            elif len(runtime.ble_controllers) == 1:
                controller = next(iter(runtime.ble_controllers.values()))
            else:
                raise HomeAssistantError(
                    "Several HG2 gates have BLE fallback configured on this "
                    "entry; specify which one with 'serial'"
                )
            try:
                command = call.data[ATTR_COMMAND]
                await controller.async_send(command)
            except Exception as err:
                raise HomeAssistantError(
                    f"EZVIZ HG2 BLE command failed: {err}"
                ) from err

        hass.services.async_register(
            DOMAIN,
            SERVICE_SEND_BLE_COMMAND,
            async_send_ble_command,
            schema=BLE_COMMAND_SERVICE_SCHEMA,
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an EZVIZ HG2 config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    remaining = [
        item
        for item in hass.config_entries.async_loaded_entries(DOMAIN)
        if item.entry_id != entry.entry_id
    ]
    if unloaded and not remaining:
        hass.services.async_remove(DOMAIN, SERVICE_SEND_IOT_ACTION)
        hass.services.async_remove(DOMAIN, SERVICE_GET_IOT_FEATURE)
        hass.services.async_remove(DOMAIN, SERVICE_GET_CLOUD_METADATA)
        hass.services.async_remove(DOMAIN, SERVICE_GET_MANUAL_SCENES)
        hass.services.async_remove(DOMAIN, SERVICE_SEND_BLE_COMMAND)
    return unloaded
