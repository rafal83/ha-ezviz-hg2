"""Firmware update entity for EZVIZ HG2/CH3 devices."""

from __future__ import annotations

from typing import Any

from pyezvizapi.exceptions import HTTPError, PyEzvizError

from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityDescription,
    UpdateEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import (
    EzvizHg2Coordinator,
    add_entities_by_gate_subentry,
    group_entities_by_gate_subentry,
)
from .device import (
    device_model,
    get_device_info as _device_info,
    get_latest_firmware_info,
    get_upgrade_percent,
    is_supported_device,
    is_upgrade_available,
    is_upgrade_in_progress,
)

UPDATE_ENTITY_DESCRIPTION = UpdateEntityDescription(
    key="firmware",
    device_class=UpdateDeviceClass.FIRMWARE,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up HG2/CH3 firmware update entities."""
    coordinator: EzvizHg2Coordinator = entry.runtime_data

    entities_by_serial: dict[str, list[UpdateEntity]] = {}
    for serial, device in coordinator.data.items():
        if not isinstance(device, dict) or not is_supported_device(device):
            continue
        entities_by_serial[serial] = [EzvizHg2UpdateEntity(coordinator, serial)]
    add_entities_by_gate_subentry(
        async_add_entities, group_entities_by_gate_subentry(coordinator, entities_by_serial)
    )


class EzvizHg2UpdateEntity(CoordinatorEntity[EzvizHg2Coordinator], UpdateEntity):
    """Report and trigger an EZVIZ cloud-managed firmware update."""

    _attr_has_entity_name = True
    _attr_supported_features = (
        UpdateEntityFeature.INSTALL
        | UpdateEntityFeature.PROGRESS
        | UpdateEntityFeature.RELEASE_NOTES
    )
    entity_description = UPDATE_ENTITY_DESCRIPTION

    def __init__(self, coordinator: EzvizHg2Coordinator, serial: str) -> None:
        super().__init__(coordinator)
        self._serial = serial
        self._attr_unique_id = f"{serial}_firmware_update"

    @property
    def available(self) -> bool:
        return super().available and self._serial in self.coordinator.data

    @property
    def device_info(self) -> DeviceInfo:
        device = self.coordinator.data[self._serial]
        info = _device_info(device)
        return DeviceInfo(
            identifiers={(DOMAIN, self._serial)},
            name=str(info.get("name") or f"EZVIZ {device_model(device)}"),
            manufacturer="EZVIZ",
            model=str(info.get("model") or info.get("deviceSubCategory") or "EZVIZ"),
            sw_version=info.get("version"),
            serial_number=self._serial,
        )

    @property
    def installed_version(self) -> str | None:
        version = _device_info(self.coordinator.data[self._serial]).get("version")
        return str(version) if version else None

    @property
    def latest_version(self) -> str | None:
        device = self.coordinator.data[self._serial]
        if is_upgrade_available(device):
            latest = get_latest_firmware_info(device).get("version")
            if latest:
                return str(latest)
        return self.installed_version

    @property
    def in_progress(self) -> bool:
        return is_upgrade_in_progress(self.coordinator.data[self._serial])

    @property
    def update_percentage(self) -> int | None:
        device = self.coordinator.data[self._serial]
        return get_upgrade_percent(device) if is_upgrade_in_progress(device) else None

    def release_notes(self) -> str | None:
        desc = get_latest_firmware_info(self.coordinator.data[self._serial]).get("desc")
        return str(desc) if desc else None

    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        try:
            await self.hass.async_add_executor_job(
                self.coordinator.api.upgrade_device, self._serial
            )
        except (HTTPError, PyEzvizError) as err:
            raise HomeAssistantError(
                f"EZVIZ rejected the firmware update: {err}"
            ) from err
        await self.coordinator.async_request_refresh()
