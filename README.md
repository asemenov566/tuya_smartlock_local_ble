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
| Lock / unlock | Operates the lock through the HA interface, scripts and automations over local BLE. |
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

Home Assistant device page in Russian.

## Requirements and installation

A disconnect triggers reconnection after a short pause, with increasing delays after failures. By default, entities become unavailable while disconnected.

In **Configure**, optionally enable **Wait for reconnection before a command (up to 10 seconds)**. It defaults to off and requires **Keep connected**. During the first 10 seconds of an outage, the lock entity still accepts lock/unlock: one accepted command waits at most 10 seconds from invocation for an authenticated session, then sends once. Expired commands are discarded. Additional commands while one is pending or executing fail instead of accumulating. Disabling the option, unloading or restarting cancels pending work; nothing is persisted.

Once transmission starts, missing acknowledgement never triggers a motor-command replay. The deadline limits waiting to **start transmission**; acknowledgement can take longer. Calibration, direction and volume are unaffected. Lock state is unknown during waiting/disconnection; `bluetooth_connected` and `command_pending` expose connection and execution status. Other entities retain their normal BLE availability.

Current hardware testing still shows brief disconnects roughly every two minutes, followed by automatic reconnection. The cause remains under investigation; persistent connection mode does not yet provide uninterrupted availability.

Home Assistant **2026.10.0 or newer**, a working connectable Bluetooth adapter/proxy in HA, a powered lock in range, HACS for the recommended installation. The tested hardware used local BlueZ Bluetooth; proxies have not been hardware-verified here.

Add `https://github.com/asemenov566/tuya_smartlock_local_ble` to HACS as a custom **Integration** repository. This is not an entry in the default HACS catalog. Follow the [complete installation guide](INSTALL.md) through the first connection.

## Status and limitations

Lock/unlock, BLE communication and the signal sensor have been observed on real hardware during development. Direction, volume and calibration use the product's identified DP mapping and have automated command tests; comprehensive hardware testing of every setting is still pending.

Lock state is assumed from acknowledged commands, supplemented by BLE reports. It is not a certified door-position sensor. Battery reports are categories, not percentages. Camera/cloud-only functions are not implemented. Continuous connection may increase battery use; 24-hour stability and battery endurance have not been measured.

## Local operation

After provisioning, the component communicates over BLE and makes no Tuya cloud calls. SmartLife/Tuya is needed to provision the lock and obtain credentials. Factory reset or rebinding may change them. Do not delete the lock from SmartLife as a way to disable cloud access: rebinding behavior has not been verified.

The HA domain and package directory are **`tuya_smartlock_local_ble`**, matching this repository. Other Tuya integrations can be installed alongside it, but only one BLE integration should actively connect to a given physical lock.

## Development

See [ARCHITECTURE.md](ARCHITECTURE.md) and the repository [add-lock skill](.skills/add-lock/SKILL.md). Tests use synthetic values and fake devices. Never submit device keys, HA storage files or raw diagnostics in issues or pull requests.

Licensed under [MIT](LICENSE).

The MIT license allows use, modification and redistribution, including commercial use, with the copyright and permission notices preserved. The inherited notice and the 2026 contribution notice are both included in LICENSE.
