"""Configuration flow for CUL MAX!."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult

from .const import (
    CONF_BAUDRATE,
    CONF_BROADCAST_TIME_DIFF,
    CONF_FAKE_SHUTTER_CONTACT_ADDRESS,
    CONF_FAKE_WALL_THERMOSTAT_ADDRESS,
    CONF_GATEWAY_ADDRESS,
    CONF_PORT,
    DEFAULT_BAUDRATE,
    DEFAULT_BROADCAST_TIME_DIFF,
    DEFAULT_FAKE_SHUTTER_CONTACT_ADDRESS,
    DEFAULT_FAKE_WALL_THERMOSTAT_ADDRESS,
    DEFAULT_GATEWAY_ADDRESS,
    DOMAIN,
)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PORT): str,
        vol.Required(CONF_BAUDRATE, default=DEFAULT_BAUDRATE): vol.All(
            vol.Coerce(int), vol.Range(min=1200, max=115200)
        ),
        # Address validation happens in async_step_user. Keeping this form schema to
        # basic HA-supported validators prevents a form-serialization 500 response.
        vol.Required(CONF_GATEWAY_ADDRESS, default=DEFAULT_GATEWAY_ADDRESS): str,
        vol.Required(
            CONF_FAKE_WALL_THERMOSTAT_ADDRESS,
            default=DEFAULT_FAKE_WALL_THERMOSTAT_ADDRESS,
        ): str,
        vol.Required(
            CONF_FAKE_SHUTTER_CONTACT_ADDRESS,
            default=DEFAULT_FAKE_SHUTTER_CONTACT_ADDRESS,
        ): str,
        vol.Required(
            CONF_BROADCAST_TIME_DIFF, default=DEFAULT_BROADCAST_TIME_DIFF
        ): vol.All(vol.Coerce(int), vol.Range(min=0, max=300)),
    }
)


def _validate_address(value: Any) -> str:
    """Validate and normalize a six-character MAX! RF address."""
    address = str(value).lower()
    if len(address) != 6 or any(char not in "0123456789abcdef" for char in address):
        raise ValueError
    return address


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure a local CUL MAX! serial gateway."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial setup step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                user_input[CONF_GATEWAY_ADDRESS] = _validate_address(
                    user_input[CONF_GATEWAY_ADDRESS]
                )
                user_input[CONF_FAKE_WALL_THERMOSTAT_ADDRESS] = _validate_address(
                    user_input[CONF_FAKE_WALL_THERMOSTAT_ADDRESS]
                )
                user_input[CONF_FAKE_SHUTTER_CONTACT_ADDRESS] = _validate_address(
                    user_input[CONF_FAKE_SHUTTER_CONTACT_ADDRESS]
                )
            except ValueError:
                errors["base"] = "invalid_address"
            else:
                await self.async_set_unique_id(user_input[CONF_PORT])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"CUL MAX! ({user_input[CONF_PORT]})", data=user_input
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )
