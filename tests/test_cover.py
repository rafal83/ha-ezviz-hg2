"""Tests against the real EzvizHg2Cover entity (not a reimplementation).

Constructed directly (CoordinatorEntity/Entity do not require a running
hass at construction time) with a small FakeCoordinator double instead of
the Windows-broken pytest-homeassistant-custom-component harness — see
tests/conftest.py for why. This covers the refactor's core "Position" and
"Cloud/BLE" scenarios against the actual shipped cover.py code:
  - a failed open/close never leaves the cover reporting fake movement
  - a gate found "open" at startup is not assumed to be at 100%
  - availability is the OR of cloud and BLE reachability, not BLE-configured
"""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.ezviz_hg2.cover import EzvizHg2Cover, async_setup_entry
from custom_components.ezviz_hg2.coordinator import GateStatusFreshness


def _hg2_device(status: int | None = None) -> dict[str, Any]:
    device: dict[str, Any] = {
        "deviceInfos": {"name": "Portail", "model": "HG2-400", "status": 1},
        "resourceInfos": [{"resourceId": "abc", "localIndex": "0"}],
    }
    if status is not None:
        device["FEATURE_INFO"] = {
            "0": {"global": {"Door": {"DoorStatus": {"doorStatus": [status]}}}}
        }
    return device


class FakeApi:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.next_error: Exception | None = None

    def send_iot_action(self, serial, resource_id, local_index, domain_id, action_id, payload):
        self.calls.append((serial, resource_id, local_index, domain_id, action_id, payload))
        if self.next_error is not None:
            raise self.next_error
        return {"meta": {"code": 200}}


class FakeBle:
    def __init__(self, serial: str, present: bool = True) -> None:
        self._serial = serial
        self._present = present
        self.sent: list[str] = []
        self.next_error: Exception | None = None

    def is_present(self) -> bool:
        return self._present

    async def async_send(self, command: str) -> None:
        if self.next_error is not None:
            raise self.next_error
        self.sent.append(command)


class FakeSubentry:
    def __init__(self, subentry_type: str, unique_id: str, data: dict[str, Any]) -> None:
        self.subentry_type = subentry_type
        self.unique_id = unique_id
        self.data = data


class FakeCoordinator:
    def __init__(self, devices: dict[str, Any], api: FakeApi | None = None) -> None:
        self.data = devices
        self.gate_status_freshness: dict[str, GateStatusFreshness] = {}
        self.ble_controllers: dict[str, FakeBle] = {}
        self.last_update_success = True
        self.api = api or FakeApi()
        self.refresh_calls = 0
        self.subentries: dict[str, FakeSubentry] = {}

    async def async_request_refresh(self) -> None:
        self.refresh_calls += 1

    def gate_subentry_id(self, serial: str) -> str | None:
        for subentry_id, subentry in self.subentries.items():
            if subentry.subentry_type == "gate" and subentry.unique_id == serial:
                return subentry_id
        return None

    def gate_settings(self, serial: str) -> dict[str, Any]:
        for subentry in self.subentries.values():
            if subentry.subentry_type == "gate" and subentry.unique_id == serial:
                return dict(subentry.data)
        return {}


def make_cover(coordinator: FakeCoordinator, serial: str = "SERIAL1", *, calibrated=True) -> EzvizHg2Cover:
    entity = EzvizHg2Cover(
        coordinator, serial, 10.0 if calibrated else None, 10.0 if calibrated else None
    )
    entity.hass = coordinator.hass if hasattr(coordinator, "hass") else FakeHassForEntity()
    return entity


class FakeHassForEntity:
    async def async_add_executor_job(self, func, *args: Any) -> Any:
        return func(*args)


# --- fake movement after failed commands ------------------------------------


async def test_failed_open_does_not_start_a_fake_movement():
    device = _hg2_device(status=0)
    coordinator = FakeCoordinator({"SERIAL1": device})
    coordinator.api.next_error = RuntimeError("network is down")
    cover = make_cover(coordinator)

    with pytest.raises(HomeAssistantError):
        await cover.async_open_cover()

    assert cover._movement.is_moving is False
    assert cover.current_cover_position is None


async def test_successful_open_starts_movement_only_after_command_succeeds():
    device = _hg2_device(status=0)
    coordinator = FakeCoordinator({"SERIAL1": device})
    cover = make_cover(coordinator)

    await cover.async_open_cover()

    assert cover._movement.is_moving is True
    assert cover._movement.target == 100.0
    assert coordinator.api.calls, "the cloud command must have been attempted"


async def test_failed_close_does_not_start_a_fake_movement():
    device = _hg2_device(status=1)
    coordinator = FakeCoordinator({"SERIAL1": device})
    coordinator.api.next_error = RuntimeError("network is down")
    cover = make_cover(coordinator)

    with pytest.raises(HomeAssistantError):
        await cover.async_close_cover()

    assert cover._movement.is_moving is False


async def test_failed_pause_leaves_the_movement_running():
    device = _hg2_device(status=1)
    coordinator = FakeCoordinator({"SERIAL1": device})
    cover = make_cover(coordinator)
    await cover.async_open_cover()
    assert cover._movement.is_moving is True

    coordinator.api.next_error = RuntimeError("network is down")
    with pytest.raises(HomeAssistantError):
        await cover.async_stop_cover()

    # A failed pause must not claim the gate stopped when it may still be
    # physically moving: the movement estimate keeps running.
    assert cover._movement.is_moving is True


# --- startup position ---------------------------------------------------


def test_gate_open_at_startup_has_no_assumed_position():
    device = _hg2_device(status=1)
    coordinator = FakeCoordinator({"SERIAL1": device})
    coordinator.gate_status_freshness["SERIAL1"] = GateStatusFreshness(True, 100.0)
    cover = make_cover(coordinator)
    cover.async_write_ha_state = lambda: None  # entity is not registered with hass

    cover._handle_coordinator_update()

    assert cover.current_cover_position is None
    assert cover.is_closed is False


def test_gate_closed_at_startup_reports_zero():
    device = _hg2_device(status=0)
    coordinator = FakeCoordinator({"SERIAL1": device})
    coordinator.gate_status_freshness["SERIAL1"] = GateStatusFreshness(True, 100.0)
    cover = make_cover(coordinator)
    cover.async_write_ha_state = lambda: None  # entity is not registered with hass

    cover._handle_coordinator_update()

    assert cover.current_cover_position == 0
    assert cover.is_closed is True


def test_stale_door_status_reports_unknown_not_last_cached_value():
    device = _hg2_device(status=0)  # cached "closed" from before the outage
    coordinator = FakeCoordinator({"SERIAL1": device})
    coordinator.gate_status_freshness["SERIAL1"] = GateStatusFreshness(False, 50.0)
    cover = make_cover(coordinator)

    assert cover.is_closed is None


# --- availability: cloud vs BLE ------------------------------------------


def test_available_via_cloud_without_ble():
    device = _hg2_device(status=0)
    coordinator = FakeCoordinator({"SERIAL1": device})
    cover = make_cover(coordinator)
    assert cover.available is True


def test_unavailable_when_cloud_down_and_no_ble():
    device = _hg2_device(status=0)
    coordinator = FakeCoordinator({"SERIAL1": device})
    coordinator.last_update_success = False
    cover = make_cover(coordinator)
    assert cover.available is False


def test_available_via_ble_when_cloud_down():
    device = _hg2_device(status=0)
    coordinator = FakeCoordinator({"SERIAL1": device})
    coordinator.last_update_success = False
    coordinator.ble_controllers["SERIAL1"] = FakeBle("SERIAL1", present=True)
    cover = make_cover(coordinator)
    assert cover.available is True


def test_unavailable_when_ble_configured_but_not_currently_present():
    # BLE being *configured* must not, by itself, make the cover available:
    # it must also be currently reachable.
    device = _hg2_device(status=0)
    coordinator = FakeCoordinator({"SERIAL1": device})
    coordinator.last_update_success = False
    coordinator.ble_controllers["SERIAL1"] = FakeBle("SERIAL1", present=False)
    cover = make_cover(coordinator)
    assert cover.available is False


def test_unavailable_when_ble_configured_for_a_different_serial():
    device = _hg2_device(status=0)
    coordinator = FakeCoordinator({"SERIAL1": device})
    coordinator.last_update_success = False
    coordinator.ble_controllers["OTHER_SERIAL"] = FakeBle("OTHER_SERIAL", present=True)
    cover = make_cover(coordinator)
    assert cover.available is False


# --- cloud/BLE command routing -------------------------------------------


async def test_ble_fallback_when_cloud_reports_device_offline():
    device = _hg2_device(status=0)
    device["deviceInfos"]["status"] = 0  # EZVIZ reports the device offline
    coordinator = FakeCoordinator({"SERIAL1": device})
    coordinator.ble_controllers["SERIAL1"] = FakeBle("SERIAL1")
    cover = make_cover(coordinator)

    await cover.async_open_cover()

    assert coordinator.ble_controllers["SERIAL1"].sent == ["open"]
    assert coordinator.api.calls == []  # cloud was never even attempted


async def test_no_ble_fallback_on_ambiguous_cloud_error():
    device = _hg2_device(status=0)
    coordinator = FakeCoordinator({"SERIAL1": device})
    coordinator.ble_controllers["SERIAL1"] = FakeBle("SERIAL1")
    coordinator.api.next_error = RuntimeError("connection reset")
    cover = make_cover(coordinator)

    with pytest.raises(HomeAssistantError, match="ambiguous"):
        await cover.async_open_cover()

    assert coordinator.ble_controllers["SERIAL1"].sent == []


async def test_ble_fallback_on_explicit_cloud_rejection():
    from custom_components.ezviz_hg2.api import EzvizActionRejected

    device = _hg2_device(status=0)
    coordinator = FakeCoordinator({"SERIAL1": device})
    coordinator.ble_controllers["SERIAL1"] = FakeBle("SERIAL1")
    coordinator.api.next_error = EzvizActionRejected("meta code 4001")
    cover = make_cover(coordinator)

    await cover.async_open_cover()

    assert coordinator.ble_controllers["SERIAL1"].sent == ["open"]


async def test_ble_error_is_surfaced_as_home_assistant_error():
    device = _hg2_device(status=0)
    device["deviceInfos"]["status"] = 0
    coordinator = FakeCoordinator({"SERIAL1": device})
    coordinator.ble_controllers["SERIAL1"] = FakeBle("SERIAL1")
    coordinator.ble_controllers["SERIAL1"].next_error = RuntimeError("BLE adapter busy")
    cover = make_cover(coordinator)

    with pytest.raises(HomeAssistantError):
        await cover.async_open_cover()


# --- async_setup_entry: per-gate duration via config subentries ------------


class FakeEntry:
    def __init__(self, coordinator: FakeCoordinator) -> None:
        self.runtime_data = coordinator


def _capturing_add_entities():
    calls: list[tuple[list[Any], str | None]] = []

    def add_entities(entities, config_subentry_id=None):
        calls.append((list(entities), config_subentry_id))

    return add_entities, calls


async def test_setup_entry_gives_each_gate_its_own_subentry_duration():
    # Reproduces the multi-gate bug: two HG2 gates on one account must not
    # end up sharing a single open/close duration.
    coordinator = FakeCoordinator(
        {"SERIAL1": _hg2_device(status=0), "SERIAL2": _hg2_device(status=0)}
    )
    coordinator.subentries["sub1"] = FakeSubentry(
        "gate", "SERIAL1", {"open_duration": 12, "close_duration": 11}
    )
    coordinator.subentries["sub2"] = FakeSubentry(
        "gate", "SERIAL2", {"open_duration": 30, "close_duration": 28}
    )
    entry = FakeEntry(coordinator)
    add_entities, calls = _capturing_add_entities()

    await async_setup_entry(FakeHassForEntity(), entry, add_entities)

    covers_by_serial = {c._serial: c for group, _ in calls for c in group}
    assert covers_by_serial["SERIAL1"]._open_duration == 12
    assert covers_by_serial["SERIAL1"]._close_duration == 11
    assert covers_by_serial["SERIAL2"]._open_duration == 30
    assert covers_by_serial["SERIAL2"]._close_duration == 28


async def test_setup_entry_groups_entities_by_their_own_subentry():
    coordinator = FakeCoordinator(
        {"SERIAL1": _hg2_device(status=0), "SERIAL2": _hg2_device(status=0)}
    )
    coordinator.subentries["sub1"] = FakeSubentry("gate", "SERIAL1", {})
    # SERIAL2 has no subentry yet (not configured through "Add a gate").
    entry = FakeEntry(coordinator)
    add_entities, calls = _capturing_add_entities()

    await async_setup_entry(FakeHassForEntity(), entry, add_entities)

    subentry_ids = {subentry_id for _, subentry_id in calls}
    assert subentry_ids == {"sub1", None}
    groups = {subentry_id: [c._serial for c in group] for group, subentry_id in calls}
    assert groups["sub1"] == ["SERIAL1"]
    assert groups[None] == ["SERIAL2"]


async def test_setup_entry_skips_devices_without_gate_control():
    routeless = _hg2_device(status=0)
    routeless["resourceInfos"] = []
    coordinator = FakeCoordinator({"SERIAL1": routeless})
    entry = FakeEntry(coordinator)
    add_entities, calls = _capturing_add_entities()

    await async_setup_entry(FakeHassForEntity(), entry, add_entities)

    assert calls == []
