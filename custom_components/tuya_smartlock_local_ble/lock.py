"""Lock HA adapter; state is command-derived unless reported by the model."""

from homeassistant.components.lock import LockEntity, LockEntityDescription
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN
from .devices import SmartlockEntity
from .domain.command_context import CommandBusy, CommandClosed


class LockControl(SmartlockEntity, LockEntity):
    _attr_assumed_state = True

    def __init__(self, data):
        super().__init__(
            data,
            LockEntityDescription(key="manual_lock", translation_key="manual_lock"),
        )
        self._attr_is_locked = None
        self._last_report = None
        self._commands = data.commands

    @property
    def available(self):
        if self._commands is not None:
            return self._commands.available
        return super().available

    @property
    def is_locked(self):
        if self._commands is not None and (
            not self.coordinator.connected or self._commands.pending
        ):
            return None
        return self._attr_is_locked

    @property
    def extra_state_attributes(self):
        return {
            "bluetooth_connected": self.coordinator.connected,
            "command_pending": self._commands.pending if self._commands else False,
        }

    async def _command(self, locked):
        action = self._model.lock if locked else self._model.unlock
        try:
            if self._commands is None:
                await action()
            else:
                await self._commands.execute(action)
        except CommandBusy as exc:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="command_busy"
            ) from exc
        except (TimeoutError, CommandClosed) as exc:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="command_failed"
            ) from exc
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
