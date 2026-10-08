"""Track fresh device reports independently of commanded lock state."""


class ReportedLockStatus:
    """An ACK never changes status; commands and disconnects invalidate it."""

    def __init__(self, session, model, changed):
        self._session = session
        self._model = model
        self._changed = changed
        self._last_report = None
        self.locked = None
        self._closed = False
        self._unsubscribers = [
            session.register_callback(self._updated),
            session.register_disconnected_callback(self.invalidate),
        ]
        self._updated([])

    def invalidate(self):
        """Require a new report, even when unrelated datapoints are published."""
        report = self._model.lock_report
        self._last_report = report[0] if report is not None else None
        self.locked = None
        self._changed()

    def _updated(self, updates):
        if self._closed or not self._session.command_ready:
            return
        report = self._model.lock_report
        if report is not None and report[0] != self._last_report:
            self._last_report, self.locked = report
            self._changed()

    async def execute(self, action):
        """Called after command admission, immediately before the model action."""
        self.invalidate()
        await action()

    def close(self):
        self._closed = True
        for unsubscribe in self._unsubscribers:
            unsubscribe()
        self._unsubscribers.clear()
        self.locked = None
