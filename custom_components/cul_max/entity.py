"""Shared entity helpers."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .gateway import CulMaxGateway, MaxDevice


class CulMaxEntity(Entity):
    """Base entity belonging to a dynamically discovered MAX! device."""

    _attr_has_entity_name = True

    def __init__(self, gateway: CulMaxGateway, device: MaxDevice) -> None:
        self.gateway = gateway
        self.device = device
        self._attr_unique_id = f"{gateway.entry.entry_id}_{device.address}_{self.key}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={("cul_max", f"{self.gateway.entry.entry_id}_{self.device.address}")},
            name=self.device.serial or f"MAX! {self.device.address.upper()}",
            manufacturer="eQ-3",
            model=self.device.device_type,
            sw_version=self.device.firmware,
            via_device=("cul_max", self.gateway.entry.entry_id),
        )
