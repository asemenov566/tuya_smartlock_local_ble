"""Device-reported lock status, battery category and BLE signal strength."""

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import SIGNAL_STRENGTH_DECIBELS_MILLIWATT
from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN
from .devices import SmartlockEntity


class LockStatus(SmartlockEntity, SensorEntity):
    """Independent of the optimistic command control and its last action."""

    def __init__(self, data):
        super().__init__(
            data,
            SensorEntityDescription(
                key="reported_lock_state",
                translation_key="reported_lock_state",
                device_class=SensorDeviceClass.ENUM,
                options=["locked", "unlocked"],
            ),
        )
        self._status = data.status
        self._attr_options = ["locked", "unlocked"]

    @property
    def available(self):
        return self._status.available

    @property
    def native_value(self):
        if self._status.locked is None:
            return None
        return "locked" if self._status.locked else "unlocked"

    @property
    def icon(self):
        return {
            "locked": "mdi:lock",
            "unlocked": "mdi:lock-open",
        }.get(self.native_value, "mdi:lock-question")

    @property
    def extra_state_attributes(self):
        return {
            "state_source": "device_report",
            "bluetooth_connected": self.coordinator.connected,
            "reported_at": self._status.reported_at,
            "cached": self._status.locked is not None and not self._status.fresh,
        }


class BatteryLevel(SmartlockEntity, SensorEntity):
    def __init__(self, data):
        super().__init__(
            data,
            SensorEntityDescription(
                key="battery_state",
                translation_key="battery_state",
                device_class=SensorDeviceClass.ENUM,
                entity_category=EntityCategory.DIAGNOSTIC,
                options=list(data.model.battery_levels),
                icon="mdi:battery",
            ),
        )
        self._attr_options = list(data.model.battery_levels)

    @property
    def native_value(self):
        return self._model.battery


class ExpectedAction(SmartlockEntity, SensorEntity):
    """Requested direction, explicitly separate from measured position."""

    def __init__(self, data):
        super().__init__(
            data,
            SensorEntityDescription(
                key="expected_action",
                translation_key="expected_action",
                device_class=SensorDeviceClass.ENUM,
                options=["opening", "closing", "idle"],
                icon="mdi:swap-horizontal",
            ),
        )
        self._actions = data.actions

    @property
    def available(self):
        return self._actions.available

    @property
    def native_value(self):
        return self._actions.expected_action

    @property
    def extra_state_attributes(self):
        return {
            "state_source": "requested_action",
            "command_pending": self._actions.pending,
            "bluetooth_connected": self.coordinator.connected,
        }


class BLESignal(SmartlockEntity, SensorEntity):
    def __init__(self, data):
        super().__init__(
            data,
            SensorEntityDescription(
                key="signal_strength",
                translation_key="signal_strength",
                device_class=SensorDeviceClass.SIGNAL_STRENGTH,
                native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
                state_class=SensorStateClass.MEASUREMENT,
                entity_category=EntityCategory.DIAGNOSTIC,
                entity_registry_enabled_default=False,
            ),
        )

    @property
    def native_value(self):
        return self._device.rssi


async def async_setup_entry(hass, entry, async_add_entities):
    data = hass.data[DOMAIN][entry.entry_id]
    entities = [BLESignal(data), LockStatus(data), ExpectedAction(data)]
    if "battery" in data.model.capabilities:
        entities.append(BatteryLevel(data))
    async_add_entities(entities)
