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

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_TIMEOUT, CONF_URL, CONF_USERNAME

from .const import (
    CONF_RFSESSION_ID,
    CONF_SESSION_ID,
    DEFAULT_API_URL,
    DEFAULT_TIMEOUT,
    DOMAIN,
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
