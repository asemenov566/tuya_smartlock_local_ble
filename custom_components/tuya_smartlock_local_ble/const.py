"""Integration identity and private credential path for Tuya Smartlock Local BLE."""

from typing import Final

DOMAIN: Final = "tuya_smartlock_local_ble"
CONF_KEEP_CONNECTED: Final = "keep_connected"
CONF_CRED_FILE: Final = DOMAIN + "/devices.json"
