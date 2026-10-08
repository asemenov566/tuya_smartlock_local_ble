"""Constants for Tuya BLE.

The existing HA domain and credential path are retained for a seamless upgrade.
"""

from typing import Final

DOMAIN: Final = "tuya_local_ble_custom"
CONF_KEEP_CONNECTED: Final = "keep_connected"
CONF_CRED_FILE: Final = DOMAIN + "/devices.json"
