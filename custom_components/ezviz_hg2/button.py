"""Action buttons for EZVIZ HG2 devices."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import EzvizHg2Coordinator
from .entity import EzvizFeatureEntity, FeatureDefinition, device_model

CALIBRATION = FeatureDefinition(
    key="travel_calibration",
    name="Calibrer la course",
    models=frozenset({"HG2"}),
    local_index="0",
    resource="global",
    domain="ChannelControllerMgr",
    feature="MotorParamCfg",
    value_path=("travelCalibration",),
    icon="mdi:gate-arrow-right",
    enabled_default=False,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up potentially disruptive HG2 action buttons disabled by default."""
    coordinator: EzvizHg2Coordinator = entry.runtime_data
    async_add_entities(
        EzvizTravelCalibrationButton(coordinator, entry, serial, CALIBRATION)
        for serial, device in coordinator.data.items()
        if isinstance(device, dict) and device_model(device) == "HG2"
    )


class EzvizTravelCalibrationButton(EzvizFeatureEntity, ButtonEntity):
    """Start the HG2 motor travel calibration."""

    _attr_entity_category = EntityCategory.CONFIG

    async def async_press(self) -> None:
        try:
            await self.hass.async_add_executor_job(
                self.coordinator.api.send_iot_action,
                self._serial,
                "global",
                "0",
                "ChannelControllerMgr",
                "TravelCalibrationCtrl",
                {},
            )
        except Exception as err:
            raise HomeAssistantError(f"EZVIZ rejected calibration: {err}") from err
        await self.coordinator.async_request_refresh()
