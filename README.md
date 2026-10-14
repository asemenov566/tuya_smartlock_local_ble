# Tuya Smartlock Local BLE

[Русский](README.ru.md) · [Installation](INSTALL.md) · [Architecture](ARCHITECTURE.md)

<img src="custom_components/tuya_smartlock_local_ble/brand/icon.png" width="128" alt="Local BLE smart lock">

Local Bluetooth control for **A1 Ultra / A1 Ultra-JM**, Tuya product **hc7n0urm**, category **jtmspro**, FD50 service. Other products are not currently supported merely because they share a similar name.

- Lock and unlock from Home Assistant without a phone BLE connection.
- Persistent connection enabled by default, status-only heartbeat and bounded reconnect delays.
- Battery category and optional Bluetooth signal strength (RSSI).
- Setup through the HA interface; no YAML or prefilled credential file required.
- Composable protocol sessions, payload dialects and commands for contributors adding models.

**You must obtain your own device credentials first.** Bluetooth discovery does not retrieve keys. An existing Tuya integration does not automatically supply them. See [INSTALL.md](INSTALL.md#obtain-your-own-credentials).

## Controls and diagnostics

| Feature | What it does |
| --- | --- |
| Lock control | Keeps the native HA lock control and services, including `lock.toggle`. Its state represents the selected action. |
| Open / Close | Separate explicit command buttons; available while the integration is loaded, including during a BLE outage. They replace the former Toggle button. |
| Status | Connects if necessary and requests current device reports without moving the motor. |
| Lock status | Shows the latest decoded device position report, separately from the selected action. |
| Expected action | Shows Opening, Closing or Target reported; describes the requested action, not measured motor movement. |
| Recalibrate | Sends the model's calibration command when you press the button; it can move the motor and change its travel settings. |
| Rotation direction | Switches the motor direction for the installation orientation. |
| Sound volume | Selects **Mute** or **Normal**; other volume levels are not implemented for this model. |
| Battery | Shows the reported category: high, medium, low or depleted; no estimated percentage. |
| BLE signal | Optional RSSI sensor in dBm, disabled by default. Enable **BLE signal** in the device's disabled entities. It uses the last advertisement, not a continuous measurement of the active connection. |
| Device information | Reports firmware, BLE protocol and hardware versions. |
| Persistent connection | Periodically requests status and retries after connection failures; it does not guarantee uninterrupted radio connectivity. |

Settings can show **Unknown** until the lock reports them or acknowledges a setting change. Calibration is never triggered automatically during setup, reconnection or status checks. Firmware installation (OTA) is not implemented.

## Home Assistant device page

![A1 Ultra controls, calibration, direction, volume, battery and BLE signal in Home Assistant](docs/images/a1-ultra-home-assistant.png)

Earlier Home Assistant device page in Russian; version 0.5.0 adds separate Open, Close and Status buttons and an Expected action sensor.

## Requirements and installation

**Configure** first asks whether to **Keep connected** (enabled by default), then shows the settings for that mode. An existing configured entry loads its controls even if the lock is out of range. Available controls mean the integration can accept a request, not that Bluetooth is connected or the action will succeed.

With **Keep connected** enabled, the integration maintains the session, queries status every 30 seconds and reconnects after a short pause, with increasing delays after failures. Optionally enable **Wait for reconnection before a command (up to 10 seconds)**, off by default. A lock/unlock request then waits at most 10 seconds from invocation to start transmission over an authenticated session; expired requests are discarded. Without this option, an offline lock/unlock request fails immediately. The Status button can request a connection directly in either mode.

With **Keep connected** disabled, choose a **Status polling interval** of Off or 10, 20, 30, 40, 50 or 60 seconds (default 20), and **Connection hold after a command** from the same choices (default 10). A polling-only session requests status, waits for a valid passive report and disconnects; it does not wait out a command hold unless a user action overlaps. Polling is skipped during an active action or its hold. The hold starts when the command operation finishes, not when physical movement is confirmed. Off releases the idle connection immediately; late movement reports may therefore require the next poll or a Status press.

In on-demand mode, each action makes its own bounded connection attempt. A failed request is not queued for a later poll or reconnect. A new lock/unlock action supersedes local waiting for the previous one. Already-started packet writes finish before the replacement is sent. Missing acknowledgement never causes an automatic motor-command replay in either mode. Unloading or restarting cancels pending work; nothing is persisted. `bluetooth_connected` and `command_pending` expose connection and execution status.

Current hardware testing still shows brief disconnects roughly every two minutes, followed by automatic reconnection. The cause remains under investigation; persistent connection mode does not yet provide uninterrupted availability.

Home Assistant **2026.10.0 or newer**, a working connectable Bluetooth adapter/proxy in HA, a powered lock in range, HACS for the recommended installation. The tested hardware used local BlueZ Bluetooth; proxies have not been hardware-verified here.

Add `https://github.com/asemenov566/tuya_smartlock_local_ble` to HACS as a custom **Integration** repository. This is not an entry in the default HACS catalog. Follow the [complete installation guide](INSTALL.md) through the first connection.

## Status and limitations

Lock/unlock, BLE communication and the signal sensor have been observed on real hardware during development. Direction, volume and calibration use the product's identified DP mapping and have automated command tests; comprehensive hardware testing of every setting is still pending.

**Lock control** changes its chosen action immediately on invocation so the opposite action remains selectable. Device position reports also synchronize the control, while repeated reports of the starting position do not undo an outstanding action. If the control direction is unknown, use explicit Open or Close rather than `lock.toggle`. Sending an opposite command does **not** guarantee immediate motor reversal during movement; that behavior remains unresolved and is not a verified capability of this release.

The separate **Lock status** sensor changes only on decoded device lock-status reports (DP47 for A1 Ultra). A new command clears it until a fresh report arrives; ACKs and unrelated battery/volume updates cannot set it. In persistent mode a disconnect also clears it. In on-demand mode the last reported value is retained while disconnected, with `cached: true`, `reported_at` (the report's local receipt time) and `bluetooth_connected: false`. This cache lasts only for the loaded session and is not a live reading of an offline lock.

**Expected action** uses `state_source: requested_action`; Opening and Closing describe the selected request, including connection waiting. Target reported means a position report matched that request. These labels do not detect actual movement or a jam. Reverse direction is handled by the lock firmware; it does not invert the logical Open/Close actions or the meaning of DP47 in HA. The Status button requests the device snapshot, but only values actually reported by the device are refreshed.

Current position and settings use ordinary device reports. Timestamped event packets are acknowledged but excluded from current values because their history and clock semantics are not verified. Such a packet alone cannot complete a status refresh or confirm a new position.

Reported position is not an independent door-contact or obstruction sensor. Jam detection is not implemented; a controller report cannot prove the mechanism reached a physically correct endpoint. Battery reports are categories, not percentages. Camera/cloud-only functions are not implemented. Continuous connection may increase battery use; 24-hour stability and battery endurance have not been measured.

## Local operation

After provisioning, the component communicates over BLE and makes no Tuya cloud calls. SmartLife/Tuya is needed to provision the lock and obtain credentials. Factory reset or rebinding may change them. Do not delete the lock from SmartLife as a way to disable cloud access: rebinding behavior has not been verified.

The HA domain and package directory are **`tuya_smartlock_local_ble`**, matching this repository. Other Tuya integrations can be installed alongside it, but only one BLE integration should actively connect to a given physical lock.

## Development

See [ARCHITECTURE.md](ARCHITECTURE.md) and the repository [add-lock skill](.skills/add-lock/SKILL.md). Tests use synthetic values and fake devices. Never submit device keys, HA storage files or raw diagnostics in issues or pull requests.

Licensed under [MIT](LICENSE).

The MIT license allows use, modification and redistribution, including commercial use, with the copyright and permission notices preserved. The inherited notice and the 2026 contribution notice are both included in LICENSE.

### Updating existing automations

The separate Toggle button is removed during entity setup. Automations referencing it must use the new Open/Close buttons or the existing lock entity's services. The native lock entity remains; `lock.toggle` inverts its selected action, independently of the reported-status sensor. Recalibration remains an explicit action and never runs as part of a status query.
