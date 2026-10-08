"""Explicit recalibration adapter; never invoked by setup or heartbeat."""

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN
from .devices import SmartlockActionEntity, SmartlockEntity


class ToggleLockButton(SmartlockActionEntity, ButtonEntity):
    def __init__(self, data):
        super().__init__(
            data,
            ButtonEntityDescription(
                key="toggle_lock",
                translation_key="toggle_lock",
                icon="mdi:swap-horizontal",
            ),
        )

    async def async_press(self):
        await self._execute_action(self._actions.toggle)


class CalibrateButton(SmartlockEntity, ButtonEntity):
    def __init__(self, data):
        super().__init__(
            data,
            ButtonEntityDescription(
                key="calibrate",
                translation_key="calibrate",
                entity_category=EntityCategory.CONFIG,
                icon="mdi:target",
            ),
        )

    async def async_press(self):
        await self._model.calibrate()


async def async_setup_entry(hass, entry, async_add_entities):
    data = hass.data[DOMAIN][entry.entry_id]
    entities = [ToggleLockButton(data)]
    if "calibrate" in data.model.capabilities:
        entities.append(CalibrateButton(data))
    async_add_entities(entities)
