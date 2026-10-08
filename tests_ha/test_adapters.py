"""Import and exercise real HA adapters, with no real Bluetooth or cloud."""

import asyncio
import base64
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

from homeassistant.exceptions import HomeAssistantError

from custom_components.tuya_smartlock_local_ble import (
    button,
    config_flow,
    lock,
    select,
    switch,
)
from custom_components.tuya_smartlock_local_ble.application.lock_commands import (
    LockCommandWaiter,
)


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_wait_option_defaults_off_and_requires_persistence(self):
        flow = config_flow.SmartlockOptionsFlow()
        flow.hass = MagicMock()
        entry = SimpleNamespace(options={"keep_connected": True, "other": "preserved"})
        with patch.object(type(flow), "config_entry", new_callable=PropertyMock) as prop:
            prop.return_value = entry
            form = await flow.async_step_init()
            self.assertFalse(form["data_schema"]({})["wait_for_reconnect"])
            invalid = await flow.async_step_init({"keep_connected": False,
                                                  "wait_for_reconnect": True})
            self.assertEqual(invalid["errors"]["base"], "wait_requires_connection")
            result = await flow.async_step_init({"keep_connected": True,
                                                 "wait_for_reconnect": True})
            self.assertTrue(result["data"]["wait_for_reconnect"])
            self.assertEqual(result["data"]["other"], "preserved")
            disabled = await flow.async_step_init({"keep_connected": True,
                                                   "wait_for_reconnect": False})
            self.assertFalse(disabled["data"]["wait_for_reconnect"])

    async def test_lock_accepts_short_outage_but_other_entities_stay_unavailable(self):
        device = MagicMock(address="AA:BB:CC:DD:EE:FF", command_ready=True)
        coordinator = MagicMock(connected=True)
        commands = LockCommandWaiter(device, coordinator.async_update_listeners, 0.1)
        self.addAsyncCleanup(commands.close)
        model = MagicMock(lock=AsyncMock(), unlock=AsyncMock())
        data = SimpleNamespace(device=device, coordinator=coordinator,
                               model=model, commands=commands)
        entity = lock.LockControl(data)
        entity.async_write_ha_state = MagicMock()
        entity._attr_is_locked = True
        device.command_ready = False
        coordinator.connected = False
        commands._disconnected()
        self.assertTrue(entity.available)
        self.assertFalse(switch.RotationDirection(data).available)
        self.assertIsNone(entity.is_locked)
        task = asyncio.create_task(entity.async_unlock())
        await asyncio.sleep(0)
        self.assertTrue(entity.extra_state_attributes["command_pending"])
        self.assertFalse(entity.extra_state_attributes["bluetooth_connected"])
        with self.assertRaises(HomeAssistantError):
            await entity.async_lock()
        model.unlock.assert_not_awaited()
        device.command_ready = True
        coordinator.connected = True
        commands._connected()
        await task
        model.unlock.assert_awaited_once()
        model.lock.assert_not_awaited()
        self.assertFalse(entity.is_locked)

    async def test_disabled_option_keeps_original_entity_availability(self):
        data = SimpleNamespace(device=MagicMock(address="AA:BB:CC:DD:EE:FF"),
                               model=MagicMock(), coordinator=MagicMock(connected=False),
                               commands=None)
        self.assertFalse(lock.LockControl(data).available)

    async def test_expired_wait_reports_failure_without_changing_lock_state(self):
        device = MagicMock(address="AA:BB:CC:DD:EE:FF", command_ready=False)
        coordinator = MagicMock(connected=False)
        commands = LockCommandWaiter(device, coordinator.async_update_listeners, 0.01)
        self.addAsyncCleanup(commands.close)
        model = MagicMock(unlock=AsyncMock())
        entity = lock.LockControl(SimpleNamespace(device=device, model=model,
                                                  coordinator=coordinator, commands=commands))
        entity.async_write_ha_state = MagicMock()
        entity._attr_is_locked = True
        commands._disconnected()
        with self.assertRaises(HomeAssistantError):
            await entity.async_unlock()
        model.unlock.assert_not_awaited()
        self.assertFalse(entity.available)
        self.assertTrue(entity._attr_is_locked)

    def flow(self):
        flow = config_flow.SmartlockConfigFlow()
        flow.hass = MagicMock()
        flow.context = {"source": "user"}
        flow._async_current_ids = MagicMock(return_value=set())
        flow.async_set_unique_id = AsyncMock()
        flow._abort_if_unique_id_configured = MagicMock()
        flow._address = "AA:BB:CC:DD:EE:FF"
        flow._devices = {
            flow._address: SimpleNamespace(name="FD50", device=MagicMock())
        }
        return flow

    def credentials(self):
        return dict(
            product_id="hc7n0urm",
            uuid="synthetic-uuid",
            local_key="synthetic-key",
            device_id="synthetic-id",
            ble_unlock_check=base64.b64encode(
                b"\x00\x01\xff\xff12345678\x01\x01\x02\x03\x04\x00\x00"
            ).decode(),
        )

    async def test_clean_setup_does_not_read_legacy_file(self):
        flow = self.flow()
        peer = MagicMock(initialize=AsyncMock(), update=AsyncMock(), stop=AsyncMock())
        with patch.object(
            config_flow, "create_connection", return_value=(peer, MagicMock())
        ):
            result = await flow.async_step_credentials(self.credentials())
        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["data"]["credentials"]["device_id"], "synthetic-id")
        flow.hass.async_add_executor_job.assert_not_called()
        peer.update.assert_awaited_once()
        peer.stop.assert_awaited_once()
        peer.send_command.assert_not_called()

    async def test_invalid_and_failed_setup_never_create_entry(self):
        flow = self.flow()
        values = self.credentials()
        values["ble_unlock_check"] = "not base64"
        result = await flow.async_step_credentials(values)
        self.assertEqual(result["errors"]["base"], "invalid_credentials")
        peer = MagicMock(
            initialize=AsyncMock(),
            update=AsyncMock(side_effect=TimeoutError),
            stop=AsyncMock(),
        )
        with patch.object(
            config_flow, "create_connection", return_value=(peer, MagicMock())
        ):
            result = await flow.async_step_credentials(self.credentials())
        self.assertEqual(result["errors"]["base"], "cannot_connect")
        self.assertNotIn("synthetic-key", str(result))
        peer.stop.assert_awaited_once()

    async def test_entity_commands_go_through_model(self):
        model = MagicMock(
            volumes=("mute", "normal"),
            battery_levels=("high", "medium", "low", "poweroff"),
            lock=AsyncMock(),
            unlock=AsyncMock(),
            set_volume=AsyncMock(),
            set_direction=AsyncMock(),
            calibrate=AsyncMock(),
        )
        data = SimpleNamespace(
            model=model,
            device=MagicMock(address="AA:BB:CC:DD:EE:FF"),
            coordinator=MagicMock(),
            commands=None,
        )
        entity = lock.LockControl(data)
        entity.async_write_ha_state = MagicMock()
        await entity.async_lock()
        await entity.async_unlock()
        volume = select.SoundVolume(data)
        volume.async_write_ha_state = MagicMock()
        await volume.async_select_option("mute")
        await switch.RotationDirection(data).async_turn_on()
        await button.CalibrateButton(data).async_press()
        model.lock.assert_awaited_once()
        model.unlock.assert_awaited_once()
        model.set_volume.assert_awaited_once_with("mute")
        model.set_direction.assert_awaited_once_with(True)
        model.calibrate.assert_awaited_once()
