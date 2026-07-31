"""Sensors for MAX! devices."""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_NEW_DEVICE, SIGNAL_DEVICE_UPDATED
from .entity import CulMaxEntity
from .gateway import CulMaxGateway, MaxDevice


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    gateway: CulMaxGateway = hass.data[DOMAIN][entry.entry_id]
    added: set[tuple[str, str]] = set()

    def add(address: str) -> None:
        device = gateway.devices[address]
        entities: list[SensorEntity] = []
        for key, cls in (("measured_temperature", CulMaxTemperature), ("target_temperature", CulMaxTargetTemperature), ("valve_position", CulMaxValvePosition)):
            if (address, key) not in added and device.device_type not in {"ShutterContact", "virtualShutterContact"}:
                added.add((address, key))
                entities.append(cls(gateway, device))
        if entities:
            async_add_entities(entities)

    for address in gateway.devices:
        add(address)
    entry.async_on_unload(async_dispatcher_connect(hass, SIGNAL_NEW_DEVICE, lambda eid, address: add(address) if eid == entry.entry_id else None))


class _ValueSensor(CulMaxEntity, SensorEntity):
    data_key: str

    @property
    def native_value(self):
        return self.device.data.get(self.data_key)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(
            self.hass, SIGNAL_DEVICE_UPDATED,
            lambda eid, address: self.async_write_ha_state() if eid == self.gateway.entry.entry_id and address == self.device.address else None,
        ))


class CulMaxTemperature(_ValueSensor):
    key = "temperature"
    data_key = "measured_temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_suggested_display_precision = 1


class CulMaxTargetTemperature(_ValueSensor):
    key = "target_temperature"
    data_key = "target_temperature"
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_suggested_display_precision = 1


class CulMaxValvePosition(_ValueSensor):
    key = "valve_position"
    data_key = "valve_position"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
