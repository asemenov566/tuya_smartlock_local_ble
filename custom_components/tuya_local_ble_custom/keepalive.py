"""One cancellable, read-only heartbeat per persistent BLE session."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

_LOGGER = logging.getLogger(__name__)


async def maintain_connection(
    refresh: Callable[[], Awaitable[None]],
    *,
    interval: float = 30,
    max_delay: float = 120,
    timeout: float = 90,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Request status, never write an actuator/password datapoint.

    The caller owns and cancels this task on unload. Sequential refreshes
    cannot accumulate if an adapter is slow. Cancellation must propagate.
    """
    delay = interval
    while True:
        await sleep(delay)
        try:
            async with asyncio.timeout(timeout):
                await refresh()
        except Exception as exc:
            # Do not log credentials, decrypted frames or exception messages.
            _LOGGER.debug("BLE heartbeat failed (%s); retrying", type(exc).__name__)
            delay = min(max_delay, delay * 2)
        else:
            delay = interval
