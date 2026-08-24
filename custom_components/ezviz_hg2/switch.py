"""Switches for writable EZVIZ HG2 and CH3 features."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import (
    EzvizHg2ConfigEntry,
    EzvizHg2Coordinator,
    add_entities_by_gate_subentry,
    group_entities_by_gate_subentry,
)
from .device import device_model, get_device_info as _device_info, get_switch_enabled
from .entity import EzvizFeatureEntity, FeatureDefinition, matching_definitions

HG2 = frozenset({"HG2"})
CH3 = frozenset({"CH3"})

SWITCHES = (
    FeatureDefinition(key="warning_sound", name="Son de l'avertisseur", models=HG2, local_index="0", resource="global", domain="WarningLightMgr", feature="WarningLightCfg", value_path=("soundEnabled",), icon="mdi:volume-high"),
    FeatureDefinition(key="warning_light", name="Feu d'avertissement", models=HG2, local_index="0", resource="global", domain="WarningLightMgr", feature="WarningLightCfg", value_path=("lightEnabled",), icon="mdi:alarm-light"),
    FeatureDefinition(key="open_button", name="Bouton d'ouverture", models=HG2, local_index="0", resource="global", domain="Door", feature="DoorParamCfg", value_path=("openButton",), icon="mdi:gesture-tap-button"),
    FeatureDefinition(key="security_light", name="Éclairage de sécurité", models=HG2, local_index="0", resource="global", domain="FillLight", feature="SecurityLightSwitch", icon="mdi:outdoor-lamp"),
    FeatureDefinition(key="local_light_link", name="Éclairage lié au portail", models=HG2, local_index="0", resource="global", domain="FillLight", feature="LocalLinkageCfg", value_path=("enabled",), icon="mdi:link-variant"),
    FeatureDefinition(key="app_notifications", name="Notifications de l'application", models=HG2, local_index="0", resource="global", domain="AppRemind", feature="AppMsgEnable", icon="mdi:bell"),
    FeatureDefinition(key="chime_mute", name="Mode silencieux", models=CH3, local_index="0", resource="global", domain="SoundSetting", feature="MuteEnabled", value_path=("enabled",), icon="mdi:volume-off"),
    FeatureDefinition(key="chime_mute_plan", name="Plan silencieux", models=CH3, local_index="0", resource="global", domain="SoundSetting", feature="MutePlan", value_path=("enabled",), icon="mdi:calendar-volume-off"),
    FeatureDefinition(key="chime_port_security", name="Protection des ports", models=CH3, local_index="0", resource="global", domain="NetworkSecurityProtection", feature="PortSecurity", value_path=("enabled",), icon="mdi:shield-lock"),
    FeatureDefinition(key="chime_night_light", name="Veilleuse", models=CH3, local_index="1", resource="Video", domain="LightCtrl", feature="NightLightEnable", icon="mdi:lightbulb-night"),
    FeatureDefinition(key="chime_loitering", name="Détection de présence prolongée", models=CH3, local_index="1", resource="Video", domain="Loitering", feature="LoiteringEnable", value_path=("enable",), icon="mdi:account-clock"),
    FeatureDefinition(key="chime_halow_test", name="Mode test HaLow", models=CH3, local_index="0", resource="global", domain="HubDeviceNetCtrl", feature="HubHalowTestSwitch", value_path=("enable",), icon="mdi:test-tube", enabled_default=False),
)


@dataclass(frozen=True, kw_only=True)
class SwitchTypeDefinition:
    """Describe one EZVIZ "camera-style" switch (see ``device.get_switch_enabled``)."""

    key: str
    name: str
    models: frozenset[str]
    switch_type: int
    icon: str | None = None
    enabled_default: bool = True


SWITCH_TYPES = (
    SwitchTypeDefinition(
        key="chime_indicator_light",
        name="Voyant lumineux",
        models=CH3,
        switch_type=611,  # DeviceSwitchType.CHIME_INDICATOR_LIGHT
        icon="mdi:led-on",
    ),
)


def _matching_switch_types(
    coordinator: EzvizHg2Coordinator, definitions: tuple[SwitchTypeDefinition, ...]
) -> list[tuple[str, SwitchTypeDefinition]]:
    """Return switch-type definitions whose type is present in each device's ``SWITCH`` list."""
    matches: list[tuple[str, SwitchTypeDefinition]] = []
    for serial, device in coordinator.data.items():
        if not isinstance(device, dict):
            continue
        model = device_model(device)
        for definition in definitions:
            if model in definition.models and get_switch_enabled(device, definition.switch_type) is not None:
                matches.append((serial, definition))
    return matches


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EzvizHg2ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up EZVIZ feature switches."""
    coordinator = entry.runtime_data
    entities_by_serial: dict[str, list[SwitchEntity]] = {}
    for serial, definition in matching_definitions(coordinator, SWITCHES):
        entities_by_serial.setdefault(serial, []).append(
            EzvizFeatureSwitch(coordinator, entry, serial, definition)
        )
    for serial, switch_definition in _matching_switch_types(coordinator, SWITCH_TYPES):
        entities_by_serial.setdefault(serial, []).append(
            EzvizSwitchTypeSwitch(coordinator, entry, serial, switch_definition)
        )
    add_entities_by_gate_subentry(
        async_add_entities, group_entities_by_gate_subentry(coordinator, entities_by_serial)
    )


class EzvizFeatureSwitch(EzvizFeatureEntity, SwitchEntity):
    """Represent one boolean EZVIZ feature."""

    @property
    def is_on(self) -> bool:
        return bool(self.feature_value)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.async_set_feature_value(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.async_set_feature_value(False)


class EzvizSwitchTypeSwitch(CoordinatorEntity[EzvizHg2Coordinator], SwitchEntity):
    """Represent one EZVIZ "camera-style" ``SWITCH`` list entry."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: EzvizHg2Coordinator,
        entry: ConfigEntry,
        serial: str,
        definition: SwitchTypeDefinition,
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
            and get_switch_enabled(device, self.definition.switch_type) is not None
        )

    @property
    def is_on(self) -> bool | None:
        device = self.coordinator.data.get(self._serial)
        if not isinstance(device, dict):
            return None
        return get_switch_enabled(device, self.definition.switch_type)

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

    async def _async_set_switch(self, enable: bool) -> None:
        try:
            await self.hass.async_add_executor_job(
                self.coordinator.api.set_switch,
                self._serial,
                self.definition.switch_type,
                enable,
            )
        except Exception as err:
            raise HomeAssistantError(f"EZVIZ rejected the switch: {err}") from err
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set_switch(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set_switch(False)
