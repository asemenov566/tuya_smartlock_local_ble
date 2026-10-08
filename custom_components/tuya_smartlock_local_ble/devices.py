"""A1 device identity, entity base and BLE update coordinator."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .application.lock_commands import LockCommandWaiter
from .const import DOMAIN


class SmartlockEntity(CoordinatorEntity):
    def __init__(self, data, description):
        super().__init__(data.coordinator)
        self._device = data.device
        self._model = data.model
        self.entity_description = description
        self._attr_has_entity_name = True
        self._attr_unique_id = f"{self._device.device_id}-{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._device.address)},
            connections={(dr.CONNECTION_BLUETOOTH, self._device.address)},
            name=f"{data.model.name} {self._device.address.replace(':', '')[-6:]}",
            manufacturer=data.model.manufacturer,
            model=f"{data.model.name} ({data.model.product_id})",
            sw_version=f"{self._device.device_version} (protocol {self._device.protocol_version})",
            hw_version=self._device.hardware_version,
        )

    @property
    def available(self):
        return self.coordinator.connected


class SmartlockCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, device):
        super().__init__(hass, logging.getLogger(__name__), name=DOMAIN)
        self.connected = False
        self._unsubscribers = [
            device.register_connected_callback(self._connected),
            device.register_disconnected_callback(self._disconnected),
            device.register_callback(self._updated),
        ]

    @callback
    def _connected(self):
        self.connected = True
        self.async_update_listeners()

    @callback
    def _disconnected(self):
        self.connected = False
        self.async_update_listeners()

    @callback
    def _updated(self, updates):
        self.connected = True
        self.async_set_updated_data(None)

    def close(self):
        for unsubscribe in self._unsubscribers:
            if callable(unsubscribe):
                unsubscribe()
        self._unsubscribers.clear()


@dataclass
class SmartlockData:
    title: str
    device: object
    model: object
    manager: object
    coordinator: SmartlockCoordinator
    close: Callable[[], Awaitable[None]] | None = None
    commands: LockCommandWaiter | None = None
