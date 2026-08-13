"""Select entities for writable EZVIZ HG2 features."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import (
    EzvizHg2ConfigEntry,
    add_entities_by_gate_subentry,
    group_entities_by_gate_subentry,
)
from .entity import EzvizFeatureEntity, FeatureDefinition, matching_definitions

HG2 = frozenset({"HG2"})


@dataclass(frozen=True, kw_only=True)
class SelectDefinition(FeatureDefinition):
    choices: tuple[tuple[str, Any], ...]


SELECTS = (
    SelectDefinition(key="motor_speed", name="Vitesse du moteur", models=HG2, local_index="0", resource="global", domain="ChannelControllerMgr", feature="MotorParamCfg", value_path=("motorSpeed",), icon="mdi:speedometer", choices=(("Lente", "low"), ("Moyenne", "middle"), ("Rapide", "high"))),
    SelectDefinition(key="bounce_sensitivity", name="Sensibilité anti-rebond", models=HG2, local_index="0", resource="global", domain="ChannelControllerMgr", feature="MotorParamCfg", value_path=("bounceSensitivity",), icon="mdi:shield-alert", choices=(("Faible", "low"), ("Moyenne-faible", "mid-low"), ("Moyenne", "middle"), ("Élevée", "high"), ("Très élevée", "high-plus"))),
    SelectDefinition(key="door_direction", name="Direction du portail", models=HG2, local_index="0", resource="global", domain="ChannelControllerMgr", feature="MotorParamCfg", value_path=("doorDirection",), icon="mdi:swap-horizontal", choices=(("Gauche", "left"), ("Droite", "right"))),
    SelectDefinition(key="custom_open_mode", name="Ouverture personnalisée", models=HG2, local_index="0", resource="global", domain="ChannelControllerMgr", feature="MotorParamCfg", value_path=("customMode",), icon="mdi:gate-arrow-right", choices=(("Non configurée", 0), ("Un quart", 1), ("Moitié", 2), ("Trois quarts", 3), ("Complète", 4), ("Demi-ouverture", 5))),
    SelectDefinition(key="stop_interface", name="Type d'entrée STOP", models=HG2, local_index="0", resource="global", domain="ChannelControllerMgr", feature="MotorExternalInterfaceType", value_path=("stopInterfaceType",), icon="mdi:stop-circle-outline", choices=(("Normalement fermée", 0), ("Normalement ouverte", 1))),
    SelectDefinition(key="auto_close_delay", name="Fermeture automatique", models=HG2, local_index="0", resource="global", domain="Door", feature="DoorParamCfg", value_path=("autoCloseDoor",), icon="mdi:timer-lock", choices=(("Désactivée", 0), ("5 secondes", 5), ("30 secondes", 30), ("1 minute", 60), ("3 minutes", 180), ("5 minutes", 300), ("10 minutes", 600))),
    SelectDefinition(key="warning_light_type", name="Type d'avertisseur", models=HG2, local_index="0", resource="global", domain="WarningLightMgr", feature="WarningLightCfg", value_path=("lightType",), icon="mdi:alarm-light", choices=(("Version complète", "highSpec"), ("Version simple", "lowSpec"))),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EzvizHg2ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up EZVIZ feature selects."""
    coordinator = entry.runtime_data
    entities_by_serial: dict[str, list[EzvizFeatureSelect]] = {}
    for serial, definition in matching_definitions(coordinator, SELECTS):
        entities_by_serial.setdefault(serial, []).append(
            EzvizFeatureSelect(coordinator, entry, serial, definition)
        )
    add_entities_by_gate_subentry(
        async_add_entities, group_entities_by_gate_subentry(coordinator, entities_by_serial)
    )


class EzvizFeatureSelect(EzvizFeatureEntity, SelectEntity):
    """Represent one enumerated EZVIZ feature."""

    def __init__(self, coordinator, entry, serial, definition: SelectDefinition) -> None:
        super().__init__(coordinator, entry, serial, definition)
        self._choices = dict(definition.choices)
        self._attr_options = list(self._choices)

    @property
    def current_option(self) -> str | None:
        value = self.feature_value
        return next((label for label, raw in self._choices.items() if raw == value), None)

    async def async_select_option(self, option: str) -> None:
        await self.async_set_feature_value(self._choices[option])
