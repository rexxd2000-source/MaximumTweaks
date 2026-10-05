"""Diagnostics page — the diagnostics-v2 redesign.

The page renders ``ui/diagnostics.html`` (the reference design: glass rail of
all 12 tests on the left, one large glass stage for the selected test on the
right, progress ring around a glass orb) inside an embedded QtWebEngine view,
and exposes a QWebChannel bridge under ``window.pywebview.api`` exactly like
the tweak-cards / debloat pages.

Nothing runs automatically: picking a test only shows its details. Clicking
Run calls back into this page, which runs the *real* measurement from
``engine.diagnostics`` on a worker thread and streams real progress and the
real result back into the page. The reference's fake 70ms/4% timer is gone.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWebChannel import QWebChannel  # noqa: F401 - registers qtwebchannel.js
from PySide6.QtWidgets import QVBoxLayout, QWidget

from config.app_config import ROOT
from engine import diagnostics as eng
from ui.pages._web import make_webview

HTML_REL = "ui/diagnostics.html"

#: Icon id -> engine key, for deep links that arrive with either name.
_ALIASES = {
    "bl": "bufferbloat", "dns": "dns", "sp": "speed", "jt": "jitter",
    "bm": "benchmark", "dk": "disk", "mp": "memory", "pc": "pcie",
    "dr": "drivers", "gp": "throttle", "rf": "refresh", "rc": "recorders",
}


def _html_path() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    base = Path(meipass) if meipass else ROOT
    return base / HTML_REL


def _resolve(key: str) -> str:
    """Accept an engine key ('speed'), a short icon id ('sp'), or the old
    page's alias; return the engine key the rail is keyed on."""
    if key in eng.RUNNERS:
        return key
    return _ALIASES.get(key, key)


# ---------------------------------------------------------------- worker

class _RunWorker(QThread):
    """Runs one real measurement off the UI thread."""

    done = Signal(str, object)

    def __init__(self, key, runner, parent=None):
        super().__init__(parent)
        self.key = key
        self.runner = runner

    def run(self):
        try:
            res = self.runner()
        except Exception as exc:  # noqa: BLE001 - surfaced in the page
            res = {"rows": [], "grade": None, "error": str(exc)}
        self.done.emit(self.key, res)


# ---------------------------------------------------------------- bridge

class _DiagnosticsBridge(QObject):
    """Registered as ``window.pywebview.api`` on the page's QWebChannel."""

    def __init__(self, page, parent=None):
        super().__init__(parent)
        self._page = page

    @Slot(str)
    def run(self, key):
        self._page.request_run(key)


# ---------------------------------------------------------------- page

class DiagnosticsPage(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._ready = False
        self._pending_focus: str | None = None
        self._running: dict[str, dict] = {}

        self._web = make_webview(self)
        self._web.setStyleSheet("background:#07060f; border:none;")
        self._web.page().setBackgroundColor(QColor("#07060f"))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._web)

        settings = self._web.settings()
        settings.setAttribute(
            settings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(
            settings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        settings.setAttribute(
            settings.WebAttribute.JavascriptCanOpenWindows, False)

        self._bridge = _DiagnosticsBridge(self, self)
        self._channel = QWebChannel(self)
        self._channel.registerObject("api", self._bridge)
        self._web.page().setWebChannel(self._channel)

        html = _html_path()
        if html.is_file():
            self._web.load(QUrl.fromLocalFile(str(html)))
        else:
            self._web.setHtml(
                "<body style='background:#07060f;color:#9a93b8;"
                "font-family:sans-serif;padding:40px;'>"
                f"diagnostics.html not found at<br><code>{html}</code>"
                "</body>")
        self._web.loadFinished.connect(self._on_load_finished)

    # ------------------------------------------------------- JS transport

    def _js(self, script: str):
        self._web.page().runJavaScript(script)

    def _on_load_finished(self, ok):
        self._ready = True
        if self._pending_focus is not None:
            key, self._pending_focus = self._pending_focus, None
            self._js(f"window.mx && window.mx.select({json.dumps(key)})")

    # ---------------------------------------------------------- run flow

    def request_run(self, key):
        key = _resolve(key)
        entry = eng.RUNNERS.get(key)
        if entry is None or key in self._running:
            return
        runner, _title, est = entry
        est = max(1.0, float(est))
        timer = QTimer(self)
        timer.setInterval(70)
        timer.timeout.connect(lambda k=key: self._tick(k))
        self._running[key] = {"t0": time.monotonic(), "est": est,
                              "timer": timer}
        timer.start()
        worker = _RunWorker(key, runner, self)
        worker.done.connect(self._on_done)
        worker.finished.connect(worker.deleteLater)
        self._running[key]["worker"] = worker
        worker.start()

    def _tick(self, key):
        st = self._running.get(key)
        if st is None:
            return
        # Real measurements do not report a percentage, so the ring is paced
        # from elapsed time against the runner's estimate and deliberately
        # held under 100% until the real result lands. A tick that is late
        # simply jumps further: this pump catches up rather than drifting.
        el = time.monotonic() - st["t0"]
        pct = min(95, int(el / st["est"] * 92))
        self._js(f"window.mx && window.mx.progress({json.dumps(key)}, {pct})")

    def _on_done(self, key, res):
        st = self._running.pop(key, None)
        if st is not None:
            timer = st.get("timer")
            if timer is not None:
                timer.stop()
                timer.deleteLater()
        self._js("window.mx && window.mx.result({}, {})".format(
            json.dumps(key), json.dumps(res)))

    # ------------------------------------------------------- navigation

    def focus_card(self, key):
        """Open a specific test. Called from the dock deep link
        (``diagnostics:<key>``), which may fire before the view has loaded, so
        the selection is queued until loadFinished."""
        resolved = _resolve(key)
        if not self._ready:
            self._pending_focus = resolved
            return
        self._js(f"window.mx && window.mx.select({json.dumps(resolved)})")
