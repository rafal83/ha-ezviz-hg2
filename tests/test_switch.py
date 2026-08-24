"""Tests against the real EzvizSwitchTypeSwitch (not a reimplementation).

Constructed directly (CoordinatorEntity/Entity do not require a running hass
at construction time) with a small FakeCoordinator double instead of the
Windows-broken pytest-homeassistant-custom-component harness — see
tests/conftest.py for why.
"""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.ezviz_hg2.switch import (
    SWITCH_TYPES,
    EzvizSwitchTypeSwitch,
    async_setup_entry,
)


def _ch3_device(switches: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "deviceInfos": {"name": "Carillon", "model": "CH3", "status": 1},
        "SWITCH": switches if switches is not None else [{"type": 611, "enable": False}],
    }


class FakeApi:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, bool]] = []
        self.next_error: Exception | None = None

    def set_switch(self, serial: str, switch_type: int, enable: bool) -> bool:
        self.calls.append((serial, switch_type, enable))
        if self.next_error is not None:
            raise self.next_error
        return True


class FakeCoordinator:
    def __init__(self, devices: dict[str, Any], api: FakeApi | None = None) -> None:
        self.data = devices
        self.api = api or FakeApi()
        self.refresh_calls = 0
        self.last_update_success = True
        self.subentries: dict[str, Any] = {}

    async def async_request_refresh(self) -> None:
        self.refresh_calls += 1

    def gate_subentry_id(self, serial: str) -> str | None:
        return None


class FakeEntry:
    def __init__(self, coordinator: FakeCoordinator) -> None:
        self.runtime_data = coordinator


class FakeHassForEntity:
    async def async_add_executor_job(self, func, *args: Any) -> Any:
        return func(*args)


def make_switch(coordinator: FakeCoordinator, serial: str = "SERIAL1") -> EzvizSwitchTypeSwitch:
    entity = EzvizSwitchTypeSwitch(coordinator, None, serial, SWITCH_TYPES[0])
    entity.hass = FakeHassForEntity()
    return entity


# --- setup --------------------------------------------------------------


def _strict_add_entities():
    calls: list[tuple[list[Any], dict[str, Any]]] = []

    def add_entities(entities, *args: Any, **kwargs: Any) -> None:
        calls.append((list(entities), kwargs))

    return add_entities, calls


async def test_setup_creates_switch_when_type_present():
    coordinator = FakeCoordinator({"SERIAL1": _ch3_device()})
    entry = FakeEntry(coordinator)
    add_entities, calls = _strict_add_entities()

    await async_setup_entry(None, entry, add_entities)

    assert len(calls) == 1
    entities, _ = calls[0]
    assert any(isinstance(entity, EzvizSwitchTypeSwitch) for entity in entities)


async def test_setup_skips_devices_without_the_switch_type():
    coordinator = FakeCoordinator({"SERIAL1": _ch3_device(switches=[{"type": 3, "enable": True}])})
    entry = FakeEntry(coordinator)
    add_entities, calls = _strict_add_entities()

    await async_setup_entry(None, entry, add_entities)

    assert calls == []


# --- entity behavior ----------------------------------------------------


def test_is_on_reads_the_switch_list():
    coordinator = FakeCoordinator({"SERIAL1": _ch3_device([{"type": 611, "enable": True}])})
    switch = make_switch(coordinator)
    assert switch.is_on is True


def test_available_false_when_type_absent():
    coordinator = FakeCoordinator({"SERIAL1": _ch3_device(switches=[])})
    switch = make_switch(coordinator)
    assert switch.available is False


async def test_turn_on_calls_api_and_requests_refresh():
    coordinator = FakeCoordinator({"SERIAL1": _ch3_device()})
    switch = make_switch(coordinator)

    await switch.async_turn_on()

    assert coordinator.api.calls == [("SERIAL1", 611, True)]
    assert coordinator.refresh_calls == 1


async def test_turn_off_calls_api_with_false():
    coordinator = FakeCoordinator({"SERIAL1": _ch3_device()})
    switch = make_switch(coordinator)

    await switch.async_turn_off()

    assert coordinator.api.calls == [("SERIAL1", 611, False)]


async def test_turn_on_wraps_cloud_errors():
    api = FakeApi()
    api.next_error = RuntimeError("rejected")
    coordinator = FakeCoordinator({"SERIAL1": _ch3_device()}, api=api)
    switch = make_switch(coordinator)

    with pytest.raises(HomeAssistantError):
        await switch.async_turn_on()

    assert coordinator.refresh_calls == 0
