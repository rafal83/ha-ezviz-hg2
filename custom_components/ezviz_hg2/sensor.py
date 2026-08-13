"""Sensors for EZVIZ HG2 discovery."""

from __future__ import annotations

import json
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EzvizHg2Coordinator
from .device import get_device_info as _info


def _feature_paths(value: Any, prefix: str = "") -> list[str]:
    """Return bounded feature paths without copying large feature payloads."""
    paths: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(child, (dict, list)):
                paths.extend(_feature_paths(child, child_prefix))
            else:
                paths.append(child_prefix)
            if len(paths) >= 250:
                break
    elif isinstance(value, list):
        for index, child in enumerate(value[:20]):
            paths.extend(_feature_paths(child, f"{prefix}[{index}]"))
            if len(paths) >= 250:
                break
    return paths[:250]


def _mapping_keys(value: Any) -> list[str]:
    """Return sorted keys when the API value is a mapping."""
    return sorted(str(key) for key in value) if isinstance(value, dict) else []


def _feature_snapshot(device: dict[str, Any]) -> dict[str, Any]:
    """Return the compact feature branch relevant to HG2 or CH3 research."""
    feature_info = device.get("FEATURE_INFO")
    if not isinstance(feature_info, dict):
        return {}
    result: dict[str, Any] = {}
    for index, index_data in feature_info.items():
        if not isinstance(index_data, dict):
            continue
        selected: dict[str, Any] = {}
        for resource_name, resource_data in index_data.items():
            if not isinstance(resource_data, dict):
                continue
            branches = {
                key: value
                for key, value in resource_data.items()
                if key
                in {
                    "Door",
                    "ChannelControllerMgr",
                    "WarningLightMgr",
                    "Chime",
                    "ChimeMgr",
                    "DoorBell",
                    "CallSignalMgr",
                    "IndicatorLight",
                    "VolumeMgr",
                }
            }
            if branches:
                selected[str(resource_name)] = branches
        if selected:
            result[str(index)] = selected
    return result


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up HG2 discovery sensors."""
    coordinator: EzvizHg2Coordinator = entry.runtime_data
    entities: list[SensorEntity] = [EzvizHg2DiscoverySensor(coordinator, entry)]
    entities.extend(
        EzvizHg2DeviceSensor(coordinator, serial)
        for serial in coordinator.data
    )
    entities.extend(
        EzvizHg2RawDataSensor(coordinator, serial)
        for serial in coordinator.data
    )
    async_add_entities(entities)


class EzvizHg2DiscoverySensor(CoordinatorEntity[EzvizHg2Coordinator], SensorEntity):
    """Report how many devices matched the HG2 signature."""

    entity_description = SensorEntityDescription(
        key="discovered_devices",
        translation_key="discovered_devices",
        icon="mdi:gate",
        entity_category=EntityCategory.DIAGNOSTIC,
    )

    def __init__(self, coordinator: EzvizHg2Coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_discovered_devices"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="EZVIZ HG2 Cloud",
            manufacturer="EZVIZ",
            model="Cloud account",
        )

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        categories: set[str] = set()
        models: set[str] = set()
        for device in self.coordinator.all_devices.values():
            if not isinstance(device, dict):
                continue
            info = _info(device)
            if value := info.get("deviceCategory"):
                categories.add(str(value))
            if value := info.get("model") or info.get("deviceSubCategory"):
                models.add(str(value))
        return {
            "account_device_count": len(self.coordinator.all_devices),
            "categories": sorted(categories),
            "models": sorted(models),
        }


class EzvizHg2DeviceSensor(CoordinatorEntity[EzvizHg2Coordinator], SensorEntity):
    """Expose initial raw status metadata for one HG2."""

    _attr_has_entity_name = True
    _attr_name = "État API"
    _attr_icon = "mdi:gate"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: EzvizHg2Coordinator, serial: str) -> None:
        super().__init__(coordinator)
        self._serial = serial
        self._attr_unique_id = f"{serial}_api_status"

    @property
    def available(self) -> bool:
        return super().available and self._serial in self.coordinator.data

    @property
    def native_value(self) -> str:
        info = _info(self.coordinator.data[self._serial])
        status = info.get("status")
        return "online" if status == 1 else "offline" if status == 0 else str(status)

    @property
    def device_info(self) -> DeviceInfo:
        info = _info(self.coordinator.data[self._serial])
        return DeviceInfo(
            identifiers={(DOMAIN, self._serial)},
            name=str(info.get("name") or "EZVIZ HG2"),
            manufacturer="EZVIZ",
            model=str(
                info.get("model")
                or info.get("deviceSubCategory")
                or "HG2"
            ),
            sw_version=info.get("version"),
            serial_number=self._serial,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        device = self.coordinator.data[self._serial]
        info = _info(device)
        resource_infos = device.get("resourceInfos")
        routes = []
        if isinstance(resource_infos, list):
            for resource in resource_infos:
                if not isinstance(resource, dict):
                    continue
                routes.append(
                    {
                        "resource_id": resource.get("resourceId"),
                        "local_index": resource.get("localIndex"),
                        "type": resource.get("type"),
                    }
                )
        return {
            "device_category": info.get("deviceCategory"),
            "device_sub_category": info.get("deviceSubCategory"),
            "model": info.get("model"),
            "resource_routes": routes,
            "serial": self._serial,
            "feature_snapshot": _feature_snapshot(device),
            "feature_paths": _feature_paths(device.get("FEATURE_INFO", {})),
            "feature_keys": _mapping_keys(device.get("FEATURE")),
            "status_keys": _mapping_keys(device.get("STATUS")),
            "switch_count": len(device.get("SWITCH") or []),
        }


class EzvizHg2RawDataSensor(CoordinatorEntity[EzvizHg2Coordinator], SensorEntity):
    """Expose the complete raw API payload for one device, for debugging.

    Disabled by default: the payload can be large and is only meant to be
    enabled temporarily to inspect it in Developer Tools > States.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "raw_data"
    _attr_icon = "mdi:code-json"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_device_class = SensorDeviceClass.DATA_SIZE
    _attr_native_unit_of_measurement = UnitOfInformation.BYTES

    def __init__(self, coordinator: EzvizHg2Coordinator, serial: str) -> None:
        super().__init__(coordinator)
        self._serial = serial
        self._attr_unique_id = f"{serial}_raw_data"

    @property
    def available(self) -> bool:
        return super().available and self._serial in self.coordinator.data

    @property
    def native_value(self) -> int:
        return len(json.dumps(self.coordinator.data[self._serial], default=str))

    @property
    def device_info(self) -> DeviceInfo:
        info = _info(self.coordinator.data[self._serial])
        return DeviceInfo(
            identifiers={(DOMAIN, self._serial)},
            name=str(info.get("name") or "EZVIZ HG2"),
            manufacturer="EZVIZ",
            model=str(
                info.get("model")
                or info.get("deviceSubCategory")
                or "HG2"
            ),
            sw_version=info.get("version"),
            serial_number=self._serial,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"raw": self.coordinator.data[self._serial]}
