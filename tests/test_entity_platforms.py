"""End-to-end check that number.py wires entities through the shared
gate-subentry grouping helpers correctly (see coordinator.py).

The helpers themselves (add_entities_by_gate_subentry,
group_entities_by_gate_subentry) are unit tested in test_coordinator.py;
this confirms one real platform actually uses them as intended — the bug
fixed here was every platform *except* number/select/switch/sensor
explicitly declaring config_subentry_id=None for a device those platforms
never mentioned it for at all, which Home Assistant logs as the device
being silently reassigned between subentries.
"""

from __future__ import annotations

from typing import Any

import custom_components.ezviz_hg2.number as number_platform


def _hg2_device() -> dict[str, Any]:
    return {
        "deviceInfos": {"name": "Portail", "model": "HG2-400", "status": 1},
        "resourceInfos": [{"resourceId": "abc", "localIndex": "0"}],
        "FEATURE_INFO": {
            "0": {
                "global": {
                    "WarningLightMgr": {"WarningLightCfg": {"soundVolume": 42}},
                }
            }
        },
    }


class FakeSubentry:
    def __init__(self, subentry_type: str, unique_id: str, data: dict[str, Any]) -> None:
        self.subentry_type = subentry_type
        self.unique_id = unique_id
        self.data = data


class FakeCoordinator:
    def __init__(self, devices: dict[str, Any]) -> None:
        self.data = devices
        self.subentries: dict[str, FakeSubentry] = {}

    def gate_subentry_id(self, serial: str) -> str | None:
        for subentry_id, subentry in self.subentries.items():
            if subentry.subentry_type == "gate" and subentry.unique_id == serial:
                return subentry_id
        return None


class FakeEntry:
    def __init__(self, coordinator: FakeCoordinator) -> None:
        self.runtime_data = coordinator


def _strict_add_entities():
    calls: list[tuple[list[Any], dict[str, Any]]] = []

    def add_entities(entities, *args: Any, **kwargs: Any) -> None:
        calls.append((list(entities), kwargs))

    return add_entities, calls


async def test_number_platform_omits_kwarg_without_a_gate_subentry():
    coordinator = FakeCoordinator({"SERIAL1": _hg2_device()})
    entry = FakeEntry(coordinator)
    add_entities, calls = _strict_add_entities()

    await number_platform.async_setup_entry(None, entry, add_entities)

    assert len(calls) == 1
    entities, kwargs = calls[0]
    assert len(entities) == 1  # only warning_sound_volume matches this device
    assert "config_subentry_id" not in kwargs


async def test_number_platform_passes_kwarg_with_a_gate_subentry():
    coordinator = FakeCoordinator({"SERIAL1": _hg2_device()})
    coordinator.subentries["sub1"] = FakeSubentry("gate", "SERIAL1", {})
    entry = FakeEntry(coordinator)
    add_entities, calls = _strict_add_entities()

    await number_platform.async_setup_entry(None, entry, add_entities)

    assert calls[0][1] == {"config_subentry_id": "sub1"}
