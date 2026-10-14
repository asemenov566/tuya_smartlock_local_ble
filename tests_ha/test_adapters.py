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
    devices,
    lock,
    select,
    sensor,
    switch,
)
from custom_components.tuya_smartlock_local_ble.application.lock_actions import (
    LockActions,
)
from custom_components.tuya_smartlock_local_ble.application.lock_commands import (
    LockCommandWaiter,
)
from custom_components.tuya_smartlock_local_ble.application.lock_status import (
    ReportedLockStatus,
)


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_connected_metadata_uses_own_config_entry(self):
        coordinator = object.__new__(devices.SmartlockCoordinator)
        coordinator.hass = MagicMock()
        coordinator._device = SimpleNamespace(
            address="AA:BB:CC:DD:EE:FF", device_version="6.0",
            protocol_version="4.5", hardware_version="1.0")
        coordinator._config_entry_id = "own-entry"
        coordinator.async_update_listeners = MagicMock()
        registry = MagicMock()
        registry.async_get_device_by_identifier.return_value = SimpleNamespace(id="own-device")
        with patch.object(devices.dr, "async_get", return_value=registry):
            coordinator._connected()
        registry.async_get_device_by_identifier.assert_called_once_with(
            (devices.DOMAIN, "AA:BB:CC:DD:EE:FF"), "own-entry")
        registry.async_get_device.assert_not_called()
        registry.async_update_device.assert_called_once_with(
            "own-device", sw_version="6.0 (protocol 4.5)", hw_version="1.0")

    async def test_explicit_buttons_do_not_depend_on_known_position(self):
        model = SimpleNamespace(
            lock=AsyncMock(),
            unlock=AsyncMock(),
            lock_report=None,
            name="Test",
            manufacturer="Test",
            product_id="test",
        )
        data = self.data(
            MagicMock(address="AA:BB:CC:DD:EE:FF", command_ready=True),
            model,
            MagicMock(connected=False),
            None,
        )
        opened = button.LockActionButton(data, False)
        closed = button.LockActionButton(data, True)
        expected = sensor.ExpectedAction(data)
        physical = sensor.LockStatus(data)
        self.assertTrue(opened.available)
        self.assertTrue(closed.available)
        self.assertIsNone(physical.native_value)
        await closed.async_press()
        self.assertEqual(expected.native_value, "closing")
        self.assertIsNone(physical.native_value)
        await opened.async_press()
        self.assertEqual(expected.native_value, "opening")
        self.assertEqual(
            expected.extra_state_attributes["state_source"], "requested_action"
        )
        self.assertIsNone(physical.native_value)
        model.lock.assert_awaited_once()
        model.unlock.assert_awaited_once()

    async def test_refresh_button_only_calls_read_only_session_service(self):
        model = SimpleNamespace(
            lock=AsyncMock(),
            unlock=AsyncMock(),
            lock_report=None,
            name="Test",
            manufacturer="Test",
            product_id="test",
        )
        data = self.data(
            MagicMock(address="AA:BB:CC:DD:EE:FF", command_ready=False),
            model,
            MagicMock(connected=False),
            None,
        )
        data.session_policy = SimpleNamespace(refresh=AsyncMock(), persistent=False)
        entity = button.RefreshStatusButton(data)
        self.assertTrue(entity.available)
        await entity.async_press()
        data.session_policy.refresh.assert_awaited_once()
        model.lock.assert_not_awaited()
        model.unlock.assert_not_awaited()

    async def test_settings_use_session_policy_when_disconnected(self):
        model = MagicMock(
            lock=AsyncMock(),
            unlock=AsyncMock(),
            set_volume=AsyncMock(),
            set_direction=AsyncMock(),
            calibrate=AsyncMock(),
            volumes=("mute", "normal"),
        )
        data = self.data(
            MagicMock(address="AA:BB:CC:DD:EE:FF", command_ready=False),
            model,
            MagicMock(connected=False),
            None,
        )
        calls = []

        async def execute(action):
            calls.append(action)
            await action()

        data.session_policy = SimpleNamespace(execute=execute, persistent=False)
        volume = select.SoundVolume(data)
        volume.async_write_ha_state = MagicMock()
        await volume.async_select_option("mute")
        await switch.RotationDirection(data).async_turn_off()
        await button.CalibrateButton(data).async_press()
        self.assertEqual(len(calls), 3)
        model.set_volume.assert_awaited_once_with("mute")
        model.set_direction.assert_awaited_once_with(False)
        model.calibrate.assert_awaited_once()

    def data(self, device, model, coordinator, commands, status=None):
        if status is None:
            model.lock_report = None
            status = ReportedLockStatus(
                device, model, coordinator.async_update_listeners
            )
            self.addCleanup(status.close)
        actions = LockActions(
            model, status, commands, coordinator.async_update_listeners
        )
        return SimpleNamespace(
            device=device,
            model=model,
            coordinator=coordinator,
            commands=commands,
            status=status,
            actions=actions,
        )

    async def test_control_toggles_but_status_waits_for_device_report(self):
        device = MagicMock(address="AA:BB:CC:DD:EE:FF", command_ready=True)
        coordinator = MagicMock(connected=True)
        model = SimpleNamespace(
            lock=AsyncMock(),
            unlock=AsyncMock(),
            lock_report=None,
            name="Test",
            manufacturer="Test",
            product_id="test",
        )
        status = ReportedLockStatus(device, model, coordinator.async_update_listeners)
        self.addCleanup(status.close)
        data = self.data(
            device=device,
            coordinator=coordinator,
            model=model,
            commands=None,
            status=status,
        )
        control = lock.LockControl(data)
        control.async_write_ha_state = MagicMock()
        reported = sensor.LockStatus(data)
        self.assertIsNone(reported.native_value)
        await control.async_unlock()
        self.assertFalse(control.is_locked)
        self.assertIsNone(reported.native_value)
        self.assertEqual(reported.icon, "mdi:lock-question")
        model.lock_report = (1, False)
        status._updated([])
        self.assertEqual(reported.native_value, "unlocked")
        self.assertEqual(reported.icon, "mdi:lock-open")
        await control.async_lock()
        self.assertTrue(control.is_locked)
        self.assertIsNone(reported.native_value)
        model.lock_report = (2, False)  # device still reports unlocked
        status._updated([])
        self.assertEqual(reported.native_value, "unlocked")
        self.assertTrue(
            control.is_locked
        )  # repeated starting position is not a new action
        await button.LockActionButton(data, True).async_press()
        self.assertTrue(control.is_locked)
        self.assertIsNone(reported.native_value)
        await control.async_toggle()
        self.assertFalse(control.is_locked)
        coordinator.connected = False
        self.assertTrue(reported.available)
        data.status.invalidate()
        self.assertIsNone(reported.native_value)

    async def test_button_reverses_pending_lock_and_manual_report_syncs_control(self):
        started = asyncio.Event()

        async def close_motor():
            started.set()
            await asyncio.Event().wait()

        device = MagicMock(address="AA:BB:CC:DD:EE:FF", command_ready=True)
        coordinator = MagicMock(connected=True)
        model = SimpleNamespace(
            lock=AsyncMock(side_effect=close_motor),
            unlock=AsyncMock(),
            lock_report=None,
            name="Test",
            manufacturer="Test",
            product_id="test",
        )
        waiter = LockCommandWaiter(device, coordinator.async_update_listeners)
        self.addAsyncCleanup(waiter.close)
        data = self.data(device, model, coordinator, waiter)
        self.addAsyncCleanup(data.actions.close)
        control = lock.LockControl(data)
        toggle = button.LockActionButton(data, False)
        reported = sensor.LockStatus(data)
        first = asyncio.create_task(control.async_lock())
        await started.wait()
        self.assertTrue(control.is_locked)
        self.assertTrue(control.extra_state_attributes["command_pending"])
        self.assertTrue(toggle.available)
        await toggle.async_press()
        await first
        model.unlock.assert_awaited_once()
        self.assertFalse(control.is_locked)
        self.assertIsNone(reported.native_value)
        model.lock_report = (1, True)
        data.status._updated([])
        self.assertTrue(control.is_locked)
        self.assertEqual(reported.native_value, "locked")

    async def test_options_select_only_settings_for_chosen_mode(self):
        flow = config_flow.SmartlockOptionsFlow()
        flow.hass = MagicMock()
        entry = SimpleNamespace(options={"keep_connected": True, "other": "preserved"})
        with patch.object(
            type(flow), "config_entry", new_callable=PropertyMock
        ) as prop:
            prop.return_value = entry
            form = await flow.async_step_init()
            self.assertTrue(form["data_schema"]({})["keep_connected"])
            persistent = await flow.async_step_init({"keep_connected": True})
            self.assertEqual(persistent["step_id"], "persistent")
            self.assertFalse(persistent["data_schema"]({})["wait_for_reconnect"])
            result = await flow.async_step_persistent({"wait_for_reconnect": True})
            self.assertTrue(result["data"]["wait_for_reconnect"])
            self.assertEqual(result["data"]["other"], "preserved")
            mode = await flow.async_step_init({"keep_connected": False})
            self.assertEqual(mode["step_id"], "on_demand")
            self.assertEqual(mode["data_schema"]({})["poll_interval"], "20")
            disabled = await flow.async_step_on_demand(
                {"poll_interval": "0", "hold_time": "30"}
            )
            self.assertFalse(disabled["data"]["wait_for_reconnect"])
            self.assertEqual(disabled["data"]["poll_interval"], 0)
            self.assertEqual(disabled["data"]["hold_time"], 30)

    async def test_controls_accept_long_outage_but_other_entities_stay_unavailable(
        self,
    ):
        device = MagicMock(address="AA:BB:CC:DD:EE:FF", command_ready=True)
        coordinator = MagicMock(connected=True)
        commands = LockCommandWaiter(device, coordinator.async_update_listeners, 0.02)
        self.addAsyncCleanup(commands.close)
        model = MagicMock(lock=AsyncMock(), unlock=AsyncMock())
        data = self.data(
            device=device,
            coordinator=coordinator,
            model=model,
            commands=commands,
            status=None,
        )
        entity = lock.LockControl(data)
        entity.async_write_ha_state = MagicMock()
        entity._actions._intent = True
        device.command_ready = False
        coordinator.connected = False
        commands._disconnected()
        await asyncio.sleep(0.04)
        self.assertTrue(entity.available)
        toggle = button.LockActionButton(data, True)
        self.assertTrue(toggle.available)
        self.assertTrue(sensor.LockStatus(data).available)
        self.assertTrue(switch.RotationDirection(data).available)
        self.assertTrue(entity.is_locked)
        task = asyncio.create_task(entity.async_unlock())
        await asyncio.sleep(0)
        self.assertTrue(entity.extra_state_attributes["command_pending"])
        self.assertFalse(entity.extra_state_attributes["bluetooth_connected"])
        self.assertFalse(entity.is_locked)
        model.unlock.assert_not_awaited()
        device.command_ready = True
        coordinator.connected = True
        commands._connected()
        await task
        model.unlock.assert_awaited_once()
        model.lock.assert_not_awaited()
        self.assertFalse(entity.is_locked)
        device.command_ready = False
        coordinator.connected = False
        commands._disconnected()
        await asyncio.sleep(0.04)
        task = asyncio.create_task(toggle.async_press())
        await asyncio.sleep(0)
        model.lock.assert_not_awaited()
        device.command_ready = True
        coordinator.connected = True
        commands._connected()
        await task
        model.lock.assert_awaited_once()
        self.assertTrue(entity.is_locked)

    async def test_disabled_option_keeps_original_entity_availability(self):
        data = self.data(
            device=MagicMock(address="AA:BB:CC:DD:EE:FF"),
            model=MagicMock(),
            coordinator=MagicMock(connected=False),
            commands=None,
            status=None,
        )
        self.assertTrue(lock.LockControl(data).available)

    async def test_expired_wait_reports_failure_without_changing_lock_state(self):
        device = MagicMock(address="AA:BB:CC:DD:EE:FF", command_ready=False)
        coordinator = MagicMock(connected=False)
        commands = LockCommandWaiter(device, coordinator.async_update_listeners, 0.01)
        self.addAsyncCleanup(commands.close)
        model = MagicMock(unlock=AsyncMock())
        entity = lock.LockControl(
            self.data(
                device=device,
                model=model,
                coordinator=coordinator,
                commands=commands,
                status=None,
            )
        )
        entity.async_write_ha_state = MagicMock()
        entity._actions._intent = True
        commands._disconnected()
        with self.assertRaises(HomeAssistantError):
            await entity.async_unlock()
        model.unlock.assert_not_awaited()
        self.assertTrue(entity.available)
        self.assertTrue(entity._actions.locked)

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
        data = self.data(
            model=model,
            device=MagicMock(address="AA:BB:CC:DD:EE:FF"),
            coordinator=MagicMock(),
            commands=None,
            status=None,
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
