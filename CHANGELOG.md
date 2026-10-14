# Changelog

## 0.5.0 — 2026-10-14

### Controls and reported status

- Replace the separate Toggle button with explicit Open and Close buttons; keep the native lock entity and its services.
- Add a Status button that connects when needed and requests current device reports without actuating the motor.
- Keep action controls available during a Bluetooth outage. Availability means a request can be accepted, not that delivery is guaranteed.
- Separate Expected action (requested Opening/Closing) from Lock status (device reports only). Neither an acknowledgement nor the selected action proves physical movement.
- Retain the last reported position between on-demand sessions, with connection, cache and report-time attributes.

### Connection modes and reliability

- Keep persistent connection mode and its optional bounded reconnect wait.
- Add on-demand sessions with status polling Off or 10–60 seconds (default 20), and command connection hold Off or 10–60 seconds (default 10).
- Release a status-only session after its report; preserve an overlapping action's session and hold. Failed on-demand commands are not replayed later.
- Harden request cancellation, contiguous BLE packet writes, query freshness and backend cleanup during unload.
- Validate V4 reports structurally, preserve report acknowledgements and reject failed command acknowledgements. Timestamped events do not overwrite current values.
- Use the current Home Assistant device-registry API for connection metadata.

### Validation and limitations

- 100 offline tests on Python 3.12 and 3.14; 13 adapter tests on Home Assistant 2026.10.0. Independent code review and regression checks completed.
- On the installed A1 Ultra, verified startup, status reads, on-demand polling and disconnect, controls while disconnected, muted sound and return to persistent mode.
- Immediate physical reversal during movement remains unresolved. Jam detection, proxy hardware compatibility and 24-hour battery/stability behavior are not verified capabilities.

### Upgrade

Update through HACS or replace `custom_components/tuya_smartlock_local_ble` with the directory from the release ZIP, then restart Home Assistant. Existing lock entity IDs remain. Automations using the removed Toggle button must migrate to Open/Close buttons or the native lock services. Back up the installed component first; rollback requires restoring that directory and restarting HA. See [INSTALL.md](INSTALL.md) / [INSTALL.ru.md](INSTALL.ru.md).
