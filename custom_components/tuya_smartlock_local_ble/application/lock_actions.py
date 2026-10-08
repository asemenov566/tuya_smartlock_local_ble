"""Shared command intent for explicit actions and the toggle button."""

from ..domain.command_context import CommandBusy, CommandStateUnknown


class LockActions:
    """Reports may seed initial intent; they never overwrite a chosen action."""

    def __init__(self, model, status, commands, changed):
        self._model = model
        self._status = status
        self._commands = commands
        self._changed = changed
        self._intent = None
        self._busy = False

    @property
    def locked(self):
        return self._intent if self._intent is not None else self._status.locked

    @property
    def pending(self):
        return self._busy

    async def set_locked(self, locked):
        if self._busy:
            raise CommandBusy()
        self._busy = True
        model_action = self._model.lock if locked else self._model.unlock

        async def action():
            await self._status.execute(model_action)

        try:
            if self._commands is None:
                await action()
            else:
                await self._commands.execute(action)
            self._intent = locked
        finally:
            self._busy = False
            self._changed()

    async def toggle(self):
        if self._busy:
            raise CommandBusy()
        if self.locked is None:
            raise CommandStateUnknown()
        await self.set_locked(not self.locked)
