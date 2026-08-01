"""Shared entities for EZVIZ HG2 and CH3 IoT features."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EzvizHg2Coordinator


@dataclass(frozen=True, kw_only=True)
class FeatureDefinition:
    """Describe one scalar value inside an EZVIZ IoT feature."""

    key: str
    name: str
    models: frozenset[str]
    local_index: str
    resource: str
    domain: str
    feature: str
    value_path: tuple[str, ...] = ()
    icon: str | None = None
    enabled_default: bool = True


def device_info(device: dict[str, Any]) -> dict[str, Any]:
    """Return the device information mapping."""
    info = device.get("deviceInfos")
    return info if isinstance(info, dict) else {}


def device_model(device: dict[str, Any]) -> str:
    """Return the normalized HG2 or CH3 model."""
    info = device_info(device)
    text = " ".join(
        str(info.get(key, ""))
        for key in ("model", "deviceSubCategory", "productName", "deviceType")
    ).upper()
    return "HG2" if "HG2" in text else "CH3" if "CH3" in text else ""


def feature_root(device: dict[str, Any], definition: FeatureDefinition) -> Any:
    """Return a raw feature value from FEATURE_INFO."""
    value: Any = device.get("FEATURE_INFO", {})
    for key in (
        definition.local_index,
        definition.resource,
        definition.domain,
        definition.feature,
    ):
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def feature_value(device: dict[str, Any], definition: FeatureDefinition) -> Any:
    """Return one scalar nested inside a feature."""
    value = feature_root(device, definition)
    for key in definition.value_path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def set_feature_root(
    device: dict[str, Any], definition: FeatureDefinition, value: Any
) -> None:
    """Replace a complete feature value in one cached device mapping."""
    target = device.setdefault("FEATURE_INFO", {})
    for key in (
        definition.local_index,
        definition.resource,
        definition.domain,
    ):
        target = target.setdefault(key, {})
    target[definition.feature] = value


class EzvizFeatureEntity(CoordinatorEntity[EzvizHg2Coordinator]):
    """Base class for a writable EZVIZ feature value."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: EzvizHg2Coordinator,
        entry: ConfigEntry,
        serial: str,
        definition: FeatureDefinition,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._serial = serial
        self.definition = definition
        self._attr_unique_id = f"{serial}_{definition.key}"
        self._attr_name = definition.name
        self._attr_icon = definition.icon
        self._attr_entity_registry_enabled_default = definition.enabled_default

    @property
    def available(self) -> bool:
        device = self.coordinator.data.get(self._serial)
        return (
            super().available
            and isinstance(device, dict)
            and feature_value(device, self.definition) is not None
        )

    @property
    def device_info(self) -> DeviceInfo:
        info = device_info(self.coordinator.data[self._serial])
        return DeviceInfo(
            identifiers={(DOMAIN, self._serial)},
            name=str(info.get("name") or f"EZVIZ {device_model(self.coordinator.data[self._serial])}"),
            manufacturer="EZVIZ",
            model=str(info.get("model") or info.get("deviceSubCategory") or "EZVIZ"),
            sw_version=info.get("version"),
            serial_number=self._serial,
        )

    @property
    def feature_value(self) -> Any:
        """Return this entity's current value."""
        return feature_value(self.coordinator.data[self._serial], self.definition)

    async def async_set_feature_value(self, value: Any) -> None:
        """Write the complete feature object while changing one scalar value."""
        device = self.coordinator.data[self._serial]
        root = deepcopy(feature_root(device, self.definition))
        if self.definition.value_path:
            if not isinstance(root, dict):
                raise HomeAssistantError("EZVIZ feature payload is unavailable")
            target = root
            for key in self.definition.value_path[:-1]:
                child = target.get(key)
                if not isinstance(child, dict):
                    raise HomeAssistantError("EZVIZ nested feature payload is unavailable")
                target = child
            target[self.definition.value_path[-1]] = value
        else:
            root = value
        try:
            await self.hass.async_add_executor_job(
                self.coordinator.api.set_iot_feature,
                self._serial,
                self.definition.resource,
                self.definition.local_index,
                self.definition.domain,
                self.definition.feature,
                root,
            )
        except Exception as err:
            raise HomeAssistantError(f"EZVIZ rejected the setting: {err}") from err
        all_devices = deepcopy(self.coordinator.all_devices)
        cached_device = all_devices.get(self._serial)
        if isinstance(cached_device, dict):
            set_feature_root(cached_device, self.definition, root)
            self.coordinator.all_devices = all_devices
        data = deepcopy(self.coordinator.data)
        current_device = data.get(self._serial)
        if isinstance(current_device, dict):
            set_feature_root(current_device, self.definition, root)
            self.coordinator.async_set_updated_data(data)


def matching_definitions(
    coordinator: EzvizHg2Coordinator,
    definitions: tuple[FeatureDefinition, ...],
) -> list[tuple[str, FeatureDefinition]]:
    """Return definitions that exist in each discovered device snapshot."""
    matches: list[tuple[str, FeatureDefinition]] = []
    for serial, device in coordinator.data.items():
        if not isinstance(device, dict):
            continue
        model = device_model(device)
        for definition in definitions:
            if model in definition.models and feature_value(device, definition) is not None:
                matches.append((serial, definition))
    return matches
