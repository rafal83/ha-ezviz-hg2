"""Shared pytest fixtures for the ezviz_hg2 test suite.

This suite runs against the real Home Assistant package (installed as a
regular dependency, see requirements-test.txt) but *without* the
``pytest-homeassistant-custom-component`` harness: on this Windows
environment its autouse, session-scoped ``mock_bluetooth_adapters`` fixture
unconditionally patches ``bluetooth_adapters.systems.linux``, which does not
exist outside Linux, and breaks every test in the session as soon as the
plugin is loaded. Home Assistant's own ``homeassistant.runner`` module also
hard-imports the POSIX-only ``fcntl``/``resource`` stdlib modules, which
Windows does not provide at all.

Instead, tests construct the integration's coordinator/entities directly
with small hand-built ``hass``/``ConfigEntry`` doubles (see ``FakeHass``
below). This exercises the real production code paths in
``coordinator.py``/``cover.py``/etc., just without Home Assistant's own
test scaffolding. On Linux/CI, where the official harness works, it remains
a reasonable follow-up to additionally adopt
``pytest-homeassistant-custom-component`` for entity-registry-level
integration tests (see the refactor's final report for details).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest


class FakeHass:
    """Minimal stand-in for HomeAssistant: only what our code touches."""

    async def async_add_executor_job(self, func, *args: Any) -> Any:
        return func(*args)


class FakeConfigEntry(MagicMock):
    """A MagicMock is sufficient: ConfigEntry is only used opaquely."""


@pytest.fixture
def fake_hass() -> FakeHass:
    return FakeHass()


@pytest.fixture
def fake_entry() -> FakeConfigEntry:
    entry = FakeConfigEntry()
    entry.entry_id = "test_entry"
    entry.options = {}
    return entry
