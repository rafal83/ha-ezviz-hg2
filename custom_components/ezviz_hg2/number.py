"""Numbers for writable EZVIZ HG2 and CH3 features."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import (
    EzvizHg2ConfigEntry,
    add_entities_by_gate_subentry,
    group_entities_by_gate_subentry,
)
from .entity import EzvizFeatureEntity, FeatureDefinition, matching_definitions

HG2 = frozenset({"HG2"})
CH3 = frozenset({"CH3"})


@dataclass(frozen=True, kw_only=True)
class NumberDefinition(FeatureDefinition):
    minimum: float
    maximum: float
    step: float = 1


NUMBERS = (
    NumberDefinition(key="warning_sound_volume", name="Volume de l'avertisseur", models=HG2, local_index="0", resource="global", domain="WarningLightMgr", feature="WarningLightCfg", value_path=("soundVolume",), icon="mdi:volume-high", minimum=0, maximum=100),
    NumberDefinition(key="warning_light_level", name="Luminosité de l'avertisseur", models=HG2, local_index="0", resource="global", domain="WarningLightMgr", feature="WarningLightCfg", value_path=("lightLevel",), icon="mdi:brightness-6", minimum=0, maximum=100),
    NumberDefinition(key="warning_ringtone", name="Sonnerie de l'avertisseur", models=HG2, local_index="0", resource="global", domain="WarningLightMgr", feature="WarningLightCfg", value_path=("ringtoneCfg",), icon="mdi:music-note", minimum=1, maximum=100),
    NumberDefinition(key="warning_flash_mode", name="Mode de clignotement", models=HG2, local_index="0", resource="global", domain="WarningLightMgr", feature="WarningLightCfg", value_path=("lightFlashMode",), icon="mdi:alarm-light-outline", minimum=0, maximum=100),
    NumberDefinition(key="chime_microphone_volume", name="Volume du microphone", models=CH3, local_index="1", resource="Video", domain="Microphone", feature="MicrophoneVolume", icon="mdi:microphone", minimum=0, maximum=100),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EzvizHg2ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up EZVIZ feature numbers."""
    coordinator = entry.runtime_data
    entities_by_serial: dict[str, list[EzvizFeatureNumber]] = {}
    for serial, definition in matching_definitions(coordinator, NUMBERS):
        entities_by_serial.setdefault(serial, []).append(
            EzvizFeatureNumber(coordinator, entry, serial, definition)
        )
    add_entities_by_gate_subentry(
        async_add_entities, group_entities_by_gate_subentry(coordinator, entities_by_serial)
    )


class EzvizFeatureNumber(EzvizFeatureEntity, NumberEntity):
    """Represent one numeric EZVIZ feature."""

    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator, entry, serial, definition: NumberDefinition) -> None:
        super().__init__(coordinator, entry, serial, definition)
        self._attr_native_min_value = definition.minimum
        self._attr_native_max_value = definition.maximum
        self._attr_native_step = definition.step

    @property
    def native_value(self) -> float:
        return float(self.feature_value)

    async def async_set_native_value(self, value: float) -> None:
        await self.async_set_feature_value(int(value) if value.is_integer() else value)
