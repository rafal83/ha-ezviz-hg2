"""Tests against the real EzvizHg2Coordinator (not a reimplementation).

Constructed with the lightweight FakeHass/FakeConfigEntry doubles from
conftest.py instead of the (Windows-broken, see conftest.py) official
pytest-homeassistant-custom-component ``hass`` fixture. DataUpdateCoordinator
itself only stores ``hass`` and does light bookkeeping at construction time,
so this exercises the actual shipped polling logic in coordinator.py.
"""

from __future__ import annotations

from typing import Any

import pytest
from pyezvizapi.exceptions import HTTPError

from custom_components.ezviz_hg2.coordinator import EzvizHg2Coordinator


class FakeConfigEntry:
    entry_id = "test_entry"

    def __init__(self) -> None:
        self.subentries: dict[str, Any] = {}

    def async_on_unload(self, func) -> None:
        pass


class FakeApi:
    """Stand-in for EzvizHg2Api with scriptable per-serial door status."""

    def __init__(self, devices: dict[str, Any]) -> None:
        self._devices = devices
        # serial -> exception instance, or None to succeed
        self.door_status_failures: dict[str, Exception] = {}
        self.door_status_calls: list[str] = []

    def refresh(self) -> dict[str, Any]:
        return self._devices

    def get_iot_feature(
        self, serial: str, resource_id: str, local_index: str, domain_id: str, feature_id: str
    ) -> dict[str, Any]:
        self.door_status_calls.append(serial)
        if err := self.door_status_failures.get(serial):
            raise err
        return {"data": {"doorStatus": [0]}}


def _hg2_device(name: str = "Portail") -> dict[str, Any]:
    return {
        "deviceInfos": {"name": name, "model": "HG2-400", "status": 1},
        "resourceInfos": [{"resourceId": "abc", "localIndex": "0"}],
    }


@pytest.fixture
def fake_entry() -> FakeConfigEntry:
    return FakeConfigEntry()


async def make_coordinator(fake_hass, fake_entry, api: FakeApi) -> EzvizHg2Coordinator:
    return EzvizHg2Coordinator(fake_hass, fake_entry, api=api, scan_interval=15)


async def test_successful_poll_marks_gate_status_fresh(fake_hass, fake_entry):
    api = FakeApi({"SERIAL1": _hg2_device()})
    coordinator = await make_coordinator(fake_hass, fake_entry, api)

    data = await coordinator._async_update_data()

    assert "SERIAL1" in data
    freshness = coordinator.gate_status_freshness["SERIAL1"]
    assert freshness.available is True
    assert freshness.updated_at is not None


async def test_failed_poll_marks_gate_status_stale(fake_hass, fake_entry):
    api = FakeApi({"SERIAL1": _hg2_device()})
    api.door_status_failures["SERIAL1"] = HTTPError("timeout")
    coordinator = await make_coordinator(fake_hass, fake_entry, api)

    data = await coordinator._async_update_data()

    # The device inventory is still returned (a stale DoorStatus does not
    # remove the device), but its freshness is explicitly marked unavailable.
    assert "SERIAL1" in data
    freshness = coordinator.gate_status_freshness["SERIAL1"]
    assert freshness.available is False


async def test_one_device_failing_does_not_affect_another(fake_hass, fake_entry):
    api = FakeApi({"SERIAL1": _hg2_device("Portail 1"), "SERIAL2": _hg2_device("Portail 2")})
    api.door_status_failures["SERIAL1"] = HTTPError("timeout")
    coordinator = await make_coordinator(fake_hass, fake_entry, api)

    data = await coordinator._async_update_data()

    assert "SERIAL1" in data and "SERIAL2" in data
    assert coordinator.gate_status_freshness["SERIAL1"].available is False
    assert coordinator.gate_status_freshness["SERIAL2"].available is True


async def test_stale_poll_preserves_previous_updated_at(fake_hass, fake_entry):
    api = FakeApi({"SERIAL1": _hg2_device()})
    coordinator = await make_coordinator(fake_hass, fake_entry, api)

    await coordinator._async_update_data()
    first_updated_at = coordinator.gate_status_freshness["SERIAL1"].updated_at
    assert first_updated_at is not None

    api.door_status_failures["SERIAL1"] = HTTPError("timeout")
    await coordinator._async_update_data()

    freshness = coordinator.gate_status_freshness["SERIAL1"]
    assert freshness.available is False
    # The timestamp of the last good read is preserved, not wiped, so a
    # consumer could report "last known good" rather than only "unknown".
    assert freshness.updated_at == first_updated_at


async def test_non_hg2_device_is_not_polled_for_door_status(fake_hass, fake_entry):
    camera = {"deviceInfos": {"name": "Camera", "model": "C6", "status": 1}}
    api = FakeApi({"SERIAL_CAM": camera})
    coordinator = await make_coordinator(fake_hass, fake_entry, api)

    data = await coordinator._async_update_data()

    assert api.door_status_calls == []
    assert "SERIAL_CAM" not in data  # not HG2/CH3, filtered out of coordinator.data


async def test_device_without_resolvable_route_is_not_polled(fake_hass, fake_entry):
    routeless = _hg2_device()
    routeless["resourceInfos"] = []
    api = FakeApi({"SERIAL1": routeless})
    coordinator = await make_coordinator(fake_hass, fake_entry, api)

    data = await coordinator._async_update_data()

    assert api.door_status_calls == []
    assert "SERIAL1" in data  # still inventoried, just no door status poll
    assert "SERIAL1" not in coordinator.gate_status_freshness


# --- per-gate settings via config subentries ---------------------------


class FakeSubentry:
    """Stand-in for homeassistant.config_entries.ConfigSubentry."""

    def __init__(self, subentry_type: str, unique_id: str, data: dict[str, Any]) -> None:
        self.subentry_type = subentry_type
        self.unique_id = unique_id
        self.data = data


async def test_gate_subentry_id_finds_matching_subentry(fake_hass, fake_entry):
    api = FakeApi({"SERIAL1": _hg2_device()})
    coordinator = await make_coordinator(fake_hass, fake_entry, api)
    fake_entry.subentries["sub1"] = FakeSubentry("gate", "SERIAL1", {"open_duration": 12})

    assert coordinator.gate_subentry_id("SERIAL1") == "sub1"
    assert coordinator.gate_subentry_id("SERIAL2") is None


async def test_gate_settings_returns_that_gates_own_subentry_data(fake_hass, fake_entry):
    api = FakeApi({"SERIAL1": _hg2_device(), "SERIAL2": _hg2_device()})
    coordinator = await make_coordinator(fake_hass, fake_entry, api)
    fake_entry.subentries["sub1"] = FakeSubentry(
        "gate", "SERIAL1", {"open_duration": 12, "close_duration": 11}
    )
    fake_entry.subentries["sub2"] = FakeSubentry(
        "gate", "SERIAL2", {"open_duration": 30, "close_duration": 28}
    )

    # Two gates on the same account must not see each other's duration:
    # this is exactly the bug the "gate" subentry split fixes.
    assert coordinator.gate_settings("SERIAL1") == {
        "open_duration": 12,
        "close_duration": 11,
    }
    assert coordinator.gate_settings("SERIAL2") == {
        "open_duration": 30,
        "close_duration": 28,
    }
    assert coordinator.gate_settings("SERIAL3") == {}


async def test_gate_subentry_id_ignores_other_subentry_types(fake_hass, fake_entry):
    api = FakeApi({"SERIAL1": _hg2_device()})
    coordinator = await make_coordinator(fake_hass, fake_entry, api)
    fake_entry.subentries["sub1"] = FakeSubentry("something_else", "SERIAL1", {})

    assert coordinator.gate_subentry_id("SERIAL1") is None
