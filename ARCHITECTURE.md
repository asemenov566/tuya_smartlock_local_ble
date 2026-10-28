# Architecture / Архитектура

The package has one composition root, `custom_components/tuya_smartlock_local_ble/registry.py`. Model identity is defined on the model class; the UI and credential provider read the catalog. New compatible models do not require product-ID branches in HA platforms or protocol code.

```text
HA platforms / config flow
           ↓
registry.py → models/<model>.py → reusable commands + payload dialect
           ↓                          ↓
connections.py → protocols/<protocol>/session.py
                                    ↓
                         codec.py + transports/ble.py
```

| Layer | Responsibility |
| --- | --- |
| `domain/` | Credential, state and model/session contracts; no HA imports. |
| `application/lock_commands.py` | Optional single-command waiting, expiry, cancellation and admission; no HA, model, DP or BLE imports. |
| `application/session_policy.py` | Connection leases, on-demand status polling and command hold; no HA imports or model DP mappings. |
| `application/lock_actions.py`, `lock_status.py` | Selected action and expected action, separately from fresh device-reported position. |
| `models/` | Product/category, capabilities, credential validation, interpreted state, composition of commands. |
| `protocols/tuya_ble/session.py` | Tuya session handshake, ordered requests, response matching and notifications. No A1 DP mappings. |
| `protocols/tuya_ble/codec.py` | Packet encryption, CRC, fragmentation and integer encoding. No models or HA imports. |
| `protocols/tuya_ble/commands/` | Independently reusable command encoders: check-token unlock, bounded byte writes and fixed actions. Models supply point IDs. |
| `protocols/tuya_ble/dialects/` | Payload decoders. FD50 decoder accepts the model's point set and state-event mapping. |
| `protocols/tuya_ble/reports.py` | Validates V4 framing, timestamps, TLVs and scalar sizes; constructs report acknowledgements without interpreting model state. |
| `transports/ble.py` | Bleak/BlueZ connection and GATT I/O. No motor/business logic. |
| `connections.py` | Own active protocol instances, their session policies, persistent heartbeat, cancellation and close. Never issues actuator commands. |
| `devices.py`, platform files | HA adapters and entity identity. Route actions through application services and expose model capabilities without DP IDs. |
| `registry.py` | The only model/protocol registration point. Duplicate product registrations fail explicitly. |

A codec is not a collection of every protocol. A model composes one session implementation and the command/dialect implementations it needs. A compatible model can reuse the entire A1 profile; a partially compatible model replaces a command object or decoder. A different connection protocol implements the session contract and is registered independently.

## Inheritance / Наследование

If evidence confirms the complete A1 wire behavior and only the product identity differs, add `models/example_lock.py`:

```python
from .a1_ultra import A1UltraModel


class ExampleLock(A1UltraModel):
    product_id = "replace_with_verified_product_id"
    name = "Example lock"
    # category, protocol, credentials, commands and capabilities are inherited.
```

Then, in **one place**, `registry.py`, import `ExampleLock` and call `register_model(ExampleLock)`. That is the entire runtime registration. No changes to `keyman.py`, the flow or existing HA platforms are needed. An unimported file alone is not loaded. Product IDs are not aliases for each other, and matching `jtmspro` alone does not prove compatibility.

For a single changed setting, compose a different command after `super().__init__` and override the corresponding state projection if its point ID differs. For example, changing only the command while leaving the old state decoder would be incomplete. For a different unlock format, replace `self.unlock_command` with an object exposing `async execute(protocol)`; preserve all other command objects. Do not subclass the session just to change a model DP.

Наследуйте A1 только при подтверждённой совместимости. Если общий лишь транспорт, создайте собственный `LockModel`, используя существующий протокол и нужные команды. Не копируйте целиком профиль A1 ради одной общей функции. Класс модели задаёт `credential_fields`, `validate_credentials`, `capabilities` и свойства состояния. Не объявляйте возможности, которых устройство не поддерживает.

## Adding a new protocol

Implement the `LockProtocol` contract, metadata (address, device/version identity, signal), received-point storage and publish/subscription methods used by HA adapters. Register it in `registry.py` and reference its `protocol_id` from a model. Provide `discovery_services`; the flow derives its filter from protocol registrations. HA's static `manifest.json` Bluetooth matcher must also declare a new service UUID; this is a packaging declaration, not another model registry. Existing FD50 models need no manifest change.

Keep connection lifecycle in `ConnectionManager` and `SessionPolicy`; never replay lock/unlock/calibrate after ambiguous failure. Implement reusable `connect`, `query_status` and `disconnect` separately from terminal `stop`. A status query must wait for a validated report, not only its request ACK. Setup, heartbeat and discovery must not actuate the motor. A successful ACK does not prove physical movement.

## Session lifecycle

`ConnectionManager` initializes credentials and local protocol state without requiring an immediate live connection. For an existing configured entry, the HA adapter can start from a BLE address placeholder; advertisements later refresh the transport device. Entities therefore load during a radio outage. First-time credential validation still requires a successful connection.

In persistent mode, the manager owns a heartbeat that reads status every 30 seconds. A disconnect wakes it after a one-second BlueZ release interval; failed reconnection attempts back off from 2 seconds to at most 120 seconds. `SessionPolicy` owns connection admission and leases. The two-step options flow shows the optional ten-second command wait only for this mode.

In on-demand mode, `SessionPolicy` owns polling (Off or 10–60 seconds in ten-second increments, default 20) and idle connection release after an action (same choices, default 10). Polling is sequential and skipped during action leases or their hold. A status-only lease releases immediately after its query unless an overlapping action still owns the connection or hold. The hold begins when the admitted operation finishes; it is not a motor-completion timer. A gate, active-user count and cancellable idle task prevent polling from closing a concurrent action's session.

Each on-demand action makes one bounded connection attempt; no request is retained for a future periodic reconnect. `query_status` subscribes before sending the query and waits up to ten seconds for a validated passive non-timestamped V4 report. It does not claim that every model field was returned; absent fields are not invented. Polling, status refresh and connection setup never send motor commands. Unload cancels owned operations, pollers and idle tasks before terminal protocol shutdown.

The session serializes outgoing request/ACK transactions separately from GATT writes. Packet fragments stay contiguous, but waiting for an ACK does not block replies to incoming time requests or datapoint reports. Notification replies belong to the client that received them; they are cancelled on disconnect/unload and cannot leak into a replacement session. Pending requests fail immediately on a disconnect, without replaying motor commands. Action-entity availability describes a loaded application service, independently of Bluetooth availability; each invocation still follows its mode's admission rules.

V4 reports are parsed structurally from their seven-byte header and complete TLVs, including supported timestamp forms. The parser rejects truncated frames and invalid scalar types/lengths; it never searches for state-looking byte sequences inside arbitrary raw values. A valid report is acknowledged with its header plus status. Command ACKs use the version-zero six-byte format and its explicit result byte; malformed or negative replies cannot become silent success.

FD50 projects model-selected points only from ordinary non-timestamped reports. Timestamped V4 packets are validated and acknowledged but never update current DP47 position or settings, nor satisfy a status query. Their history semantics and device-clock interpretation are not verified; treating receipt as a fresh measurement could replace current state with an old event. A1 current-position reports have been observed in ordinary DP47 packets. This conservative boundary deliberately excludes timestamped-only updates until their freshness can be established.

Disconnected clients are explicitly closed even when `is_connected` is false, so backend subscriptions and D-Bus resources can be released. Reconnection waits for bounded cleanup of the previous client. Notification callbacks are bound to their originating client and reject events from retired sessions. Unloading waits for owned cleanup tasks.

## Validation

### Optional command waiting

The HA lifecycle adapter creates `LockCommandWaiter` only when both persistent connection and command waiting are enabled. Lock control and the explicit Open/Close buttons invoke `LockActions`, which uses the waiter, `SessionPolicy` and reported-status service around the unchanged model operation. The model and command encoders know nothing about queues, reconnect scheduling, HA options or button intent.

The waiter waits for `command_ready` (authenticated session) and permits one pending/executing operation. `LockActions` cancels and drains a superseded operation before admitting the replacement. The waiter owns a ten-second send deadline measured from user invocation, subscriptions and cancellation on unload. Expiry discards only that request, allowing a later manual request with a fresh deadline. No command is persisted. Without the waiter, a disconnected persistent-mode motor command fails immediately; on-demand commands instead make their own connection attempt. Status refresh may explicitly connect in either mode. Calibration and setting changes use the session policy without the optional motor-command waiter.

`domain/command_context.py` carries a task-local absolute send deadline through unchanged domain calls. It is scoped with a ContextVar token and reset in a finally block, so heartbeat, other requests and models do not acquire global mutable policy. The protocol adapter honors that deadline while acquiring request/write locks, rechecks the authenticated client and expiry immediately before writing, then disables only the send deadline. Normal ACK timeout still applies. Only `CommandNotReady`, which guarantees that no bytes were submitted, permits waiting again. Transport failure or missing ACK after a write is never retried. Compatible protocol implementations must honor this execution-context contract before enabling waiting.

Run `python scripts/run_tests.py protocol` for protocol, command and lifecycle tests, `python scripts/run_tests.py ha` for adapters with Home Assistant installed (Python 3.14 / HA 2026.10.0 in CI), and `python scripts/run_tests.py packaging` for release checks. The runner uses a temporary profile and synthetic devices, blocks external connections and real Bluetooth access, and permits SQLite only in memory. It does not replace reviewing test fixtures and mocks. Ordinary unittest discovery remains supported, but the runner is the recommended isolated entry point. Also run hassfest and compile checks; physical acceptance is a separate owner-authorized step.

### Release contents / Состав поставки

`python scripts/build_release.py` creates an installation ZIP and SHA-256 file under ignored `dist/`. It reads only the explicit runtime file list in [scripts/build_release.py](scripts/build_release.py), rejects links and verifies archived bytes. Add each new runtime module or translation to that list after reviewing its contents. An existing output is never overwritten: move or remove only a disposable previous build before rebuilding. Review the source diff and archive before publishing; a file allowlist cannot detect secrets added inside an allowed source file.

The installation archive contains the component code, translations, manifest, license and icon. Tests, screenshots, documentation, profiles, reports, caches, HA storage and local credential files are excluded. Source documentation and synthetic tests remain versioned. The README screenshot is a documentation asset and is intentionally not installed into HA.

Сборщик включает только явно перечисленные файлы компонента; новый модуль или перевод нужно добавить в список после проверки. Ключи, `devices.json`, `.storage`, базы, профили, логи и отчёты в поставку не входят. Для примеров используйте искусственные данные и домены `example.com` / `example.test`; пути вычисляйте от проекта либо получайте из окружения. Проверки выполняйте через `scripts/run_tests.py` с временным профилем. Список файлов защищает состав ZIP, но не заменяет проверку содержимого исходников перед публикацией.

See [.skills/add-lock/SKILL.md](.skills/add-lock/SKILL.md) for the contributor workflow.

### Reported status versus control intent

`application/lock_status.py` owns report freshness and invalidation, independently of HA, model encoders and BLE payload details. An admitted motor command invalidates the reported value before invoking the model operation. A command ACK cannot set position. Persistent-mode disconnects also invalidate it; on-demand disconnects retain the last report for the current loaded entry. The sensor publishes `state_source: device_report`, `reported_at` (local receipt time), `cached` and `bluetooth_connected`. Unrelated publishes cannot resurrect an invalidated token; a fresh position report arriving before the command ACK is preserved. No cache is persisted across unload. Model interpretation remains in `models/`; subscriptions are closed with the config entry.

`application/lock_actions.py` owns the shared immediate action for explicit lock/unlock, native `lock.toggle` and Open/Close buttons. Generation checks keep superseded completions from overwriting newer intent. Position reports can synchronize idle control; a repeated starting-position report must not undo an outstanding action. Replacing an invocation cancels local connection/ACK waiting; already-started GATT frames finish under the operation lock with a bounded write timeout before a replacement can send. No motor write is replayed. Unload cancels owned work and removes report subscriptions. HA action entities share availability and exception translation; models remain unaware of command intent and buttons.

The separate expected-action sensor exposes Opening/Closing from intent, with `state_source: requested_action`, and Target reported when a received position matches the request. This is not a physical motion or jam detector; an ACK is not motion evidence. Reverse direction is a firmware setting: logical Open/Close and interpretation of the model's DP47 are not swapped by application policy. Immediate physical reversal while the motor is moving remains unresolved and is not a promised behavior of release 0.5.0.

During button setup, only the former integration-owned Toggle button registry entry is removed. The native lock entity and its services keep their identity. Automations targeting the removed button require migration to explicit buttons or lock services. Open, Close and Status remain available while the application services are loaded; other entities follow their connection mode and service availability policies.
