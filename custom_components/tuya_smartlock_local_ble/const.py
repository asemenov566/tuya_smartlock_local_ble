"""Integration identity and private credential path for Tuya Smartlock Local BLE."""

from typing import Final

DOMAIN: Final = "tuya_smartlock_local_ble"
CONF_KEEP_CONNECTED: Final = "keep_connected"
CONF_WAIT_FOR_RECONNECT: Final = "wait_for_reconnect"
CONF_POLL_INTERVAL: Final = "poll_interval"
CONF_HOLD_TIME: Final = "hold_time"
CONF_CRED_FILE: Final = DOMAIN + "/devices.json"
