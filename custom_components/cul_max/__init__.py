"""Home Assistant integration for a CUL in MAX! mode."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_DEVICE, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .const import (
    DOMAIN,
    PLATFORMS,
    SERVICE_BROADCAST_TIME,
    SERVICE_FAKE_WALL_THERMOSTAT,
    SERVICE_FAKE_WINDOW_CONTACT,
    SERVICE_PAIR_MODE,
)
from .gateway import CulMaxGateway

_LOGGER = logging.getLogger(__name__)

def cv_hex_address(value: Any) -> str:
    """Validate a MAX! RF address."""
    value = str(value).lower()
    if len(value) != 6 or any(char not in "0123456789abcdef" for char in value):
        raise vol.Invalid("must be exactly six hexadecimal characters")
    return value


SERVICE_SCHEMA_DEVICE = vol.Schema({vol.Required(CONF_DEVICE): cv_hex_address})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up CUL MAX! from a config entry."""
    gateway = CulMaxGateway(hass, entry)
    try:
        await gateway.async_connect()
    except OSError as err:
        raise ConfigEntryNotReady(f"Cannot open CUL serial interface: {err}") from err

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = gateway

    # Create the parent gateway device before child MAX! devices use it via_device.
    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=f"CUL MAX! ({entry.data['port']})",
        manufacturer="busware.de",
        model="CUL868",
        sw_version=gateway.cul_firmware,
    )

    await hass.config_entries.async_forward_entry_setups(entry, [Platform.BINARY_SENSOR, Platform.CLIMATE, Platform.SENSOR])

    async def pair_mode(call: ServiceCall) -> None:
        await gateway.async_enable_pair_mode(call.data.get("duration", 60))

    async def broadcast_time(call: ServiceCall) -> None:
        await gateway.async_broadcast_time()

    async def fake_window(call: ServiceCall) -> None:
        await gateway.async_send_fake_window_contact(
            call.data[CONF_DEVICE], call.data["is_open"], call.data.get("group_id", 0)
        )

    async def fake_wall_thermostat(call: ServiceCall) -> None:
        await gateway.async_send_fake_wall_thermostat(
            call.data[CONF_DEVICE],
            call.data["desired_temperature"],
            call.data["measured_temperature"],
            call.data.get("group_id", 0),
        )

    async def set_group_id(call: ServiceCall) -> None:
        await gateway.async_set_group_id(call.data[CONF_DEVICE], call.data["group_id"])

    async def configure_temperatures(call: ServiceCall) -> None:
        await gateway.async_configure_temperatures(
            call.data[CONF_DEVICE], comfort=call.data["comfort_temperature"], eco=call.data["eco_temperature"],
            maximum=call.data["maximum_temperature"], minimum=call.data["minimum_temperature"],
            offset=call.data["measurement_offset"], window_open=call.data["window_open_temperature"],
            window_duration=call.data["window_open_duration"], group_id=call.data.get("group_id", 0),
        )

    async def factory_reset(call: ServiceCall) -> None:
        await gateway.async_factory_reset(call.data[CONF_DEVICE])

    async def set_week_profile_day(call: ServiceCall) -> None:
        await gateway.async_set_week_profile_day(
            call.data[CONF_DEVICE], call.data["day"], call.data["schedule"]
        )

    # Services are integration-wide. The entry id avoids ambiguity with multiple CULs.
    if not hass.services.has_service(DOMAIN, SERVICE_PAIR_MODE):
        hass.services.async_register(
            DOMAIN, SERVICE_PAIR_MODE, pair_mode,
            schema=vol.Schema({vol.Optional("duration", default=60): vol.All(vol.Coerce(int), vol.Range(min=60, max=3600))}),
        )
        hass.services.async_register(DOMAIN, SERVICE_BROADCAST_TIME, broadcast_time)
        hass.services.async_register(
            DOMAIN, SERVICE_FAKE_WINDOW_CONTACT, fake_window,
            schema=SERVICE_SCHEMA_DEVICE.extend({vol.Required("is_open"): cv.boolean, vol.Optional("group_id", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=255))}),
        )
        hass.services.async_register(
            DOMAIN, SERVICE_FAKE_WALL_THERMOSTAT, fake_wall_thermostat,
            schema=SERVICE_SCHEMA_DEVICE.extend({
                vol.Required("desired_temperature"): vol.All(vol.Coerce(float), vol.Range(min=4.5, max=30.5)),
                vol.Required("measured_temperature"): vol.All(vol.Coerce(float), vol.Range(min=0, max=51.1)),
                vol.Optional("group_id", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=255)),
            }),
        )
        hass.services.async_register(
            DOMAIN, "set_group_id", set_group_id,
            schema=SERVICE_SCHEMA_DEVICE.extend({vol.Required("group_id"): vol.All(vol.Coerce(int), vol.Range(min=0, max=255))}),
        )
        hass.services.async_register(
            DOMAIN, "configure_temperatures", configure_temperatures,
            schema=SERVICE_SCHEMA_DEVICE.extend({
                vol.Required("comfort_temperature"): vol.All(vol.Coerce(float), vol.Range(min=4.5, max=30.5)),
                vol.Required("eco_temperature"): vol.All(vol.Coerce(float), vol.Range(min=4.5, max=30.5)),
                vol.Required("maximum_temperature"): vol.All(vol.Coerce(float), vol.Range(min=4.5, max=30.5)),
                vol.Required("minimum_temperature"): vol.All(vol.Coerce(float), vol.Range(min=4.5, max=30.5)),
                vol.Required("measurement_offset"): vol.All(vol.Coerce(float), vol.Range(min=-3.5, max=3.5)),
                vol.Required("window_open_temperature"): vol.All(vol.Coerce(float), vol.Range(min=4.5, max=30.5)),
                vol.Required("window_open_duration"): vol.All(vol.Coerce(int), vol.Range(min=0, max=60)),
                vol.Optional("group_id", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=255)),
            }),
        )
        hass.services.async_register(DOMAIN, "factory_reset", factory_reset, schema=SERVICE_SCHEMA_DEVICE)
        hass.services.async_register(
            DOMAIN,
            "set_week_profile_day",
            set_week_profile_day,
            schema=SERVICE_SCHEMA_DEVICE.extend({
                vol.Required("day"): vol.All(vol.Coerce(int), vol.Range(min=0, max=6)),
                vol.Required("schedule"): [
                    {
                        vol.Required("time"): str,
                        vol.Required("temperature"): vol.Coerce(float),
                    }
                ],
            }),
        )

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when serial connection settings have changed."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    gateway: CulMaxGateway = hass.data[DOMAIN].pop(entry.entry_id)
    await gateway.async_disconnect()
    return unloaded
