"""Tests against the real EzvizHg2UpdateEntity (not a reimplementation).

Constructed directly (CoordinatorEntity/Entity do not require a running hass
at construction time) with a small FakeCoordinator double instead of the
Windows-broken pytest-homeassistant-custom-component harness — see
tests/conftest.py for why.
"""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.exceptions import HomeAssistantError
from pyezvizapi.exceptions import PyEzvizError

from custom_components.ezviz_hg2.update import EzvizHg2UpdateEntity, async_setup_entry


def _hg2_device(**upgrade_overrides: Any) -> dict[str, Any]:
    device: dict[str, Any] = {
        "deviceInfos": {"name": "Portail", "model": "HG2-400", "status": 1, "version": "1.0.0"},
        "resourceInfos": [{"resourceId": "abc", "localIndex": "0"}],
    }
    device.update(upgrade_overrides)
    return device


class FakeApi:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.next_error: Exception | None = None

    def upgrade_device(self, serial: str) -> bool:
        self.calls.append(serial)
        if self.next_error is not None:
            raise self.next_error
        return True


class FakeSubentry:
    def __init__(self, subentry_type: str, unique_id: str, data: dict[str, Any]) -> None:
        self.subentry_type = subentry_type
        self.unique_id = unique_id
        self.data = data


class FakeCoordinator:
    def __init__(self, devices: dict[str, Any], api: FakeApi | None = None) -> None:
        self.data = devices
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


class FakeEntry:
    def __init__(self, coordinator: FakeCoordinator) -> None:
        self.runtime_data = coordinator


class FakeHassForEntity:
    async def async_add_executor_job(self, func, *args: Any) -> Any:
        return func(*args)


def make_entity(coordinator: FakeCoordinator, serial: str = "SERIAL1") -> EzvizHg2UpdateEntity:
    entity = EzvizHg2UpdateEntity(coordinator, serial)
    entity.hass = FakeHassForEntity()
    return entity


# --- setup --------------------------------------------------------------


def _strict_add_entities():
    calls: list[tuple[list[Any], dict[str, Any]]] = []

    def add_entities(entities, *args: Any, **kwargs: Any) -> None:
        calls.append((list(entities), kwargs))

    return add_entities, calls


async def test_setup_creates_one_entity_per_supported_device():
    coordinator = FakeCoordinator({"SERIAL1": _hg2_device()})
    entry = FakeEntry(coordinator)
    add_entities, calls = _strict_add_entities()

    await async_setup_entry(None, entry, add_entities)

    assert len(calls) == 1
    entities, _ = calls[0]
    assert len(entities) == 1
    assert isinstance(entities[0], EzvizHg2UpdateEntity)


async def test_setup_skips_unsupported_devices():
    coordinator = FakeCoordinator({"SERIAL1": {"deviceInfos": {"model": "C6"}}})
    entry = FakeEntry(coordinator)
    add_entities, calls = _strict_add_entities()

    await async_setup_entry(None, entry, add_entities)

    assert calls == []


# --- entity properties ----------------------------------------------------


def test_installed_version_reads_device_info_version():
    coordinator = FakeCoordinator({"SERIAL1": _hg2_device()})
    entity = make_entity(coordinator)
    assert entity.installed_version == "1.0.0"


def test_latest_version_falls_back_to_installed_without_an_update():
    coordinator = FakeCoordinator({"SERIAL1": _hg2_device()})
    entity = make_entity(coordinator)
    assert entity.latest_version == "1.0.0"


def test_latest_version_reads_the_queued_firmware_when_available():
    device = _hg2_device(
        UPGRADE={
            "isNeedUpgrade": 3,
            "upgradePackageInfo": {"version": "1.2.0", "desc": "Motor fix"},
        }
    )
    coordinator = FakeCoordinator({"SERIAL1": device})
    entity = make_entity(coordinator)
    assert entity.latest_version == "1.2.0"


def test_release_notes_reads_the_queued_firmware_description():
    device = _hg2_device(
        UPGRADE={
            "isNeedUpgrade": 3,
            "upgradePackageInfo": {"version": "1.2.0", "desc": "Motor fix"},
        }
    )
    coordinator = FakeCoordinator({"SERIAL1": device})
    entity = make_entity(coordinator)
    assert entity.release_notes() == "Motor fix"


def test_release_notes_none_without_a_queued_firmware():
    coordinator = FakeCoordinator({"SERIAL1": _hg2_device()})
    entity = make_entity(coordinator)
    assert entity.release_notes() is None


def test_in_progress_and_percentage_track_status():
    device = _hg2_device(STATUS={"upgradeStatus": 0, "upgradeProcess": 42})
    coordinator = FakeCoordinator({"SERIAL1": device})
    entity = make_entity(coordinator)
    assert entity.in_progress is True
    assert entity.update_percentage == 42


def test_update_percentage_none_when_not_in_progress():
    coordinator = FakeCoordinator({"SERIAL1": _hg2_device()})
    entity = make_entity(coordinator)
    assert entity.in_progress is False
    assert entity.update_percentage is None


# --- install ----------------------------------------------------------------


async def test_async_install_calls_api_and_requests_refresh():
    coordinator = FakeCoordinator({"SERIAL1": _hg2_device()})
    entity = make_entity(coordinator)

    await entity.async_install(version=None, backup=False)

    assert coordinator.api.calls == ["SERIAL1"]
    assert coordinator.refresh_calls == 1


async def test_async_install_wraps_cloud_errors():
    api = FakeApi()
    api.next_error = PyEzvizError("rejected")
    coordinator = FakeCoordinator({"SERIAL1": _hg2_device()}, api=api)
    entity = make_entity(coordinator)

    with pytest.raises(HomeAssistantError):
        await entity.async_install(version=None, backup=False)

    assert coordinator.refresh_calls == 0
