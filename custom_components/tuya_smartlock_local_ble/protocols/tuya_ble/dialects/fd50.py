"""A1 Ultra DP payload dialect. Add other lock dialects in separate modules."""

import time

from ....domain.datapoints import DataPoint as DataPoint
from ..const import PointType


class FD50PayloadDecoder:
    def __init__(self, points, notify, setting_ids, state_flag=47, state_point=118):
        self.setting_ids = setting_ids
        self.state_flag = state_flag
        self.state_point = state_point
        self._datapoints = points
        self._fire_callbacks = notify

    def parse(self, data: bytes) -> None:
        """Parse A1 Ultra/TuyaOS FD50 command-style V4 datapoint payloads.

        Captured command/event bodies use:
        00000000 01 <dp_id> <len:3> <value:len>

        The lock may also emit other V4 event bodies on the same message code.
        Those frames should not make the integration disconnect, so this parser
        scans for the safe command-style datapoints we understand and ignores
        malformed/unknown frames instead of raising.
        """
        datapoints: list[DataPoint] = []
        pos = 0
        parsed_ranges: list[tuple[int, int]] = []
        while len(data) - pos >= 5:
            if len(data) - pos >= 8:
                flags = int.from_bytes(data[pos + 1 : pos + 4], "big")
                dp_type = data[pos + 4]
                typed_len = int.from_bytes(data[pos + 5 : pos + 7], "big")
                typed_value_pos = pos + 7
                typed_next_pos = typed_value_pos + typed_len
                if (
                    flags == self.state_flag
                    and dp_type == PointType.DT_BOOL.value
                    and (typed_len == 1)
                    and (typed_next_pos <= len(data))
                ):
                    raw_value = data[typed_value_pos:typed_next_pos]
                    value = raw_value != b"\x00"
                    self._datapoints._update_from_device(
                        self.state_point,
                        time.time(),
                        flags,
                        PointType.DT_ENUM,
                        1 if value else 0,
                    )
                    datapoints.append(self._datapoints[self.state_point])
                    parsed_ranges.append((pos, typed_next_pos))
                    pos = typed_next_pos
                    continue
            op = data[pos]
            dp_id = data[pos + 1]
            data_len = int.from_bytes(data[pos + 2 : pos + 5], "big")
            value_pos = pos + 5
            next_pos = value_pos + data_len
            if (
                op == 1
                and dp_id in self.setting_ids
                and (1 <= data_len <= len(data) - value_pos)
            ):
                raw_value = data[value_pos:next_pos]
                value = int.from_bytes(raw_value, "big", signed=False)
                self._datapoints._update_from_device(
                    dp_id, time.time(), 0, PointType.DT_ENUM, value
                )
                datapoints.append(self._datapoints[dp_id])
                parsed_ranges.append((pos, next_pos))
                pos = next_pos
                continue
            if len(data) - pos >= 8 and data[pos + 1 : pos + 3] == b"\x00\x00":
                dp_id = data[pos + 3]
                data_len = int.from_bytes(data[pos + 4 : pos + 7], "big")
                value_pos = pos + 7
                next_pos = value_pos + data_len
                if dp_id in self.setting_ids and 1 <= data_len <= len(data) - value_pos:
                    raw_value = data[value_pos:next_pos]
                    value = int.from_bytes(raw_value, "big", signed=False)
                    self._datapoints._update_from_device(
                        dp_id, time.time(), 0, PointType.DT_ENUM, value
                    )
                    datapoints.append(self._datapoints[dp_id])
                    parsed_ranges.append((pos, next_pos))
                    pos = next_pos
                    continue
                if len(data) - pos >= 8:
                    dp_type = data[pos + 4]
                    data_len = int.from_bytes(data[pos + 5 : pos + 7], "big")
                    value_pos = pos + 7
                    next_pos = value_pos + data_len
                    if (
                        dp_id in self.setting_ids
                        and dp_type in (0, 1, 4)
                        and (1 <= data_len <= len(data) - value_pos)
                    ):
                        raw_value = data[value_pos:next_pos]
                        value = int.from_bytes(raw_value, "big", signed=False)
                        self._datapoints._update_from_device(
                            dp_id, time.time(), 0, PointType.DT_ENUM, value
                        )
                        datapoints.append(self._datapoints[dp_id])
                        parsed_ranges.append((pos, next_pos))
                        pos = next_pos
                        continue
            pos += 1
        self._fire_callbacks(datapoints)
