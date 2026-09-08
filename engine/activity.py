"""In-app activity/event bus.

Every important event (tweak applied / failed / reverted, profile launched,
scan completed, restart required, error, update available) is emitted here so
UI surfaces like the Dashboard activity feed stay in sync automatically.

Thread-safe: the Qt bridge uses a queued signal, so emitting from a worker
thread is fine. Falls back to plain callbacks when PySide6 is unavailable
(CLI-only environments).
"""
from __future__ import annotations

import time
from collections import deque

try:
    from PySide6.QtCore import QObject, Signal

    class _QtBus(QObject):
        added = Signal(dict)

    _HAS_QT = True
except Exception:  # noqa: BLE001 - CLI without Qt
    _HAS_QT = False

MAX_HISTORY = 60


class _ActivityBus:
    def __init__(self):
        self._history: deque[dict] = deque(maxlen=MAX_HISTORY)
        self._handlers = []
        self._qt = _QtBus() if _HAS_QT else None

    def emit(self, kind: str, text: str) -> None:
        """kind: success | error | warn | info | profile | scan | restart."""
        item = {"kind": kind, "text": text, "time": time.strftime("%H:%M:%S")}
        self._history.appendleft(item)
        if self._qt is not None:
            self._qt.added.emit(item)  # queued across threads
        for handler in self._handlers:
            try:
                handler(item)
            except Exception:  # noqa: BLE001
                pass

    def on_add(self, handler):
        """Register a plain-callback subscriber (used when Qt is absent)."""
        self._handlers.append(handler)

    def qt_signal(self):
        """Return the Qt Signal (or None) so UI widgets can subscribe."""
        return self._qt.added if self._qt is not None else None

    def history(self, n: int = 20) -> list[dict]:
        return list(self._history)[:n]


bus = _ActivityBus()

emit = bus.emit
history = bus.history
