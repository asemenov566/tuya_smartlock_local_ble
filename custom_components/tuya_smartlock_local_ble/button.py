"""Explicit recalibration adapter; never invoked by setup or heartbeat."""

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN
from .devices import SmartlockActionEntity


class LockActionButton(SmartlockActionEntity, ButtonEntity):
    def __init__(self, data, locked):
        self._locked = locked
        key = "close_lock" if locked else "open_lock"
        super().__init__(
            data,
            ButtonEntityDescription(
                key=key,
                translation_key=key,
                icon="mdi:lock" if locked else "mdi:lock-open",
            ),
        )

    async def async_press(self):
        await self._execute_action(lambda: self._actions.set_locked(self._locked))


class RefreshStatusButton(SmartlockActionEntity, ButtonEntity):
    def __init__(self, data):
        super().__init__(
            data,
            ButtonEntityDescription(
                key="refresh_status",
                translation_key="refresh_status",
                icon="mdi:refresh",
            ),
        )

    async def async_press(self):
        await self._execute_action(self._session_policy.refresh)


class CalibrateButton(SmartlockActionEntity, ButtonEntity):
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
        await self._execute_setting(self._model.calibrate)


async def async_setup_entry(hass, entry, async_add_entities):
    data = hass.data[DOMAIN][entry.entry_id]
    # Remove only the obsolete integration-owned button, preserving other IDs.
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    old_id = registry.async_get_entity_id(
        "button", DOMAIN, f"{data.device.device_id}-toggle_lock"
    )
    if old_id:
        registry.async_remove(old_id)
    entities = [
        LockActionButton(data, False),
        LockActionButton(data, True),
        RefreshStatusButton(data),
    ]
    if "calibrate" in data.model.capabilities:
        entities.append(CalibrateButton(data))
    async_add_entities(entities)
