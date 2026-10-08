"""Home Assistant lifecycle adapter for the lock domain."""

from __future__ import annotations

import logging
import time

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth.match import ADDRESS, BluetoothCallbackMatcher
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady

from .application.lock_actions import LockActions
from .application.lock_commands import LockCommandWaiter
from .application.lock_status import ReportedLockStatus
from .connections import ConnectionManager
from .const import CONF_KEEP_CONNECTED, CONF_WAIT_FOR_RECONNECT, DOMAIN
from .devices import SmartlockCoordinator, SmartlockData
from .keyman import LocalCredentialProvider
from .registry import create_connection

PLATFORMS = [
    Platform.BUTTON,
    Platform.SENSOR,
    Platform.SELECT,
    Platform.SWITCH,
    Platform.LOCK,
]
_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    address = entry.data[CONF_ADDRESS]
    ble_device = bluetooth.async_ble_device_from_address(hass, address, True)
    if ble_device is None:
        raise ConfigEntryNotReady("Lock is outside Bluetooth range")
    provider = LocalCredentialProvider(hass, {**entry.options, **entry.data})
    credentials = await provider.get_device_credentials(address)
    if credentials is None:
        raise ConfigEntryNotReady("Lock credentials are missing")
    try:
        device, model = create_connection(credentials, provider, ble_device)
    except ValueError as exc:
        raise ConfigEntryNotReady("Unsupported lock model") from exc
    coordinator = SmartlockCoordinator(hass, device)
    store = hass.data.setdefault(DOMAIN, {})
    connections = store.setdefault("_connections", ConnectionManager())
    persistent = entry.options.get(CONF_KEEP_CONNECTED, True)
    try:
        await connections.start(entry.entry_id, device, persistent)
    except Exception as exc:
        coordinator.close()
        raise ConfigEntryNotReady("Could not establish the BLE session") from exc
    except BaseException:
        coordinator.close()
        raise

    commands = (
        LockCommandWaiter(device, coordinator.async_update_listeners)
        if persistent and entry.options.get(CONF_WAIT_FOR_RECONNECT, False)
        else None
    )
    status = ReportedLockStatus(device, model, coordinator.async_update_listeners)
    actions = LockActions(model, status, commands, coordinator.async_update_listeners)

    async def close():
        try:
            if commands is not None:
                await commands.close()
        finally:
            try:
                await connections.close(entry.entry_id)
            finally:
                status.close()
                coordinator.close()

    data = SmartlockData(
        entry.title, device, model, provider, coordinator, close, commands, status, actions
    )
    store[entry.entry_id] = data
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        store.pop(entry.entry_id, None)
        await close()
        raise

    last_refresh = 0.0
    refresh_task = None

    async def refresh():
        try:
            await device.refresh_session()
        except Exception:
            _LOGGER.debug("Advertisement-triggered status refresh failed")

    @callback
    def advertised(info, change):
        nonlocal last_refresh, refresh_task
        device.set_ble_device_and_advertisement_data(info.device, info.advertisement)
        now = time.monotonic()
        if (
            not persistent
            and now - last_refresh >= 300
            and (refresh_task is None or refresh_task.done())
        ):
            last_refresh = now
            refresh_task = entry.async_create_background_task(
                hass, refresh(), "lock-status-refresh"
            )

    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass,
            advertised,
            BluetoothCallbackMatcher({ADDRESS: address}),
            bluetooth.BluetoothScanningMode.ACTIVE,
        )
    )
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    async def stopped(event):
        await close()

    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stopped))
    return True


async def _async_update_listener(hass, entry):
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass, entry):
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        data = hass.data[DOMAIN].pop(entry.entry_id)
        await data.close()
        return True
    return False
