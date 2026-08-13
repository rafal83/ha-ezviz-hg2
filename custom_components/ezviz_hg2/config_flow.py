"""Config flow for EZVIZ HG2."""

from __future__ import annotations

import logging
from typing import Any, override

from pyezvizapi.client import EzvizClient
from pyezvizapi.exceptions import (
    EzvizAuthVerificationCode,
    HTTPError,
    InvalidURL,
    PyEzvizError,
)
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_TIMEOUT,
    CONF_URL,
    CONF_USERNAME,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_BLE_ADDRESS,
    CONF_BLE_FALLBACK_ENABLED,
    CONF_BLE_VERIFY_CODE,
    CONF_CLOSE_DURATION,
    CONF_OPEN_DURATION,
    CONF_RFSESSION_ID,
    CONF_SESSION_ID,
    DEFAULT_API_URL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TIMEOUT,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MAX_TRAVEL_DURATION,
    MIN_SCAN_INTERVAL,
    MIN_TRAVEL_DURATION,
    SUBENTRY_TYPE_GATE,
)
from .device import get_device_info, get_hg2_capabilities

_LOGGER = logging.getLogger(__name__)

CONF_SERIAL = "serial"


def _authenticate(data: dict[str, Any]) -> dict[str, Any]:
    client = EzvizClient(
        data[CONF_USERNAME],
        data[CONF_PASSWORD],
        data[CONF_URL],
        data[CONF_TIMEOUT],
    )
    token = client.login()
    return {
        CONF_SESSION_ID: token[CONF_SESSION_ID],
        CONF_RFSESSION_ID: token[CONF_RFSESSION_ID],
        CONF_URL: token["api_url"],
        CONF_TIMEOUT: data[CONF_TIMEOUT],
    }


class EzvizHg2ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configure an EZVIZ account used for HG2 discovery."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> EzvizHg2OptionsFlow:
        """Create the options flow."""
        return EzvizHg2OptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Each HG2 gate's travel duration and BLE fallback is its own subentry."""
        return {SUBENTRY_TYPE_GATE: GateSubentryFlowHandler}

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_USERNAME].casefold())
            self._abort_if_unique_id_configured()
            try:
                data = await self.hass.async_add_executor_job(
                    _authenticate, user_input
                )
            except EzvizAuthVerificationCode:
                errors["base"] = "mfa_required"
            except (HTTPError, InvalidURL):
                errors["base"] = "cannot_connect"
            except PyEzvizError:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected EZVIZ authentication error")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=user_input[CONF_USERNAME], data=data
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Required(CONF_URL, default=DEFAULT_API_URL): str,
                vol.Required(CONF_TIMEOUT, default=DEFAULT_TIMEOUT): vol.All(
                    vol.Coerce(int), vol.Range(min=5, max=120)
                ),
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )

    @override
    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Start reauthentication after an expired EZVIZ session."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Refresh the EZVIZ session with the account password."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            auth_input = {
                CONF_USERNAME: entry.title,
                CONF_PASSWORD: user_input[CONF_PASSWORD],
                CONF_URL: entry.data[CONF_URL],
                CONF_TIMEOUT: entry.data.get(CONF_TIMEOUT, DEFAULT_TIMEOUT),
            }
            try:
                data = await self.hass.async_add_executor_job(
                    _authenticate, auth_input
                )
            except EzvizAuthVerificationCode:
                errors["base"] = "mfa_required"
            except (HTTPError, InvalidURL):
                errors["base"] = "cannot_connect"
            except PyEzvizError:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected EZVIZ reauthentication error")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(entry, data=data)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
        )


class EzvizHg2OptionsFlow(OptionsFlow):
    """Let the user tune the cloud polling interval for the whole account."""

    @override
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )
        schema = vol.Schema(
            {
                vol.Required(CONF_SCAN_INTERVAL, default=current): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)


def _gate_settings_schema(
    *, available_serials: list[str] | None
) -> vol.Schema:
    """Build the gate settings schema, optionally including a serial picker.

    ``available_serials`` is only provided when creating a new subentry: an
    existing one's serial is fixed (it is the subentry's unique_id).
    """
    duration_validator = vol.All(
        vol.Coerce(int), vol.Range(min=MIN_TRAVEL_DURATION, max=MAX_TRAVEL_DURATION)
    )
    schema_dict: dict[Any, Any] = {}
    if available_serials is not None:
        schema_dict[vol.Required(CONF_SERIAL)] = vol.In(available_serials)
    schema_dict.update(
        {
            vol.Optional(CONF_OPEN_DURATION): duration_validator,
            vol.Optional(CONF_CLOSE_DURATION): duration_validator,
            vol.Required(CONF_BLE_FALLBACK_ENABLED, default=False): bool,
            vol.Optional(CONF_BLE_ADDRESS, default=""): str,
            vol.Optional(CONF_BLE_VERIFY_CODE, default=""): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            ),
        }
    )
    return vol.Schema(schema_dict)


def _normalize_gate_settings(
    user_input: dict[str, Any], errors: dict[str, str]
) -> dict[str, Any]:
    """Validate and normalize one gate subentry's settings."""
    normalized = dict(user_input)
    normalized[CONF_BLE_ADDRESS] = str(normalized.get(CONF_BLE_ADDRESS, "")).strip().upper()
    normalized[CONF_BLE_VERIFY_CODE] = str(normalized.get(CONF_BLE_VERIFY_CODE, "")).strip()
    if normalized.get(CONF_BLE_FALLBACK_ENABLED) and len(normalized[CONF_BLE_VERIFY_CODE]) != 6:
        errors[CONF_BLE_VERIFY_CODE] = "ble_verify_code_invalid"
    return normalized


class GateSubentryFlowHandler(ConfigSubentryFlow):
    """Manage one HG2 gate's own travel duration and BLE fallback settings."""

    def _available_serials(self) -> list[str]:
        entry = self._get_entry()
        coordinator = entry.runtime_data
        configured = {
            subentry.unique_id
            for subentry in entry.subentries.values()
            if subentry.subentry_type == SUBENTRY_TYPE_GATE
        }
        return sorted(
            serial
            for serial, device in getattr(coordinator, "data", {}).items()
            if isinstance(device, dict)
            and get_hg2_capabilities(device).gate_control
            and serial not in configured
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Add a subentry for one not-yet-configured HG2 gate."""
        available_serials = self._available_serials()
        if not available_serials:
            return self.async_abort(reason="no_gates_available")

        errors: dict[str, str] = {}
        if user_input is not None:
            serial = user_input.pop(CONF_SERIAL)
            normalized = _normalize_gate_settings(user_input, errors)
            if not errors:
                entry = self._get_entry()
                device = entry.runtime_data.data.get(serial, {})
                title = get_device_info(device).get("name") or serial
                return self.async_create_entry(
                    title=str(title), data=normalized, unique_id=serial
                )

        schema = self.add_suggested_values_to_schema(
            _gate_settings_schema(available_serials=available_serials),
            user_input,
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Edit an existing gate's travel duration and BLE fallback settings."""
        subentry = self._get_reconfigure_subentry()
        errors: dict[str, str] = {}
        if user_input is not None:
            normalized = _normalize_gate_settings(user_input, errors)
            if not errors:
                return self.async_update_and_abort(
                    self._get_entry(), subentry, data=normalized
                )

        schema = self.add_suggested_values_to_schema(
            _gate_settings_schema(available_serials=None),
            user_input if user_input is not None else subentry.data,
        )
        return self.async_show_form(
            step_id="reconfigure", data_schema=schema, errors=errors
        )
