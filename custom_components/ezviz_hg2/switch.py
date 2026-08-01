"""Switches for writable EZVIZ HG2 and CH3 features."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import EzvizHg2ConfigEntry
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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EzvizHg2ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up EZVIZ feature switches."""
    coordinator = entry.runtime_data
    async_add_entities(
        EzvizFeatureSwitch(coordinator, entry, serial, definition)
        for serial, definition in matching_definitions(coordinator, SWITCHES)
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
