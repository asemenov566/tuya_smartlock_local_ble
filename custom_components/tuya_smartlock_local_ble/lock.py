"""Lock HA adapter; state is command-derived unless reported by the model."""

from homeassistant.components.lock import LockEntity, LockEntityDescription
from homeassistant.core import callback

from .const import DOMAIN
from .devices import SmartlockEntity


class LockControl(SmartlockEntity, LockEntity):
    _attr_assumed_state = True

    def __init__(self, data):
        super().__init__(
            data,
            LockEntityDescription(key="manual_lock", translation_key="manual_lock"),
        )
        self._attr_is_locked = None
        self._last_report = None

    async def _command(self, locked):
        if locked:
            await self._model.lock()
        else:
            await self._model.unlock()
        self._attr_is_locked = locked
        self.async_write_ha_state()

    async def async_lock(self, **kwargs):
        await self._command(True)

    async def async_unlock(self, **kwargs):
        await self._command(False)

    @callback
    def _handle_coordinator_update(self):
        report = self._model.lock_report
        if report is not None and report[0] != self._last_report:
            self._last_report, self._attr_is_locked = report
        self.async_write_ha_state()


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([LockControl(hass.data[DOMAIN][entry.entry_id])])
