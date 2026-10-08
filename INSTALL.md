# Installation: GitHub to the first connection

[Русская инструкция](INSTALL.ru.md)

## Before installation

1. Confirm Home Assistant is 2026.10.0 or newer and its Bluetooth integration has a working adapter with connection support.
2. Confirm your lock is A1 Ultra product `hc7n0urm`, category `jtmspro`. Names on seller listings are insufficient.
3. Pair the lock to your own SmartLife account and confirm it works. Do not factory-reset it for this installation.
4. Obtain the four device-specific values below before proceeding. No usable credentials are shipped in this repository.

## Obtain your own credentials

The component does not log into Tuya and does not import another HA integration's secrets. Get these values once from **your own device**:

| HA field | Where to obtain it |
| --- | --- |
| Device ID | The device list in the linked Tuya cloud project; the device details API returns `id`. |
| UUID | The same device details response, field `uuid`. This is NOT the Bluetooth service UUID. |
| Local key | The same response, field `local_key`. This is NOT an API client secret. |
| BLE unlock check | Device status entry with `code: ble_unlock_check`; copy its entire Base64 `value` without quotes. |

1. Sign in at [Tuya Developer Platform](https://iot.tuya.com/). In **Cloud → Development**, create or open a Smart Home project with the data center matching your SmartLife account.
2. In the project's **Devices → Link Tuya App Account**, link that account using the QR code and SmartLife's scanner. Check that the lock appears under this project.
3. Open **API Explorer** for this project. Request device information for its Device ID. The [documented device-information API](https://developer.tuya.com/en/docs/cloud/d00d20c097?id=Kag2xtiyewd3r) is `GET /v1.0/iot-03/devices/{device_id}` and returns UUID/local key. Portal labels and available services vary; **Query Device Details** or **Query Device Details in Bulk** may be the available equivalent. Copy actual, unmasked fields for your device.
4. Request device status (`GET /v1.0/devices/{device_id}/status`) and locate `ble_unlock_check`. If the details response includes `status`, it may already be there. The schema/type `Raw` is not the actual value.
5. As an alternative for **BLE unlock check only**, an existing Tuya device diagnostic in HA may contain this status value: Settings → Devices & services → Tuya → the lock → Download diagnostics. Availability and redaction depend on the integration. Diagnostics are not a guaranteed source of UUID/local key; do not publish the file.
6. If Tuya returns an expired subscription, permission error or masks the required fields, stop here and resolve access in your Tuya project. This integration cannot bypass account restrictions or derive missing keys from Bluetooth advertisements. A free plan or a universal zero-setup flow is not promised.

Keep these values private. You do not enter your SmartLife password or Tuya API access secret into this integration. The lock does not need an IP address for BLE.

## Install through HACS

1. Open HACS in Home Assistant. In its menu choose **Custom repositories**.
2. Paste `https://github.com/asemenov566/tuya_smartlock_local_ble` and choose type **Integration**. Add it.
3. Find **Tuya Smartlock Local BLE**, open it and choose **Download**. Without releases, HACS uses the default branch.
4. Restart Home Assistant. Open a **new browser tab at your HA root address**, wait for the dashboard, then open Settings → Devices & services.
5. If you see a discovered FD50 device, choose **Add/Configure**. Otherwise choose **Add integration → Tuya Smartlock Local BLE**. Wake the lock and retry if it is not listed.

## Add the lock and connect

1. Disconnect SmartLife from the lock; turning off phone Bluetooth is a simple way. Disable other BLE integrations controlling this same lock.
2. Select the nearby device by its name and Bluetooth address. FD50 discovery alone does not confirm the model.
3. If a model selector appears, select **A1 Ultra**. Paste your UUID, local key, device ID and BLE unlock check into the form.
4. Submit. The integration opens a BLE session and requests status; **it does not lock, unlock or calibrate** during this check. Incorrect credentials/range cause a setup error instead of a successful entry.
5. After success, the device page contains lock control, battery and configuration controls. Persistent connection is enabled by default. Settings can remain unknown until a report or a successful write; the component does not invent initial values.
6. With the lock in a safe position, manually try lock/unlock and confirm physical movement with phone Bluetooth off. Only test direction/calibration intentionally; calibration changes the travel setup.

Credentials are stored locally in HA's config entry (`.storage`, managed by HA). No manual file is required. Secure HA backups, which may contain these credentials.

## Manual ZIP alternative

From GitHub choose **Code → Download ZIP**. Extract it on your computer. Copy only `custom_components/tuya_smartlock_local_ble` into the HA configuration directory's `custom_components` folder. The final path is `/config/custom_components/tuya_smartlock_local_ble/manifest.json`; do not nest the repository folder inside it. Restart HA and follow the same setup steps above. Git is not needed on the HA server. Updates to a manual installation are also manual.

## Troubleshooting and removal

- **No integration in the list:** verify the directory path, restart HA, reload the browser and inspect HA logs.
- **No lock found:** verify HA Bluetooth, range and lock power; wake it; disconnect the phone/other BLE clients. HACS itself does not scan Bluetooth.
- **Cannot connect:** recheck all four fields belong to the selected lock. A reset/rebind may invalidate previous keys. Retry close to the adapter.
- **Lock status differs from the mechanism:** it is an assumed state supplemented by reports. Check actual movement; do not use it as a door-closed detector.
- **Remove:** delete this lock's integration entry in HA, then remove the package in HACS and restart.
- **Rollback:** keep a backup of the installed component and credentials before an update. Restore the previous component version and matching settings, then restart. Do not edit `.storage` while HA is running.

## Coexistence with Tuya Local BLE

This project's domain and package directory are `tuya_smartlock_local_ble`. Components with a different domain can be installed alongside it. Configure a physical lock in only one active BLE integration; otherwise clients may compete for its connection. Shared dependency compatibility must still be checked when either package changes its requirements.

HAOS is a supported deployment target by design: dependencies run inside Home Assistant, not the host OS. Use current HAOS, HA 2026.10.0+ and a supported Bluetooth adapter. This version has not yet been physically tested on HAOS.

## Waiting for commands during reconnection

Since 0.4.0: **Settings → Devices & services → Tuya Smartlock Local BLE → Configure**. Keep **Keep connected** enabled and enable **Wait for reconnection before a command (up to 10 seconds)**. Saving reloads the integration entry. This option defaults to off; disabling restores previous availability and cancels waiting. See README.md for the execution limits.
