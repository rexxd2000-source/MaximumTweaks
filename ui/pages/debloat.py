"""Smart Debloater — the page renders ui/smart_debloater.html (an exact clone
of the frozen mockup) inside an embedded QtWebEngine view, and exposes a
QWebChannel bridge under ``window.pywebview.api`` so the page can call
``scan()`` / ``remove(ids)`` exactly like a real pywebview window.

The heavy lifting lives in ``engine.debloat.smart`` (registry/Apk scan,
dependency protection, restore point, per-app removal). Only a thin transport
lives here:

  * ``_DebloatBridge`` — QObject registered as ``api``; its Slot() methods run
    on the Qt main thread and fan out to background QThreads.
  * ``_ScanWorker``   — runs ``smart.scan`` with a progress callback that is
    forwarded to the page as ``onScanProgress(percent, stepIndex)``, then
    ``onScanDone(items)`` / ``onScanError(msg)``.
  * ``_RemoveWorker`` — runs ``smart.remove`` when this process is already
    elevated; otherwise the removal is handed to an elevated copy of the app
    via ``--cli debloat-remove <job.json>`` and the result file is polled.
    Both paths end in ``onRemoveDone(results)`` / ``onRemoveFailed(msg)``.

Ids sent by the page are never trusted: ``smart.remove`` rescans the system
and re-runs the protection rules before anything is removed.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWebChannel import QWebChannel  # noqa: F401 - registers qtwebchannel.js
from PySide6.QtWidgets import QVBoxLayout, QWidget

from config.app_config import ROOT
from ui.pages._web import make_webview

HTML_REL = "ui/smart_debloater.html"


def _html_path() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    base = Path(meipass) if meipass else ROOT
    return base / HTML_REL


# ---------------------------------------------------------------- workers

class _ScanWorker(QThread):
    progress = Signal(int, int)   # percent, stepIndex
    done = Signal(list)
    error = Signal(str)

    def run(self):
        try:
            from engine.debloat import smart
            items = smart.scan(on_progress=lambda p, s: self.progress.emit(p, s))
            self.done.emit(items)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))


class _RemoveWorker(QThread):
    done = Signal(list)
    error = Signal(str)

    def __init__(self, ids: list[str], parent=None):
        super().__init__(parent)
        self._ids = list(ids or [])

    def run(self):
        try:
            from engine.debloat import smart
            self.done.emit(smart.remove(self._ids))
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))


# ---------------------------------------------------------------- bridge

class _DebloatBridge(QObject):
    """Registered as ``window.pywebview.api`` on the page's QWebChannel."""

    def __init__(self, page, parent=None):
        super().__init__(parent)
        self._page = page

    @Slot()
    def scan(self):
        self._page.request_scan()

    @Slot(list)
    def remove(self, ids):
        self._page.request_remove(list(ids or []))


# ---------------------------------------------------------------- page

class DebloatPage(QWidget):
    """Embedded-webview port of smart-debloater.html (exact clone)."""

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._busy = False
        self._job = None
        self._worker = None
        self._last_fwd = -1
        self._last_step = -1

        self._web = make_webview(self)
        self._web.setStyleSheet("background:#0a0912; border:none;")
        self._web.page().setBackgroundColor(QColor("#0a0912"))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._web)

        settings = self._web.settings()
        settings.setAttribute(settings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(settings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        settings.setAttribute(settings.WebAttribute.JavascriptCanOpenWindows, False)

        self._bridge = _DebloatBridge(self, self)
        self._channel = QWebChannel(self)
        self._channel.registerObject("api", self._bridge)
        self._web.page().setWebChannel(self._channel)

        html = _html_path()
        if html.is_file():
            self._web.load(QUrl.fromLocalFile(str(html)))
        else:
            # Never fall over silently if the HTML is missing (e.g. a bare dev
            # checkout) — show a readable message instead of a blank page.
            self._web.setHtml(
                "<body style='background:#0a0912;color:#9a93b8;"
                "font-family:sans-serif;padding:40px;'>"
                f"smart_debloater.html not found at<br><code>{html}</code>"
                "</body>")

        self._poll = QTimer(self)
        self._poll.setInterval(400)
        self._poll.timeout.connect(self._poll_job)

    # ------------------------------------------------------- JS transport
    def _js(self, script: str):
        self._web.page().runJavaScript(script)

    # ------------------------------------------------------- scan path
    def request_scan(self):
        if self._busy:
            return
        self._busy = True
        self._last_fwd = -1
        self._last_step = -1
        self._worker = _ScanWorker(self)
        self._worker.progress.connect(self._on_scan_progress)
        self._worker.done.connect(self._on_scan_done)
        self._worker.error.connect(self._on_scan_error)
        self._worker.start()

    def _on_scan_progress(self, pct, step):
        # Throttle what gets pushed to the page: a continuous rAF chase loop
        # eases the ring toward the latest target, so forwarding every event
        # would only flood the renderer and make it look frozen.
        if pct - self._last_fwd >= 2 or step != self._last_step:
            self._last_fwd = pct
            self._last_step = step
            self._js(f"window.onScanProgress && window.onScanProgress({pct}, {step})")

    def _on_scan_done(self, items):
        self._busy = False
        self._js(f"window.onScanDone && window.onScanDone({json.dumps(items)})")

    def _on_scan_error(self, msg):
        self._busy = False
        self._js(f"window.onScanError && window.onScanError({json.dumps(str(msg))})")

    # ------------------------------------------------------- remove path
    def request_remove(self, ids: list[str]):
        if self._busy or not ids:
            return
        self._busy = True
        self._js(f"window.onRemoveStarted && window.onRemoveStarted({json.dumps(ids)})")
        from engine.debloat import smart
        if smart.is_admin():
            self._start_remove_worker(ids)
        else:
            self._start_elevated(ids)

    def _start_remove_worker(self, ids: list[str]):
        self._worker = _RemoveWorker(ids, self)
        self._worker.done.connect(self._on_remove_done)
        self._worker.error.connect(self._on_remove_error)
        self._worker.start()

    def _start_elevated(self, ids: list[str]):
        """Relaunch ourselves as Administrator and let that copy do the work."""
        try:
            wdir = Path(tempfile.mkdtemp(prefix="mxt-debloat-"))
            job = wdir / "job.json"
            job.write_text(json.dumps({"ids": ids}), encoding="utf-8")
            result_file = job.with_suffix(".result.json")

            if getattr(sys, "frozen", False):
                target = sys.executable
                args = ["--cli", "debloat-remove", str(job)]
            else:
                target = sys.executable
                args = [str(ROOT / "main.py"), "--cli", "debloat-remove", str(job)]
            params = " ".join(f'"{a.replace(chr(34), "")}"' for a in args)

            import ctypes
            rc = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", target, params, None, 0)
            if int(rc) <= 32:
                self._busy = False
                self._js("window.onRemoveFailed && window.onRemoveFailed("
                         f"{json.dumps('Administrator approval was cancelled — nothing was removed.')})")
                return
            self._job = {"result": result_file, "tries": 0}
            self._poll.start()
        except Exception as exc:  # noqa: BLE001
            self._busy = False
            self._js(f"window.onRemoveFailed && window.onRemoveFailed({json.dumps(str(exc))})")

    def _poll_job(self):
        job = self._job
        if job is None:
            return
        job["tries"] += 1
        result_file = job.get("result")
        if result_file and Path(result_file).exists():
            self._poll.stop()
            self._job = None
            self._busy = False
            try:
                data = json.loads(Path(result_file).read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                data = None
            if isinstance(data, dict) and data.get("error"):
                self._js(f"window.onRemoveFailed && window.onRemoveFailed({json.dumps(data['error'])})")
            elif isinstance(data, list):
                self._js(f"window.onRemoveDone && window.onRemoveDone({json.dumps(data)})")
            else:
                self._js("window.onRemoveFailed && window.onRemoveFailed("
                         f"{json.dumps('Removal finished, but its result could not be read.')})")
        elif job["tries"] > 750:  # ~5 minutes
            self._poll.stop()
            self._job = None
            self._busy = False
            self._js("window.onRemoveFailed && window.onRemoveFailed("
                     f"{json.dumps('Removal did not finish in time — check Logs\\debloat.log.')})")

    def _on_remove_done(self, results):
        self._busy = False
        self._js(f"window.onRemoveDone && window.onRemoveDone({json.dumps(results)})")

    def _on_remove_error(self, msg):
        self._busy = False
        self._js(f"window.onRemoveFailed && window.onRemoveFailed({json.dumps(str(msg))})")