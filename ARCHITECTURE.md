# Architecture / Архитектура

The package has one composition root, `custom_components/tuya_local_ble_custom/registry.py`. Model identity is defined on the model class; the UI and credential provider read the catalog. New compatible models do not require product-ID branches in HA platforms or protocol code.

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
| `models/` | Product/category, capabilities, credential validation, interpreted state, composition of commands. |
| `protocols/tuya_ble/session.py` | Tuya session handshake, ordered requests, response matching and notifications. No A1 DP mappings. |
| `protocols/tuya_ble/codec.py` | Packet encryption, CRC, fragmentation and integer encoding. No models or HA imports. |
| `protocols/tuya_ble/commands/` | Independently reusable command encoders: check-token unlock, bounded byte writes and fixed actions. Models supply point IDs. |
| `protocols/tuya_ble/dialects/` | Payload decoders. FD50 decoder accepts the model's point set and state-event mapping. |
| `transports/ble.py` | Bleak/BlueZ connection and GATT I/O. No motor/business logic. |
| `connections.py` | Own active protocol instances, initial connection, heartbeat, cancellation and close. Never issues actuator commands. |
| `devices.py`, platform files | HA adapters and entity identity. They call model methods and expose capabilities, without DP IDs. |
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

Keep connection retries in `ConnectionManager`; never replay lock/unlock/calibrate after ambiguous failure. Setup, heartbeat and discovery must not actuate the motor. A successful ACK does not prove physical movement.

## Validation

`python -m unittest discover -s tests -v` tests protocols, command composition and lifecycle without HA. `python -m unittest discover -s tests_ha -v` tests adapters with real Home Assistant installed (Python 3.14 / HA 2026.10.0 in CI). Also run hassfest and compile checks. Use synthetic credentials and simulated devices; physical acceptance is a separate owner-authorized step.

See [.skills/add-lock/SKILL.md](.skills/add-lock/SKILL.md) for the contributor workflow.
