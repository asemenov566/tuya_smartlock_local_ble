"""A1 battery category and BLE signal strength; no invented battery percentage."""

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
    entities = [BLESignal(data)]
    if "battery" in data.model.capabilities:
        entities.append(BatteryLevel(data))
    async_add_entities(entities)
