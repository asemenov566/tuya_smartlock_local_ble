"""Report-only status never treats an acknowledged command as movement."""

import asyncio
import importlib
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

package = types.ModuleType("status_test")
package.__path__ = [
    str(
        Path(__file__).resolve().parents[1]
        / "custom_components/tuya_smartlock_local_ble"
    )
]
sys.modules[package.__name__] = package
Status = importlib.import_module(
    "status_test.application.lock_status"
).ReportedLockStatus
Points = importlib.import_module("status_test.domain.datapoints").DataPoints
Model = importlib.import_module("status_test.models.a1_ultra").A1UltraModel
PointType = importlib.import_module("status_test.protocols.tuya_ble.const").PointType
Actions = importlib.import_module("status_test.application.lock_actions").LockActions
Unknown = importlib.import_module(
    "status_test.domain.command_context"
).CommandStateUnknown


class StatusTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.callbacks = {}
        self.unsubscribers = [Mock(), Mock()]

        def register(name, index):
            def subscribe(callback):
                self.callbacks[name] = callback
                return self.unsubscribers[index]

            return subscribe

        self.session = SimpleNamespace(
            command_ready=True,
            register_callback=register("report", 0),
            register_disconnected_callback=register("disconnect", 1),
        )
        self.model = SimpleNamespace(lock_report=None)
        self.status = Status(self.session, self.model, Mock())
        self.addCleanup(self.status.close)

    def report(self, timestamp, locked):
        self.model.lock_report = (timestamp, locked)
        self.callbacks["report"]([])

    async def test_ack_without_report_stays_unknown(self):
        self.report(1, True)
        action = AsyncMock()
        await self.status.execute(action)
        action.assert_awaited_once()
        self.assertIsNone(self.status.locked)
        self.callbacks["report"]([])  # unrelated battery/volume update
        self.assertIsNone(self.status.locked)

    async def test_report_before_ack_survives_command_completion(self):
        self.report(1, True)

        async def action():
            self.assertIsNone(self.status.locked)
            self.report(2, False)

        await self.status.execute(action)
        self.assertIs(self.status.locked, False)

    async def test_ack_failure_does_not_restore_previous_status(self):
        self.report(1, False)
        with self.assertRaises(TimeoutError):
            await self.status.execute(AsyncMock(side_effect=TimeoutError))
        self.assertIsNone(self.status.locked)

    def test_reconnect_needs_fresh_report(self):
        self.report(1, True)
        self.session.command_ready = False
        self.callbacks["disconnect"]()
        self.assertIsNone(self.status.locked)
        self.session.command_ready = True
        self.callbacks["report"]([])
        self.assertIsNone(self.status.locked)
        self.report(2, False)
        self.assertIs(self.status.locked, False)

    def test_manual_state_changes_without_any_command(self):
        self.report(1, True)
        self.assertIs(self.status.locked, True)
        self.report(2, False)
        self.assertIs(self.status.locked, False)

    def test_close_unsubscribes_and_ignores_late_reports(self):
        self.status.close()
        self.report(1, True)
        self.assertIsNone(self.status.locked)
        for unsubscribe in self.unsubscribers:
            unsubscribe.assert_called_once()

    def test_model_accepts_only_decoded_boolean_lock_status(self):
        peer = SimpleNamespace(datapoints=Points(), publish=Mock())
        model = Model(peer, SimpleNamespace())
        peer.payload_decoder(bytes.fromhex("000000000001002f01000101"))
        self.assertIs(model.lock_report[1], False)
        peer.payload_decoder(bytes.fromhex("000000000001002f01000100"))
        self.assertIs(model.lock_report[1], True)
        previous = model.lock_report
        peer.payload_decoder(bytes.fromhex("000000000001002f01000102"))
        self.assertEqual(model.lock_report, previous)
        peer.datapoints._update_from_device(118, 99, 0, PointType.DT_ENUM, 1)
        self.assertIsNone(model.lock_report)

    async def test_toggle_inverts_intent_until_fresh_report_resynchronizes(self):
        self.model.lock = AsyncMock()
        self.model.unlock = AsyncMock()
        actions = Actions(self.model, self.status, None, Mock())
        self.report(1, False)
        await actions.toggle()  # initially unlocked: start closing
        self.assertIs(actions.locked, True)
        await actions.toggle()  # reverse to opening, do not close again
        self.assertIs(actions.locked, False)
        self.model.lock.assert_awaited_once()
        self.model.unlock.assert_awaited_once()
        self.assertIsNone(self.status.locked)
        self.report(3, True)  # manual movement resynchronizes both controls
        self.assertIs(actions.locked, True)
        await actions.toggle()
        self.assertIs(actions.locked, False)

    async def test_explicit_actions_and_toggle_share_intent(self):
        self.model.lock = AsyncMock()
        self.model.unlock = AsyncMock()
        actions = Actions(self.model, self.status, None, Mock())
        await actions.set_locked(False)
        await actions.toggle()
        self.model.lock.assert_awaited_once()
        self.model.unlock.assert_awaited_once()
        self.assertIs(actions.locked, True)

    async def test_repeated_starting_position_after_ack_keeps_requested_direction(self):
        self.model.lock = AsyncMock()
        self.model.unlock = AsyncMock()
        actions = Actions(self.model, self.status, None, Mock())
        self.report(1, False)
        await actions.set_locked(True)
        self.report(2, False)
        self.assertIs(self.status.locked, False)
        self.assertIs(actions.locked, True)
        self.assertEqual(actions.expected_action, "closing")
        await actions.toggle()
        self.model.unlock.assert_awaited_once()
        self.assertEqual(actions.expected_action, "opening")
        self.report(3, False)
        self.assertEqual(actions.expected_action, "idle")

    async def test_on_demand_retains_last_report_but_command_invalidates(self):
        self.status.close()
        self.status = Status(
            self.session, self.model, Mock(), retain_on_disconnect=True
        )
        self.addCleanup(self.status.close)
        self.report(1, True)
        self.session.command_ready = False
        self.callbacks["disconnect"]()
        self.assertIs(self.status.locked, True)
        self.assertEqual(self.status.reported_at, 1)
        self.assertFalse(self.status.fresh)
        self.session.command_ready = True
        self.callbacks["report"]([])
        self.assertFalse(self.status.fresh)
        self.report(2, True)
        self.assertTrue(self.status.fresh)
        await self.status.execute(AsyncMock())
        self.assertIsNone(self.status.locked)

    async def test_unknown_toggle_does_not_guess_or_send(self):
        self.model.lock = AsyncMock()
        self.model.unlock = AsyncMock()
        actions = Actions(self.model, self.status, None, Mock())
        with self.assertRaises(Unknown):
            await actions.toggle()
        self.model.lock.assert_not_awaited()
        self.model.unlock.assert_not_awaited()

    async def test_reverse_does_not_wait_for_ack_or_physical_report(self):
        started, finish = asyncio.Event(), asyncio.Event()

        async def lock():
            started.set()
            await finish.wait()

        self.model.lock = AsyncMock(side_effect=lock)
        self.model.unlock = AsyncMock()
        actions = Actions(self.model, self.status, None, Mock())
        self.addAsyncCleanup(actions.close)
        self.report(1, False)
        task = asyncio.create_task(actions.toggle())
        await started.wait()
        self.assertIs(actions.locked, True)  # opposite control already visible
        self.assertTrue(actions.pending)
        await actions.toggle()
        await task  # superseded call ends normally
        self.model.unlock.assert_awaited_once()
        self.model.lock.assert_awaited_once()
        self.assertFalse(finish.is_set())
        self.assertIs(actions.locked, False)
        self.assertIsNone(self.status.locked)

    async def test_manual_reports_after_command_update_control_and_next_toggle(self):
        self.model.lock = AsyncMock()
        self.model.unlock = AsyncMock()
        actions = Actions(self.model, self.status, None, Mock())
        await actions.set_locked(False)
        self.report(1, True)
        self.assertIs(actions.locked, True)
        await actions.toggle()
        self.model.unlock.assert_awaited_with()
        self.model.lock.assert_not_awaited()
        self.report(2, False)
        self.assertIs(actions.locked, False)

    async def test_old_position_report_during_ack_does_not_reset_next_action(self):
        async def lock():
            self.report(1, False)

        self.model.lock = AsyncMock(side_effect=lock)
        self.model.unlock = AsyncMock()
        actions = Actions(self.model, self.status, None, Mock())
        await actions.set_locked(True)
        self.assertIs(self.status.locked, False)
        self.assertIs(actions.locked, True)
        await actions.toggle()
        self.model.lock.assert_awaited_once()
        self.model.unlock.assert_awaited_once()
        self.assertIs(actions.locked, False)

    async def test_three_rapid_requests_leave_only_latest_action(self):
        started = asyncio.Event()

        async def lock():
            started.set()
            await asyncio.Event().wait()

        self.model.lock = AsyncMock(side_effect=lock)
        self.model.unlock = AsyncMock()
        actions = Actions(self.model, self.status, None, Mock())
        self.addAsyncCleanup(actions.close)
        first = asyncio.create_task(actions.set_locked(True))
        await started.wait()
        second = asyncio.create_task(actions.toggle())
        third = asyncio.create_task(actions.toggle())
        await asyncio.sleep(0)
        self.assertIs(actions.locked, True)
        self.model.lock.side_effect = None
        await asyncio.gather(first, second, third)
        self.model.unlock.assert_not_awaited()
        self.assertFalse(actions.pending)

    async def test_close_cancels_inflight_and_unsubscribes(self):
        started = asyncio.Event()

        async def lock():
            started.set()
            await asyncio.Event().wait()

        self.model.lock = lock
        actions = Actions(self.model, self.status, None, Mock())
        task = asyncio.create_task(actions.set_locked(True))
        await started.wait()
        await actions.close()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(actions.pending)
        self.assertFalse(self.status._listeners)

    async def test_cancel_replacement_while_previous_drains_never_sends_it(self):
        started, cleanup, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def lock():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleanup.set()
                await release.wait()

        self.model.lock = AsyncMock(side_effect=lock)
        self.model.unlock = AsyncMock()
        actions = Actions(self.model, self.status, None, Mock())
        first = asyncio.create_task(actions.set_locked(True))
        await started.wait()
        second = asyncio.create_task(actions.set_locked(False))
        await cleanup.wait()
        second.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await second
        self.model.unlock.assert_not_awaited()
        release.set()
        await first
        self.model.unlock.assert_not_awaited()
        await actions.close()
