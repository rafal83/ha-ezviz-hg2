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
    OptionsFlow,
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
    CONF_BLE_SERIAL,
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
)

_LOGGER = logging.getLogger(__name__)


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
    """Let the user tune cloud polling, travel, and optional BLE fallback."""

    @override
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            normalized = dict(user_input)
            normalized[CONF_BLE_SERIAL] = str(
                normalized.get(CONF_BLE_SERIAL, "")
            ).strip().upper()
            normalized[CONF_BLE_ADDRESS] = str(
                normalized.get(CONF_BLE_ADDRESS, "")
            ).strip().upper()
            normalized[CONF_BLE_VERIFY_CODE] = str(
                normalized.get(CONF_BLE_VERIFY_CODE, "")
            ).strip()
            if normalized.get(CONF_BLE_FALLBACK_ENABLED):
                if not normalized[CONF_BLE_SERIAL]:
                    errors[CONF_BLE_SERIAL] = "ble_serial_required"
                if len(normalized[CONF_BLE_VERIFY_CODE]) != 6:
                    errors[CONF_BLE_VERIFY_CODE] = "ble_verify_code_invalid"
            if not errors:
                return self.async_create_entry(data=normalized)

        displayed = (
            self.config_entry.options if user_input is None else normalized
        )
        current = displayed.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )
        current_open_duration = displayed.get(CONF_OPEN_DURATION)
        current_close_duration = displayed.get(CONF_CLOSE_DURATION)
        current_ble_enabled = displayed.get(
            CONF_BLE_FALLBACK_ENABLED, False
        )
        current_ble_serial = displayed.get(CONF_BLE_SERIAL, "")
        current_ble_address = displayed.get(CONF_BLE_ADDRESS, "")
        current_ble_verify_code = displayed.get(
            CONF_BLE_VERIFY_CODE, ""
        )
        runtime = self.config_entry.runtime_data
        serials = sorted(
            serial
            for serial, device in getattr(runtime, "data", {}).items()
            if isinstance(device, dict)
            and "HG2"
            in " ".join(
                str(device.get("deviceInfos", {}).get(key, ""))
                for key in (
                    "model",
                    "deviceSubCategory",
                    "productName",
                    "deviceType",
                )
            ).upper()
        )
        if not current_ble_serial and len(serials) == 1:
            current_ble_serial = serials[0]
        elif current_ble_serial and current_ble_serial not in serials:
            serials.append(current_ble_serial)
        duration_validator = vol.All(
            vol.Coerce(int),
            vol.Range(min=MIN_TRAVEL_DURATION, max=MAX_TRAVEL_DURATION),
        )
        schema_dict: dict[Any, Any] = {
            vol.Required(CONF_SCAN_INTERVAL, default=current): vol.All(
                vol.Coerce(int),
                vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
            ),
            vol.Required(
                CONF_BLE_FALLBACK_ENABLED, default=current_ble_enabled
            ): bool,
        }
        serial_validator: Any = vol.In(serials) if serials else str
        schema_dict[
            vol.Optional(CONF_BLE_SERIAL, default=current_ble_serial)
        ] = serial_validator
        schema_dict[
            vol.Optional(CONF_BLE_ADDRESS, default=current_ble_address)
        ] = str
        schema_dict[
            vol.Optional(CONF_BLE_VERIFY_CODE, default=current_ble_verify_code)
        ] = selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        )
        if current_open_duration is None:
            schema_dict[vol.Optional(CONF_OPEN_DURATION)] = duration_validator
        else:
            schema_dict[
                vol.Optional(CONF_OPEN_DURATION, default=current_open_duration)
            ] = duration_validator
        if current_close_duration is None:
            schema_dict[vol.Optional(CONF_CLOSE_DURATION)] = duration_validator
        else:
            schema_dict[
                vol.Optional(CONF_CLOSE_DURATION, default=current_close_duration)
            ] = duration_validator
        return self.async_show_form(
            step_id="init", data_schema=vol.Schema(schema_dict), errors=errors
        )
