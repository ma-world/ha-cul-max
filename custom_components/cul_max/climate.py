"""Climate entities for MAX! heating and wall thermostats."""
from __future__ import annotations

from homeassistant.components.climate import ClimateEntity, HVACMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_DEVICE_UPDATED, SIGNAL_NEW_DEVICE
from .entity import CulMaxEntity
from .gateway import CulMaxGateway, MaxDevice

THERMOSTAT_TYPES = {"HeatingThermostat", "HeatingThermostatPlus", "WallMountedThermostat", "virtualThermostat"}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Create climate entities as thermostats become known."""
    gateway: CulMaxGateway = hass.data[DOMAIN][entry.entry_id]
    added: set[str] = set()

    def add(address: str) -> None:
        device = gateway.devices[address]
        if address not in added and device.device_type in THERMOSTAT_TYPES:
            added.add(address)
            async_add_entities([CulMaxClimate(gateway, device)])

    for address in gateway.devices:
        add(address)
    entry.async_on_unload(async_dispatcher_connect(
        hass, SIGNAL_NEW_DEVICE, lambda eid, address: add(address) if eid == entry.entry_id else None
    ))


class CulMaxClimate(CulMaxEntity, ClimateEntity):
    """A MAX! thermostat."""

    key = "climate"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 0.5
    _attr_min_temp = 4.5
    _attr_max_temp = 30.5
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]

    @property
    def current_temperature(self) -> float | None:
        return self.device.data.get("measured_temperature")

    @property
    def target_temperature(self) -> float | None:
        return self.device.data.get("target_temperature")

    @property
    def hvac_mode(self) -> HVACMode:
        return HVACMode.OFF if self.device.data.get("target_temperature") == 4.5 else HVACMode.HEAT

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        keys = ("mode", "valve_position", "battery", "rf_error", "panel_locked", "until", "group_id")
        return {key: self.device.data[key] for key in keys if key in self.device.data}

    async def async_set_temperature(self, **kwargs: float) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is not None:
            await self.gateway.async_set_target_temperature(self.device.address, temperature)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        await self.gateway.async_set_target_temperature(
            self.device.address, 4.5 if hvac_mode == HVACMode.OFF else (self.target_temperature or 20.0)
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(
            self.hass, SIGNAL_DEVICE_UPDATED,
            lambda eid, address: self.async_write_ha_state()
            if eid == self.gateway.entry.entry_id and address == self.device.address else None,
        ))
