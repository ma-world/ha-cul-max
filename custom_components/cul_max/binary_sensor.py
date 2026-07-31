"""Binary sensors for MAX! shutter contacts."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_DEVICE_UPDATED, SIGNAL_NEW_DEVICE
from .entity import CulMaxEntity
from .gateway import CulMaxGateway, MaxDevice


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    gateway: CulMaxGateway = hass.data[DOMAIN][entry.entry_id]
    known: set[str] = set()

    def add(address: str) -> None:
        device = gateway.devices[address]
        if address not in known and device.device_type in {"ShutterContact", "virtualShutterContact"}:
            known.add(address)
            hass.add_job(async_add_entities, [CulMaxWindowContact(gateway, device)])

    for address in gateway.devices:
        add(address)
    entry.async_on_unload(async_dispatcher_connect(hass, SIGNAL_NEW_DEVICE, lambda eid, address: add(address) if eid == entry.entry_id else None))


class CulMaxWindowContact(CulMaxEntity, BinarySensorEntity):
    """Represent a MAX! window contact."""

    key = "window"
    _attr_device_class = BinarySensorDeviceClass.WINDOW

    @property
    def is_on(self) -> bool | None:
        return self.device.data.get("window_open")

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(
            self.hass, SIGNAL_DEVICE_UPDATED,
            lambda eid, address: self.async_write_ha_state() if eid == self.gateway.entry.entry_id and address == self.device.address else None,
        ))
