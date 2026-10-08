"""Behavior tests with fake BLE peers; never contact a physical lock."""

import asyncio
import base64
import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

ROOT = Path(__file__).resolve().parents[1] / "custom_components/tuya_smartlock_local_ble"
package = types.ModuleType("custom_ble_test")
package.__path__ = [str(ROOT)]
sys.modules[package.__name__] = package
protocol = importlib.import_module("custom_ble_test.protocols.tuya_ble.session")
credentials = importlib.import_module("custom_ble_test.domain.credentials")
keepalive = importlib.import_module("custom_ble_test.keepalive")
Model = importlib.import_module("custom_ble_test.models.a1_ultra").A1UltraModel
ConnectionManager = importlib.import_module(
    "custom_ble_test.connections"
).ConnectionManager
Device = protocol.TuyaBLEProtocol
Code = protocol.TuyaCommandCode


def device():
    result = Device(MagicMock(), MagicMock(address="00:00:00:00:00:00"))
    result._device_info = credentials.LockCredentials(
        "test-uuid",
        "test-key",
        "test-id",
        "jtmspro",
        "hc7n0urm",
        "Test lock",
        "AT1",
        "A1 Ultra",
    )
    result.model = Model(result, result._device_info)
    return result


class ConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_codec_roundtrip_and_crc_rejection(self):
        codec = protocol.PacketCodec
        key = b"0123456789abcdef"
        packets = codec.build_packets(
            7,
            Code.FUN_SENDER_DPS_V4,
            b"synthetic-command",
            3,
            login_key=key,
            session_key=key,
            protocol_version=4,
        )
        envelope = bytearray()
        for packet in packets:
            number, pos = codec.unpack_int(packet, 0)
            if number == 0:
                length, pos = codec.unpack_int(packet, pos)
                pos += 1
            envelope += packet[pos:]
        self.assertEqual(
            codec.decode(envelope, key),
            (7, 3, Code.FUN_SENDER_DPS_V4.value, b"synthetic-command"),
        )
        cipher = protocol.AES.new(key, protocol.AES.MODE_CBC, envelope[1:17])
        raw = bytearray(cipher.decrypt(envelope[17:]))
        raw[12] ^= 1
        cipher = protocol.AES.new(key, protocol.AES.MODE_CBC, envelope[1:17])
        corrupted = envelope[:17] + cipher.encrypt(bytes(raw))
        with self.assertRaises(
            importlib.import_module(
                "custom_ble_test.protocols.tuya_ble.exceptions"
            ).PacketCRCError
        ):
            codec.decode(corrupted, key)

    async def test_inherited_model_registers_without_changing_core(self):
        registry = importlib.import_module("custom_ble_test.registry")

        class CompatibleModel(Model):
            product_id = "synthetic-compatible-id"
            name = "Synthetic compatible lock"

        original = dict(registry.MODELS)
        try:
            registry.register_model(CompatibleModel)
            info = credentials.LockCredentials(
                "synthetic-uuid",
                "synthetic-key",
                "synthetic-id",
                "jtmspro",
                CompatibleModel.product_id,
                "Test",
                "Test",
                "Test",
            )
            peer, model = registry.create_connection(
                info, MagicMock(), MagicMock(address="00:00:00:00:00:00")
            )
            peer.send_command = AsyncMock()
            await model.lock()
            await model.set_volume("mute")
            self.assertIsInstance(model, CompatibleModel)
            self.assertEqual(
                peer.send_command.await_args_list[0].args[0],
                bytes.fromhex("00000000012e00000101"),
            )
            with self.assertRaises(ValueError):
                registry.register_model(CompatibleModel)
        finally:
            registry.MODELS.clear()
            registry.MODELS.update(original)

    async def test_command_can_be_replaced_without_copying_model(self):
        lock = device()
        replacement = MagicMock(execute=AsyncMock())
        lock.model.unlock_command = replacement
        await lock.model.unlock()
        replacement.execute.assert_awaited_once_with(lock)

    async def test_configuration_wire_commands(self):
        lock = device()
        lock._send_packet = AsyncMock()
        for dp, value, expected in [
            (31, 1, "00000000011f00000101"),
            (31, 0, "00000000011f00000100"),
            (78, True, "00000000014e00000101"),
            (78, False, "00000000014e00000100"),
            (68, 0, "00000000014400000100"),
        ]:
            if dp == 31:
                await lock.model.set_volume("normal" if value else "mute")
            elif dp == 78:
                await lock.model.set_direction(value)
            else:
                await lock.model.calibrate()
            lock._send_packet.assert_awaited_with(
                Code.FUN_SENDER_DPS_V4, bytes.fromhex(expected), True
            )
        self.assertIsNone(lock.datapoints[68])

    async def test_configuration_rejects_unreviewed_values(self):
        lock = device()
        lock._send_packet = AsyncMock()
        for value in ("loud", 2, None):
            with self.assertRaises(protocol.ProtocolError):
                await lock.model.set_volume(value)
        with self.assertRaises(protocol.ProtocolError):
            await lock.model.set_direction(1)
        lock._send_packet.assert_not_awaited()

    async def test_failed_configuration_does_not_publish_success(self):
        lock = device()
        lock._send_packet = AsyncMock(side_effect=TimeoutError)
        with self.assertRaises(TimeoutError):
            await lock.model.set_direction(True)
        self.assertIsNone(lock.datapoints[78])

    async def test_configuration_echo_and_battery_parser(self):
        lock = device()
        lock._parse_datapoints_v4(bytes.fromhex("a100000904000100"))
        self.assertEqual(lock.datapoints[9].value, 0)
        lock._parse_datapoints_v4(bytes.fromhex("a100004e01000101"))
        self.assertEqual(lock.datapoints[78].value, 1)
        lock._parse_datapoints_v4(bytes.fromhex("00000000011f00000101"))
        self.assertEqual(lock.datapoints[31].value, 1)

    async def test_connection_manager_closes_and_cancels_session(self):
        manager = ConnectionManager()
        peer = MagicMock(
            initialize=AsyncMock(),
            update=AsyncMock(),
            stop=AsyncMock(),
            refresh_session=AsyncMock(),
        )
        await manager.start("one", peer)
        await manager.close("one")
        await manager.close("one")
        peer.stop.assert_awaited_once()
        self.assertFalse(manager._connections)

    async def test_failed_setup_closes_session(self):
        manager = ConnectionManager()
        peer = MagicMock(
            initialize=AsyncMock(),
            update=AsyncMock(side_effect=TimeoutError),
            stop=AsyncMock(),
        )
        with self.assertRaises(TimeoutError):
            await manager.start("one", peer)
        peer.stop.assert_awaited_once()
        self.assertFalse(manager._connections)

    async def test_failed_heartbeat_still_releases_ble_client(self):
        manager = ConnectionManager()
        peer = MagicMock(initialize=AsyncMock(), update=AsyncMock(), stop=AsyncMock())
        await manager.start("one", peer, keep_connected=False)

        async def failed_heartbeat():
            raise RuntimeError("synthetic heartbeat failure")

        task = asyncio.create_task(failed_heartbeat())
        manager._connections["one"].task = task
        await asyncio.sleep(0)
        with self.assertRaises(RuntimeError):
            await manager.close("one")
        peer.stop.assert_awaited_once()
        self.assertFalse(manager._connections)

    async def test_shutdown_attempts_every_session_after_disconnect_failure(self):
        manager = ConnectionManager()
        first = MagicMock(
            initialize=AsyncMock(),
            update=AsyncMock(),
            stop=AsyncMock(side_effect=RuntimeError("synthetic disconnect failure")),
        )
        second = MagicMock(initialize=AsyncMock(), update=AsyncMock(), stop=AsyncMock())
        await manager.start("one", first, keep_connected=False)
        await manager.start("two", second, keep_connected=False)
        with self.assertRaises(ExceptionGroup) as result:
            await manager.close_all()
        self.assertEqual(len(result.exception.exceptions), 1)
        first.stop.assert_awaited_once()
        second.stop.assert_awaited_once()
        self.assertFalse(manager._connections)

    async def test_refresh_is_status_read_not_datapoint_write(self):
        lock = device()
        lock._ensure_connected = AsyncMock()
        lock._send_packet_while_connected = AsyncMock(return_value=True)
        lock.send_command = AsyncMock()
        await lock.update()
        lock._ensure_connected.assert_awaited_once()
        lock._send_packet_while_connected.assert_awaited_once_with(
            Code.FUN_SENDER_DEVICE_STATUS, b"", 0, True
        )
        lock.send_command.assert_not_awaited()

    async def test_missing_ack_is_error(self):
        lock = device()
        lock._ensure_connected = AsyncMock()
        lock._send_packet_while_connected = AsyncMock(return_value=False)
        with self.assertRaises(TimeoutError):
            await lock._send_packet(Code.FUN_SENDER_DPS_V4, b"test-command")

    async def test_stopped_device_rejects_commands(self):
        lock = device()
        await lock.stop()
        with self.assertRaises(protocol.ProtocolError):
            await lock.update()

    async def test_failed_status_discards_session_for_next_reconnect(self):
        lock = device()
        client = MagicMock(is_connected=True)
        client.stop_notify = AsyncMock()
        client.disconnect = AsyncMock()
        lock._client = client
        lock._is_paired = True
        lock.update = AsyncMock(side_effect=TimeoutError)
        with self.assertRaises(TimeoutError):
            await lock.refresh_session()
        client.disconnect.assert_awaited_once()
        self.assertIsNone(lock._client)
        self.assertFalse(lock._expected_disconnect)
        self.assertFalse(lock._is_paired)

    async def test_stop_disconnects_even_if_stop_notify_fails(self):
        lock = device()
        client = MagicMock(is_connected=True)
        client.stop_notify = AsyncMock(side_effect=protocol.BleakError("test"))
        client.disconnect = AsyncMock()
        lock._client = client
        with self.assertRaises(protocol.BleakError):
            await lock.stop()
        client.disconnect.assert_awaited_once()

    async def test_cancelled_request_clears_pending_ack(self):
        lock = device()
        lock._build_packets = MagicMock(return_value=[b"fake"])
        lock._int_send_packet_while_connected = AsyncMock()
        task = asyncio.create_task(
            lock._send_packet_while_connected(
                Code.FUN_SENDER_DEVICE_STATUS, b"", 0, True
            )
        )
        await asyncio.sleep(0)
        self.assertEqual(len(lock._input_expected_responses), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(lock._input_expected_responses, {})

    async def test_encode_failure_clears_pending_ack_without_sending(self):
        lock = device()
        lock._build_packets = MagicMock(side_effect=ValueError("synthetic invalid key"))
        lock._int_send_packet_while_connected = AsyncMock()
        with self.assertRaises(ValueError):
            await lock._send_packet_while_connected(
                Code.FUN_SENDER_DEVICE_STATUS, b"", 0, True
            )
        self.assertEqual(lock._input_expected_responses, {})
        lock._int_send_packet_while_connected.assert_not_awaited()

    async def test_failed_write_never_replays_motor_command(self):
        lock = device()
        lock.managed_connection = True
        lock._is_paired = True
        lock._int_send_packets_locked = AsyncMock(
            side_effect=protocol.BleakError("test")
        )
        lock._resend_packets = AsyncMock()
        lock._reconnect = AsyncMock()
        with self.assertRaises(protocol.BleakError):
            await lock._send_packets_locked([b"motor-command"])
        await asyncio.sleep(0)
        lock._resend_packets.assert_not_called()
        lock._reconnect.assert_not_called()

    async def test_managed_disconnect_leaves_retries_to_heartbeat(self):
        lock = device()
        lock.managed_connection = True
        lock._is_paired = True
        lock._reconnect = AsyncMock()
        lock._client = client = MagicMock()
        lock._disconnected(client)
        await asyncio.sleep(0)
        self.assertFalse(lock._is_paired)
        lock._reconnect.assert_not_called()

    async def test_incoming_reply_can_unblock_waiting_request(self):
        lock = device()
        lock._client = MagicMock(is_connected=True)
        lock._build_packets = MagicMock(return_value=[b"synthetic"])
        lock._int_send_packet_while_connected = AsyncMock()
        request = asyncio.create_task(lock._send_packet_while_connected(
            Code.FUN_SENDER_DEVICE_STATUS, b"", 0, True
        ))
        await asyncio.sleep(0)
        await asyncio.wait_for(lock._send_response(
            Code.FUN_RECEIVE_TIME1_REQ, b"synthetic-time", 42
        ), 1)
        self.assertEqual(lock._int_send_packet_while_connected.await_count, 2)
        self.assertFalse(request.done())
        next(iter(lock._input_expected_responses.values())).set_result(0)
        self.assertTrue(await request)

    async def test_old_notification_reply_is_not_sent_to_new_connection(self):
        lock = device()
        old_client = MagicMock(is_connected=True)
        lock._client = old_client
        lock._int_send_packet_while_connected = AsyncMock()
        await lock._operation_lock.acquire()
        reply = asyncio.create_task(lock._send_response(
            Code.FUN_RECEIVE_TIME1_REQ, b"synthetic-time", 42, old_client
        ))
        await asyncio.sleep(0)
        lock._client = MagicMock(is_connected=True)
        lock._operation_lock.release()
        await reply
        lock._int_send_packet_while_connected.assert_not_awaited()

    async def test_late_old_disconnect_keeps_new_connection(self):
        lock = device()
        lock._client = current = MagicMock(is_connected=True)
        lock._is_paired = True
        lock._disconnected(MagicMock())
        self.assertIs(lock._client, current)
        self.assertTrue(lock._is_paired)

    async def test_remote_disconnect_releases_disconnected_backend(self):
        lock = device()
        lock.managed_connection = True
        lock._client = client = MagicMock(is_connected=False)
        client.disconnect = AsyncMock()
        lock._disconnected(client)
        await lock._wait_for_client_cleanup()
        client.disconnect.assert_awaited_once()
        self.assertFalse(lock._client_cleanup_tasks)

    async def test_stop_releases_backend_without_active_radio_link(self):
        lock = device()
        lock._client = client = MagicMock(is_connected=False)
        client.stop_notify = AsyncMock()
        client.disconnect = AsyncMock()
        await lock.stop()
        client.disconnect.assert_awaited_once()
        client.stop_notify.assert_not_awaited()

    async def test_retired_notifications_cannot_enter_current_session(self):
        lock = device()
        old = MagicMock()
        lock._client = current = MagicMock()
        lock._notification_handler = MagicMock()
        lock._session_notification(old, 1, b"stale")
        lock._session_notification(current, 1, b"current")
        lock._stopped = True
        lock._session_notification(current, 1, b"after-stop")
        lock._notification_handler.assert_called_once_with(1, b"current")

    async def test_reconnect_waits_for_retired_backend_cleanup(self):
        lock = device()
        lock.managed_connection = True
        lock._client = client = MagicMock(is_connected=False)
        released = asyncio.Event()
        client.disconnect = AsyncMock(side_effect=released.wait)
        lock._transport.connect = AsyncMock(side_effect=asyncio.CancelledError)
        lock._disconnected(client)
        reconnect = asyncio.create_task(lock._ensure_connected())
        await asyncio.sleep(0.03)
        lock._transport.connect.assert_not_awaited()
        released.set()
        with self.assertRaises(asyncio.CancelledError):
            await reconnect
        lock._transport.connect.assert_awaited_once()

    async def test_disconnect_aborts_request_without_ack_timeout(self):
        lock = device()
        lock.managed_connection = True
        lock._client = current = MagicMock(is_connected=True)
        lock._build_packets = MagicMock(return_value=[b"synthetic"])
        lock._int_send_packet_while_connected = AsyncMock()
        request = asyncio.create_task(lock._send_packet_while_connected(
            Code.FUN_SENDER_DEVICE_STATUS, b"", 0, True
        ))
        await asyncio.sleep(0)
        lock._disconnected(current)
        with self.assertRaises(protocol.BleakError):
            await asyncio.wait_for(request, 1)
        self.assertFalse(lock._input_expected_responses)

    async def test_disconnect_wakes_heartbeat_and_uses_short_retry(self):
        disconnected = asyncio.Event()
        disconnected.set()
        delays = []
        refresh = AsyncMock(side_effect=[OSError(), None])

        async def sleep(delay):
            delays.append(delay)
            if len(delays) == 2:
                raise asyncio.CancelledError

        with self.assertRaises(asyncio.CancelledError):
            await keepalive.maintain_connection(
                refresh, disconnected=disconnected, sleep=sleep, interval=30
            )
        self.assertEqual(delays, [1, 2])
        refresh.assert_awaited_once()

    async def test_stop_cancels_queued_notification_responses(self):
        lock = device()
        lock._client = MagicMock(is_connected=True)
        lock._execute_disconnect = AsyncMock()
        await lock._operation_lock.acquire()
        lock._queue_response(Code.FUN_RECEIVE_TIME1_REQ, b"time", 1)
        await asyncio.sleep(0)
        await lock.stop()
        self.assertFalse(lock._response_tasks)
        lock._operation_lock.release()

    async def test_heartbeat_backoff_is_bounded_and_recovers(self):
        delays = []
        refresh = AsyncMock(side_effect=[OSError(), OSError(), None, None])

        async def sleep(delay):
            delays.append(delay)
            if len(delays) == 5:
                raise asyncio.CancelledError

        with self.assertRaises(asyncio.CancelledError):
            await keepalive.maintain_connection(
                refresh, interval=30, max_delay=120, sleep=sleep
            )
        self.assertEqual(delays, [30, 60, 120, 30, 30])
        self.assertEqual(refresh.await_count, 4)

    async def test_unload_cancels_inflight_refresh(self):
        started, cancelled = asyncio.Event(), asyncio.Event()

        async def refresh():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        task = asyncio.create_task(
            keepalive.maintain_connection(refresh, interval=0.001)
        )
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(cancelled.is_set())

    async def test_slow_refresh_does_not_accumulate_tasks(self):
        active = peak = calls = 0

        async def refresh():
            nonlocal active, peak, calls
            calls += 1
            active += 1
            peak = max(peak, active)
            try:
                await asyncio.Event().wait()
            finally:
                active -= 1

        async def sleep(delay):
            if calls == 3:
                raise asyncio.CancelledError

        with self.assertRaises(asyncio.CancelledError):
            await keepalive.maintain_connection(refresh, timeout=0.001, sleep=sleep)
        self.assertEqual(peak, 1)
        self.assertEqual(active, 0)

    async def test_fd50_characteristics_used_if_legacy_missing(self):
        lock = device()
        client = MagicMock()
        client.services.get_characteristic.side_effect = lambda uuid: (
            uuid == protocol.CHARACTERISTIC_NOTIFY_FD50
        )
        lock._select_characteristics(client)
        self.assertEqual(
            lock._characteristic_notify, protocol.CHARACTERISTIC_NOTIFY_FD50
        )
        self.assertEqual(lock._characteristic_write, protocol.CHARACTERISTIC_WRITE_FD50)

    async def test_unlock_requires_device_specific_value(self):
        lock = device()
        with self.assertRaises(protocol.ProtocolError):
            lock.model.unlock_command.payload()
        lock._device_info.ble_unlock_check = base64.b64encode(
            b"\x00\x01\xff\xff12345678\x01\x01\x02\x03\x04\x00\x00"
        ).decode()
        self.assertEqual(
            lock.model.unlock_command.payload(),
            bytes.fromhex("000000000147000013ffff0001")
            + b"12345678\x01\x01\x02\x03\x04\x00\x01",
        )


if __name__ == "__main__":
    unittest.main()
