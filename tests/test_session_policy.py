"""Connection modes with simulated radio failures and overlapping operations."""

import asyncio
import importlib
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

package = types.ModuleType("policy_test")
package.__path__ = [
    str(
        Path(__file__).resolve().parents[1]
        / "custom_components/tuya_smartlock_local_ble"
    )
]
sys.modules[package.__name__] = package
Policy = importlib.import_module("policy_test.application.session_policy").SessionPolicy
NotReady = importlib.import_module("policy_test.domain.command_context").CommandNotReady


class PolicyTests(unittest.IsolatedAsyncioTestCase):
    def policy(self, **options):
        peer = SimpleNamespace(command_ready=False, query_status=AsyncMock())

        async def connect():
            peer.command_ready = True

        async def disconnect():
            peer.command_ready = False

        peer.connect = AsyncMock(side_effect=connect)
        peer.disconnect = AsyncMock(side_effect=disconnect)
        policy = Policy(peer, persistent=False, **options)
        self.addAsyncCleanup(policy.close)
        return policy, peer

    async def test_poll_waits_for_report_then_disconnects(self):
        p, peer = self.policy(hold_time=30)
        started, report = asyncio.Event(), asyncio.Event()

        async def query():
            started.set()
            await report.wait()

        peer.query_status.side_effect = query
        task = asyncio.create_task(p.refresh())
        await started.wait()
        peer.disconnect.assert_not_awaited()
        report.set()
        await task
        await asyncio.sleep(0.01)
        peer.disconnect.assert_awaited_once()

    async def test_poll_does_not_disconnect_active_command(self):
        p, peer = self.policy(hold_time=0)
        started, finish = asyncio.Event(), asyncio.Event()

        async def action():
            started.set()
            await finish.wait()

        task = asyncio.create_task(p.execute(action))
        await started.wait()
        await p.refresh()
        await asyncio.sleep(0.01)
        peer.disconnect.assert_not_awaited()
        finish.set()
        await task
        await asyncio.sleep(0.01)
        peer.disconnect.assert_awaited_once()

    async def test_action_does_not_disconnect_active_poll(self):
        p, peer = self.policy(hold_time=0)
        started, finish = asyncio.Event(), asyncio.Event()

        async def query():
            started.set()
            await finish.wait()

        peer.query_status.side_effect = query
        task = asyncio.create_task(p.refresh())
        await started.wait()
        await p.execute(AsyncMock())
        await asyncio.sleep(0.01)
        peer.disconnect.assert_not_awaited()
        finish.set()
        await task
        await asyncio.sleep(0.01)
        peer.disconnect.assert_awaited_once()

    async def test_command_hold_and_next_command_extend_deadline(self):
        p, peer = self.policy(hold_time=0.06)
        await p.execute(AsyncMock())
        await asyncio.sleep(0.04)
        await p.execute(AsyncMock())
        await asyncio.sleep(0.04)
        peer.disconnect.assert_not_awaited()
        await asyncio.sleep(0.04)
        peer.disconnect.assert_awaited_once()
        peer.connect.assert_awaited_once()

    async def test_failed_connection_does_not_replay_action_later(self):
        p, peer = self.policy()
        peer.connect.side_effect = OSError()
        action = AsyncMock()
        with self.assertRaises(OSError):
            await p.execute(action)
        peer.command_ready = True
        await asyncio.sleep(0)
        action.assert_not_awaited()
        self.assertEqual(p._users, 0)
        self.assertFalse(p._operations)

    async def test_lost_ack_never_retries_write(self):
        p, peer = self.policy(hold_time=0)
        action = AsyncMock(side_effect=TimeoutError)
        with self.assertRaises(TimeoutError):
            await p.execute(action)
        await asyncio.sleep(0.01)
        action.assert_awaited_once()
        peer.disconnect.assert_awaited_once()

    async def test_persistent_offline_without_waiting_fails_immediately(self):
        p, peer = self.policy()
        p.persistent = True
        action = AsyncMock()
        with self.assertRaises(NotReady):
            await p.execute(action)
        action.assert_not_awaited()
        peer.connect.assert_not_awaited()
        self.assertTrue(p.available)

    async def test_explicit_refresh_can_connect_persistent_session(self):
        p, peer = self.policy()
        p.persistent = True
        await p.refresh()
        peer.query_status.assert_awaited_once()
        await asyncio.sleep(0)
        peer.disconnect.assert_not_awaited()

    async def test_polling_off_never_connects(self):
        p, peer = self.policy(poll_interval=0)
        p.start_polling()
        await asyncio.sleep(0.01)
        peer.connect.assert_not_awaited()
        self.assertIsNone(p._poller)

    async def test_close_cancels_pending_query(self):
        p, peer = self.policy()
        started = asyncio.Event()

        async def query():
            started.set()
            await asyncio.Event().wait()

        peer.query_status.side_effect = query
        task = asyncio.create_task(p.refresh())
        await started.wait()
        await p.close()
        self.assertTrue(task.cancelled())
        self.assertEqual(p._users, 0)
        self.assertFalse(p.available)

    async def test_failed_poll_preserves_hold_from_overlapping_command(self):
        p, peer = self.policy(hold_time=60)
        started, fail = asyncio.Event(), asyncio.Event()

        async def query():
            started.set()
            await fail.wait()
            raise TimeoutError()

        peer.query_status.side_effect = query
        polling = asyncio.create_task(p.refresh())
        await started.wait()
        await p.execute(AsyncMock())
        fail.set()
        with self.assertRaises(TimeoutError):
            await polling
        peer.disconnect.assert_not_awaited()
        self.assertGreater(p._hold_until, asyncio.get_running_loop().time())
