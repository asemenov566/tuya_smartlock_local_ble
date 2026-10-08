"""Application waiting and transmission boundaries; synthetic devices only."""

import asyncio
import importlib
import unittest
from unittest.mock import AsyncMock, MagicMock

from test_connection import Code, device, protocol

context = importlib.import_module("custom_ble_test.domain.command_context")
Waiter = importlib.import_module(
    "custom_ble_test.application.lock_commands"
).LockCommandWaiter


class CommandWaitTests(unittest.IsolatedAsyncioTestCase):
    def setup_waiter(self, timeout=0.1):
        peer = device()
        peer._client = MagicMock(is_connected=True)
        peer._is_paired = True
        waiter = Waiter(peer, MagicMock(), timeout)
        self.addAsyncCleanup(waiter.close)
        return peer, waiter

    def disconnect(self, peer):
        peer._is_paired = False
        peer._fire_disconnected_callbacks()

    def reconnect(self, peer):
        peer._is_paired = True
        peer._fire_connected_callbacks()

    async def test_waits_for_authentication_and_runs_once(self):
        peer, waiter = self.setup_waiter()
        self.disconnect(peer)
        action = AsyncMock()
        task = asyncio.create_task(waiter.execute(action))
        await asyncio.sleep(0)
        action.assert_not_awaited()
        self.assertTrue(waiter.available)
        self.assertTrue(waiter.pending)
        self.reconnect(peer)
        await task
        action.assert_awaited_once()
        self.assertFalse(waiter.pending)

    async def test_timeout_removes_command_before_late_reconnect(self):
        peer, waiter = self.setup_waiter(0.01)
        self.disconnect(peer)
        action = AsyncMock()
        with self.assertRaises(TimeoutError):
            await waiter.execute(action)
        self.assertFalse(waiter.available)
        self.reconnect(peer)
        await asyncio.sleep(0)
        action.assert_not_awaited()

    async def test_duplicate_and_opposite_commands_are_rejected(self):
        peer, waiter = self.setup_waiter()
        self.disconnect(peer)
        first, second = AsyncMock(), AsyncMock()
        task = asyncio.create_task(waiter.execute(first))
        await asyncio.sleep(0)
        with self.assertRaises(context.CommandBusy):
            await waiter.execute(second)
        self.reconnect(peer)
        await task
        first.assert_awaited_once()
        second.assert_not_awaited()

    async def test_unload_cancels_wait_without_motor_write(self):
        peer, waiter = self.setup_waiter()
        self.disconnect(peer)
        action = AsyncMock()
        task = asyncio.create_task(waiter.execute(action))
        await asyncio.sleep(0)
        await waiter.close()
        self.assertTrue(task.cancelled())
        self.reconnect(peer)
        action.assert_not_awaited()
        self.assertFalse(waiter.available)
        with self.assertRaises(context.CommandClosed):
            await waiter.execute(action)

    async def test_caller_cancellation_discards_command(self):
        peer, waiter = self.setup_waiter()
        self.disconnect(peer)
        action = AsyncMock()
        task = asyncio.create_task(waiter.execute(action))
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.reconnect(peer)
        action.assert_not_awaited()
        self.assertFalse(waiter.pending)

    async def test_write_failure_and_lost_ack_are_never_replayed(self):
        for failure in (protocol.BleakError("synthetic"), TimeoutError()):
            peer, waiter = self.setup_waiter()
            action = AsyncMock(side_effect=failure)
            with self.assertRaises(type(failure)):
                await waiter.execute(action)
            self.disconnect(peer)
            self.reconnect(peer)
            action.assert_awaited_once()

    async def test_prewrite_race_waits_for_next_authenticated_session(self):
        peer, waiter = self.setup_waiter()

        async def race():
            self.disconnect(peer)
            raise context.CommandNotReady()

        action = AsyncMock(side_effect=race)
        task = asyncio.create_task(waiter.execute(action))
        await asyncio.sleep(0)
        self.assertEqual(action.await_count, 1)
        action.side_effect = None
        self.reconnect(peer)
        await task
        self.assertEqual(action.await_count, 2)

    async def test_deadline_is_task_local_and_restored(self):
        _, waiter = self.setup_waiter()
        observed = []

        async def action():
            observed.append(context.send_deadline.get())
            await asyncio.sleep(0)

        task = asyncio.create_task(waiter.execute(action))
        await asyncio.sleep(0)
        self.assertIsNone(context.send_deadline.get())
        await task
        self.assertIsInstance(observed[0], float)
        self.assertIsNone(context.send_deadline.get())

    async def test_repeated_disconnect_does_not_extend_availability(self):
        peer, waiter = self.setup_waiter(0.01)
        self.disconnect(peer)
        await asyncio.sleep(0.02)
        self.disconnect(peer)
        self.assertFalse(waiter.available)

    async def test_deadline_expires_behind_request_lock_no_late_write(self):
        peer, waiter = self.setup_waiter(0.01)
        peer._int_send_packet_while_connected = AsyncMock()
        await peer._request_lock.acquire()
        try:
            with self.assertRaises(TimeoutError):
                await waiter.execute(lambda: peer.send_command(b"synthetic"))
        finally:
            peer._request_lock.release()
        peer._int_send_packet_while_connected.assert_not_awaited()
        self.assertEqual(peer._input_expected_responses, {})

    async def test_deadline_expires_behind_write_lock_no_late_write(self):
        peer, waiter = self.setup_waiter(0.01)
        peer._int_send_packet_while_connected = AsyncMock()
        await peer._operation_lock.acquire()
        try:
            with self.assertRaises(TimeoutError):
                await waiter.execute(lambda: peer.send_command(b"synthetic"))
        finally:
            peer._operation_lock.release()
        peer._int_send_packet_while_connected.assert_not_awaited()

    async def test_send_deadline_does_not_cancel_ack_after_write(self):
        peer, waiter = self.setup_waiter(0.01)
        peer._build_packets = MagicMock(return_value=[b"synthetic"])

        async def write(packets):
            await asyncio.sleep(0.02)
            next(iter(peer._input_expected_responses.values())).set_result(True)

        peer._int_send_packet_while_connected = AsyncMock(side_effect=write)
        await waiter.execute(lambda: peer.send_command(b"synthetic"))
        peer._int_send_packet_while_connected.assert_awaited_once()
        self.assertEqual(peer._input_expected_responses, {})

    async def test_optional_path_never_initiates_a_second_connection(self):
        peer, waiter = self.setup_waiter()
        peer._ensure_connected = AsyncMock()
        peer._send_packet_while_connected_locked = AsyncMock(return_value=True)
        await waiter.execute(lambda: peer.send_command(b"synthetic"))
        peer._ensure_connected.assert_not_awaited()
        self.assertEqual(peer._send_packet_while_connected_locked.call_args.args[0],
                         Code.FUN_SENDER_DPS_V4)

    async def test_default_send_path_is_unchanged(self):
        peer = device()
        peer._send_packet = AsyncMock()
        await peer.send_command(b"synthetic")
        peer._send_packet.assert_awaited_once_with(Code.FUN_SENDER_DPS_V4, b"synthetic", True)
