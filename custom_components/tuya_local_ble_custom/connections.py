"""Own active protocol sessions and their retry tasks. No lock commands."""

import asyncio
from contextlib import suppress
from dataclasses import dataclass

from .keepalive import maintain_connection


@dataclass
class Connection:
    protocol: object
    task: asyncio.Task | None = None


class ConnectionManager:
    def __init__(self):
        self._connections: dict[str, Connection] = {}

    async def start(self, key, protocol, keep_connected=True):
        if key in self._connections:
            raise ValueError("Connection already owned")
        connection = Connection(protocol)
        self._connections[key] = connection
        protocol.managed_connection = True
        try:
            async with asyncio.timeout(90):
                await protocol.initialize()
                await protocol.update()
            if keep_connected:
                connection.task = asyncio.create_task(
                    maintain_connection(protocol.refresh_session),
                    name=f"lock-connection-{key}",
                )
        except BaseException:
            await self.close(key)
            raise

    async def close(self, key):
        connection = self._connections.pop(key, None)
        if connection is None:
            return
        try:
            if connection.task is not None:
                connection.task.cancel()
                with suppress(asyncio.CancelledError):
                    await connection.task
        finally:
            # A failed heartbeat must not prevent releasing the BLE client.
            await connection.protocol.stop()

    async def close_all(self):
        errors = []
        for key in list(self._connections):
            try:
                await self.close(key)
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise ExceptionGroup("Could not close all BLE sessions cleanly", errors)
