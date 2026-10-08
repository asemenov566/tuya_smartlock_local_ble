"""Bounded, optional waiting for one lock command. No model or BLE imports."""

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress

from ..domain.command_context import (
    CommandBusy,
    CommandClosed,
    CommandNotReady,
    send_deadline,
)
from ..domain.contracts import LockProtocol


class LockCommandWaiter:
    """Wait for the connection owner's authenticated session; never reconnect."""

    def __init__(
        self, session: LockProtocol, changed: Callable[[], None], timeout: float = 10
    ):
        self._session = session
        self._changed = changed
        self._timeout = timeout
        self._ready = asyncio.Event()
        self._closed = False
        self._task = None
        self._disconnected_at = None
        self._expiry = None
        self._unsubscribers = [
            session.register_connected_callback(self._connected),
            session.register_disconnected_callback(self._disconnected),
        ]

    @property
    def pending(self):
        return self._task is not None

    @property
    def available(self):
        """Accept commands through a short outage, never an indefinite one."""
        return not self._closed and (
            self._session.command_ready
            or (
                self._disconnected_at is not None
                and asyncio.get_running_loop().time()
                < self._disconnected_at + self._timeout
            )
        )

    def _connected(self):
        self._disconnected_at = None
        if self._expiry is not None:
            self._expiry.cancel()
            self._expiry = None
        self._ready.set()
        self._changed()

    def _disconnected(self):
        self._ready.clear()
        if self._closed:
            return
        # Repeated failure notifications must not extend the availability grace.
        if self._disconnected_at is None:
            loop = asyncio.get_running_loop()
            self._disconnected_at = loop.time()
            self._expiry = loop.call_later(self._timeout, self._changed)
        self._changed()

    async def execute(self, action: Callable[[], Awaitable[None]]) -> None:
        if self._closed:
            raise CommandClosed()
        if self._task is not None:
            raise CommandBusy()
        if not self.available:
            raise TimeoutError("Lock is unavailable")
        self._task = asyncio.current_task()
        deadline = asyncio.get_running_loop().time() + self._timeout
        token = send_deadline.set(deadline)
        try:
            self._changed()
            while True:
                async with asyncio.timeout_at(deadline):
                    self._ready.clear()
                    if not self._session.command_ready:
                        await self._ready.wait()
                if self._closed:
                    raise CommandClosed()
                try:
                    await action()
                    return
                except CommandNotReady:
                    # The transport explicitly guarantees no write was attempted.
                    continue
        finally:
            send_deadline.reset(token)
            self._task = None
            self._changed()

    async def close(self):
        self._closed = True
        if self._expiry is not None:
            self._expiry.cancel()
        for unsubscribe in self._unsubscribers:
            unsubscribe()
        self._unsubscribers.clear()
        task = self._task
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
