"""Strict report boundaries and response acknowledgements, no real credentials."""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

from test_connection import Code, device, protocol

decode = protocol.decode_report


def packet(*points, passive=True):
    return bytes([0, 0, 0, 0, 7, int(passive), 0]) + b"".join(
        bytes([dp, kind]) + len(value).to_bytes(2, "big") + value
        for dp, kind, value in points
    )


class ReportTests(unittest.IsolatedAsyncioTestCase):
    def test_bulk_status_and_unknown_raw_cannot_inject_points(self):
        peer = device()
        raw = packet((47, 1, b"\x00"))
        data = packet(
            (71, 0, raw),
            (9, 4, b"\x02"),
            (31, 4, b"\x00"),
            (78, 1, b"\x01"),
            (47, 1, b"\x01"),
        )
        peer._parse_datapoints_v4(data)
        self.assertFalse(peer.model.lock_report[1])
        self.assertEqual(peer.model.volume, "mute")
        self.assertTrue(peer.model.reversed_direction)
        self.assertEqual(peer.model.battery, "low")

    def test_truncated_bulk_is_atomic_and_never_publishes_prefix(self):
        peer = device()
        data = packet((47, 1, b"\x00"), (31, 4, b"\x00"))[:-1]
        with self.assertRaises(ValueError):
            peer._parse_datapoints_v4(data)
        self.assertIsNone(peer.model.lock_report)

    def test_timestamped_reports_skip_timestamp_without_scanning(self):
        data = packet((47, 1, b"\x00"), passive=False)
        for timestamp in (b"\x01" + bytes(4), b"\x00" + b"1234567890123"):
            report = decode(data[:7] + timestamp + data[7:], timestamped=True)
            self.assertEqual(report.points, ((47, 1, b"\x00"),))

    def test_old_timestamped_position_cannot_replace_current_report(self):
        for stamp in (b"\x01" + bytes(4), b"\x00" + b"1234567890123"):
            peer = device()
            old = packet((47, 1, b"\x01"), passive=False)
            historical = old[:7] + stamp + old[7:]
            peer._parse_datapoints_v4(historical, timestamped=True)
            self.assertIsNone(peer.model.lock_report)
            peer._parse_datapoints_v4(packet((47, 1, b"\x00")))
            latest = peer.model.lock_report
            peer._parse_datapoints_v4(historical, timestamped=True)
            self.assertEqual(peer.model.lock_report, latest)

    def test_report_ack_preserves_header_and_honors_no_ack_bit(self):
        peer = device()
        peer._queue_response = MagicMock()
        data = packet((47, 1, b"\x00"))
        peer._handle_command_or_response(21, 0, Code.FUN_RECEIVE_DP_V4, data)
        peer._queue_response.assert_called_once_with(
            Code.FUN_RECEIVE_DP_V4, data[:7] + b"\x00", 21
        )
        peer._queue_response.reset_mock()
        peer._handle_command_or_response(
            22, 0, Code.FUN_RECEIVE_DP_V4, data[:5] + b"\x81" + data[6:]
        )
        peer._queue_response.assert_not_called()

    async def test_transport_error_ack_is_not_success(self):
        peer = device()
        future = asyncio.get_running_loop().create_future()
        peer._input_expected_responses[1] = future
        peer._handle_command_or_response(
            2, 1, Code.FUN_SENDER_DPS_V4, bytes(5) + b"\x01"
        )
        with self.assertRaises(protocol.ProtocolError):
            await future

    async def test_status_query_waits_for_passive_report_not_ack_or_event(self):
        peer = device()
        peer._client = MagicMock()
        peer._ensure_connected = AsyncMock()
        peer._build_packets = MagicMock(return_value=[b"status"])
        async def write(packets):
            for response in peer._input_expected_responses.values():
                response.set_result(0)
        peer._int_send_packet_while_connected = AsyncMock(side_effect=write)
        task = asyncio.create_task(peer.query_status())
        while not peer._int_send_packet_while_connected.await_count:
            await asyncio.sleep(0)
        self.assertFalse(task.done())
        peer._parse_datapoints_v4(packet((47, 1, b"\x01"), passive=False))
        await asyncio.sleep(0)
        self.assertFalse(task.done())
        peer._parse_datapoints_v4(packet((47, 1, b"\x00")))
        await asyncio.wait_for(task, 1)

    async def test_status_query_ignores_report_before_request_admission(self):
        peer = device()
        peer._client = MagicMock()
        peer._ensure_connected = AsyncMock()
        peer._build_packets = MagicMock(return_value=[b"status"])
        sent = asyncio.Event()
        async def write(packets):
            sent.set()
            for response in peer._input_expected_responses.values():
                response.set_result(0)
        peer._int_send_packet_while_connected = AsyncMock(side_effect=write)
        await peer._request_lock.acquire()
        task = asyncio.create_task(peer.query_status())
        await asyncio.sleep(0)
        peer._parse_datapoints_v4(packet((47, 1, b"\x01")))
        peer._request_lock.release()
        await sent.wait()
        await asyncio.sleep(0)
        self.assertFalse(task.done())
        peer._parse_datapoints_v4(packet((47, 1, b"\x00")))
        await asyncio.wait_for(task, 1)

    async def test_status_query_accepts_report_before_transport_ack(self):
        peer = device()
        peer._client = MagicMock()
        peer._ensure_connected = AsyncMock()
        peer._build_packets = MagicMock(return_value=[b"status"])
        async def write(packets):
            peer._parse_datapoints_v4(packet((47, 1, b"\x00")))
            for response in peer._input_expected_responses.values():
                response.set_result(0)
        peer._int_send_packet_while_connected = AsyncMock(side_effect=write)
        await asyncio.wait_for(peer.query_status(), 1)

    async def test_queued_report_before_writer_task_cannot_complete_query(self):
        peer = device()
        peer._client = MagicMock()
        peer._ensure_connected = AsyncMock()
        peer._build_packets = MagicMock(return_value=[b"status"])
        sent = asyncio.Event()
        async def write(packets):
            sent.set()
            for response in peer._input_expected_responses.values():
                response.set_result(0)
        peer._int_send_packet_while_connected = AsyncMock(side_effect=write)
        task = asyncio.create_task(peer.query_status())
        asyncio.get_running_loop().call_soon(
            peer._parse_datapoints_v4, packet((47, 1, b"\x01")))
        await sent.wait()
        await asyncio.sleep(0)
        self.assertFalse(task.done())
        peer._parse_datapoints_v4(packet((47, 1, b"\x00")))
        await asyncio.wait_for(task, 1)

    async def test_idle_disconnect_can_reconnect_but_stop_cannot(self):
        peer = device()
        peer._execute_disconnect = AsyncMock()
        await peer.disconnect()
        self.assertFalse(peer._expected_disconnect)
        self.assertFalse(peer._stopped)
        await peer.stop()
        with self.assertRaises(protocol.ProtocolError):
            await peer.connect()
