"""Configuration flow for CUL MAX!."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_BAUDRATE, CONF_BROADCAST_TIME_DIFF, CONF_FAKE_SHUTTER_CONTACT_ADDRESS,
    CONF_FAKE_WALL_THERMOSTAT_ADDRESS, CONF_GATEWAY_ADDRESS, CONF_PORT,
    DEFAULT_BAUDRATE, DEFAULT_BROADCAST_TIME_DIFF, DEFAULT_FAKE_SHUTTER_CONTACT_ADDRESS,
    DEFAULT_FAKE_WALL_THERMOSTAT_ADDRESS, DEFAULT_GATEWAY_ADDRESS, DOMAIN,
)


def _address(value: str) -> str:
    value = str(value).lower()
    if len(value) != 6 or any(char not in "0123456789abcdef" for char in value):
        raise vol.Invalid("must contain six hexadecimal characters")
    return value


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure a local CUL MAX! serial gateway."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_PORT])
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=f"CUL MAX! ({user_input[CONF_PORT]})", data=user_input)

        schema = vol.Schema({
            vol.Required(CONF_PORT): str,
            vol.Required(CONF_BAUDRATE, default=DEFAULT_BAUDRATE): vol.All(vol.Coerce(int), vol.Range(min=1200, max=115200)),
            vol.Required(CONF_GATEWAY_ADDRESS, default=DEFAULT_GATEWAY_ADDRESS): _address,
            vol.Required(CONF_FAKE_WALL_THERMOSTAT_ADDRESS, default=DEFAULT_FAKE_WALL_THERMOSTAT_ADDRESS): _address,
            vol.Required(CONF_FAKE_SHUTTER_CONTACT_ADDRESS, default=DEFAULT_FAKE_SHUTTER_CONTACT_ADDRESS): _address,
            vol.Required(CONF_BROADCAST_TIME_DIFF, default=DEFAULT_BROADCAST_TIME_DIFF): vol.All(vol.Coerce(int), vol.Range(min=0, max=300)),
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)
