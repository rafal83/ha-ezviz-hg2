"""Tests against the real EzvizHg2WifiSignalSensor (not a reimplementation).

Constructed directly (CoordinatorEntity/Entity do not require a running hass
at construction time) with a small FakeCoordinator double instead of the
Windows-broken pytest-homeassistant-custom-component harness — see
tests/conftest.py for why.
"""

from __future__ import annotations

from typing import Any

from custom_components.ezviz_hg2.sensor import EzvizHg2WifiSignalSensor, async_setup_entry


def _device(wifi: dict[str, Any] | None = None) -> dict[str, Any]:
    device: dict[str, Any] = {"deviceInfos": {"name": "Portail", "model": "HG2-400", "status": 1}}
    if wifi is not None:
        device["WIFI"] = wifi
    return device


class FakeCoordinator:
    def __init__(self, devices: dict[str, Any]) -> None:
        self.data = devices
        self.all_devices = devices
        self.last_update_success = True
        self.subentries: dict[str, Any] = {}

    def gate_subentry_id(self, serial: str) -> str | None:
        return None


class FakeEntry:
    def __init__(self, coordinator: FakeCoordinator, entry_id: str = "test_entry") -> None:
        self.runtime_data = coordinator
        self.entry_id = entry_id


def _strict_add_entities():
    calls: list[tuple[list[Any], dict[str, Any]]] = []

    def add_entities(entities, *args: Any, **kwargs: Any) -> None:
        calls.append((list(entities), kwargs))

    return add_entities, calls


async def test_setup_creates_wifi_sensor_when_signal_present():
    coordinator = FakeCoordinator({"SERIAL1": _device({"signal": 60})})
    entry = FakeEntry(coordinator)
    add_entities, calls = _strict_add_entities()

    await async_setup_entry(None, entry, add_entities)

    entities = [e for call in calls for e in call[0]]
    assert any(isinstance(e, EzvizHg2WifiSignalSensor) for e in entities)


async def test_setup_skips_wifi_sensor_without_signal():
    coordinator = FakeCoordinator({"SERIAL1": _device()})
    entry = FakeEntry(coordinator)
    add_entities, calls = _strict_add_entities()

    await async_setup_entry(None, entry, add_entities)

    entities = [e for call in calls for e in call[0]]
    assert not any(isinstance(e, EzvizHg2WifiSignalSensor) for e in entities)


def test_native_value_reads_signal():
    coordinator = FakeCoordinator({"SERIAL1": _device({"signal": 60})})
    sensor = EzvizHg2WifiSignalSensor(coordinator, "SERIAL1")
    assert sensor.native_value == 60


def test_available_false_without_wifi_data():
    coordinator = FakeCoordinator({"SERIAL1": _device()})
    sensor = EzvizHg2WifiSignalSensor(coordinator, "SERIAL1")
    assert sensor.available is False
