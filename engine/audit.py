"""Background system-state auditor.

Runs the live detection engine off the UI thread so the app opens instantly
and toggles fill in progressively. A single worker audits queued tweak lists
(launch audit, per-category audits, post-apply re-checks) and emits one
signal per result so cards update in place without a full page rebuild.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal

from engine import state_checker
from rexlog import logger


class AuditWorker(QThread):
    """Iterates tweaks and emits their detected live state."""

    result_ready = Signal(str, object, int)  # tid, value (True/False/None), cache gen
    finished_all = Signal()

    def __init__(self, tweaks: list[dict], parent=None):
        super().__init__(parent)
        self.tweaks = tweaks
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            for tweak in self.tweaks:
                if self._stop:
                    break
                try:
                    # Snapshot the cache generation before the check: if the
                    # state is invalidated while the query runs (an apply/revert
                    # landed on the UI thread), the value is stale and the UI
                    # drops it instead of flipping a just-applied toggle back.
                    gen = state_checker.current_gen()
                    value = state_checker.check_tweak(tweak)
                except Exception as exc:  # noqa: BLE001
                    logger.warn(f"audit: {tweak.get('id')} failed: {exc}")
                    value = None
                if self._stop:
                    break
                self.result_ready.emit(tweak.get("id"), value, gen)
        finally:
            self.finished_all.emit()


class StateAuditor(QObject):
    """Owns the worker queue and fans results out to the UI."""

    live_changed = Signal(str, object)  # tid, value
    batch_done = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: AuditWorker | None = None
        self._queue: list[dict] = []
        self._pending: set[str] = set()
        self._shutdown = False

    def request(self, tweaks, force=False) -> None:
        """Queue tweaks for a background audit.

        Deduplicates against pending work unless ``force`` is set (used after
        apply/revert so just-changed tweaks are always re-checked even if an
        older audit is still running).
        """
        if self._shutdown:
            return
        fresh = []
        for t in tweaks:
            tid = t["id"]
            if force:
                self._pending.discard(tid)
            if tid in self._pending:
                continue
            self._pending.add(tid)
            fresh.append(t)
        if not fresh:
            return
        self._queue.extend(fresh)
        if self._worker is None or not self._worker.isRunning():
            self._start()

    def _start(self):
        batch, self._queue = self._queue[:], []
        self._worker = AuditWorker(batch, self)
        self._worker.result_ready.connect(self._on_result)
        self._worker.finished_all.connect(self._on_finished)
        self._worker.start()

    def _on_result(self, tid, value, gen):
        # A result computed under an older cache generation is stale: an
        # apply/revert invalidated the state while the worker was reading it,
        # so showing it could flip a just-changed toggle back to its old value.
        # Re-queue the tweak for a fresh check instead.
        if gen != state_checker.current_gen():
            self._pending.discard(tid)
            from database import BY_ID
            tweak = BY_ID.get(tid)
            if tweak is not None:
                self.request([tweak])
            return
        self._pending.discard(tid)
        self.live_changed.emit(tid, value)

    def _on_finished(self):
        self.batch_done.emit()
        if self._queue and not (self._worker and self._worker._stop):
            self._start()

    def shutdown(self):
        """Stop in-flight auditing so the app can exit without a crash.

        Latched: any ``request`` arriving after shutdown (e.g. from page
        refreshes triggered by late detection results) is dropped instead of
        spawning a fresh worker that would be destroyed while running.
        """
        self._shutdown = True
        self._queue = []
        self._pending.clear()
        worker, self._worker = self._worker, None
        if worker is not None and worker.isRunning():
            worker.stop()
            worker.wait(5000)
