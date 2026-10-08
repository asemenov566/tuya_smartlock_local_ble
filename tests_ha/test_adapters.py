"""Import and exercise real HA adapters, with no real Bluetooth or cloud."""

import base64
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.tuya_local_ble_custom import (
    button,
    config_flow,
    lock,
    select,
    switch,
)


class AdapterTests(unittest.IsolatedAsyncioTestCase):
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
