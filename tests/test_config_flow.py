"""Tests against the real config_flow.py gate-settings validation.

GateSubentryFlowHandler itself needs a live flow context (self.hass,
self._entry_id, ...) that the Windows-broken pytest-homeassistant-custom-
component harness would normally provide (see tests/conftest.py). The
validation/normalization logic it delegates to is a plain function, so it
is tested directly here against the real code.
"""

from __future__ import annotations

from custom_components.ezviz_hg2.config_flow import _normalize_gate_settings
from custom_components.ezviz_hg2.const import (
    CONF_BLE_ADDRESS,
    CONF_BLE_FALLBACK_ENABLED,
    CONF_BLE_VERIFY_CODE,
)


def test_ble_disabled_skips_verify_code_validation():
    errors: dict[str, str] = {}
    result = _normalize_gate_settings(
        {CONF_BLE_FALLBACK_ENABLED: False, CONF_BLE_ADDRESS: "", CONF_BLE_VERIFY_CODE: ""},
        errors,
    )
    assert errors == {}
    assert result[CONF_BLE_FALLBACK_ENABLED] is False


def test_ble_enabled_requires_six_character_verify_code():
    errors: dict[str, str] = {}
    _normalize_gate_settings(
        {
            CONF_BLE_FALLBACK_ENABLED: True,
            CONF_BLE_ADDRESS: "AA:BB:CC:DD:EE:FF",
            CONF_BLE_VERIFY_CODE: "12345",
        },
        errors,
    )
    assert errors[CONF_BLE_VERIFY_CODE] == "ble_verify_code_invalid"


def test_ble_enabled_with_valid_verify_code_has_no_error():
    errors: dict[str, str] = {}
    _normalize_gate_settings(
        {
            CONF_BLE_FALLBACK_ENABLED: True,
            CONF_BLE_ADDRESS: "aa:bb:cc:dd:ee:ff",
            CONF_BLE_VERIFY_CODE: "abc123",
        },
        errors,
    )
    assert errors == {}


def test_ble_address_and_verify_code_are_normalized():
    errors: dict[str, str] = {}
    result = _normalize_gate_settings(
        {
            CONF_BLE_FALLBACK_ENABLED: False,
            CONF_BLE_ADDRESS: "  aa:bb:cc:dd:ee:ff  ",
            CONF_BLE_VERIFY_CODE: "  abc123  ",
        },
        errors,
    )
    assert result[CONF_BLE_ADDRESS] == "AA:BB:CC:DD:EE:FF"
    # Only whitespace is trimmed from the verify code: unlike the address,
    # it is not case-normalized (EZVIZ codes may be case-sensitive).
    assert result[CONF_BLE_VERIFY_CODE] == "abc123"


def test_missing_ble_fields_default_to_empty_string():
    errors: dict[str, str] = {}
    result = _normalize_gate_settings({CONF_BLE_FALLBACK_ENABLED: False}, errors)
    assert result[CONF_BLE_ADDRESS] == ""
    assert result[CONF_BLE_VERIFY_CODE] == ""
    assert errors == {}
