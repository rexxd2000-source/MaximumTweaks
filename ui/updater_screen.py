"""Step 1 of the boot wizard — full-bleed Updater screen.

Renders ``ui/updater_fullscreen.html`` (an exact port of the "Checking for
updates" mockup: blurred-violet glass panel, static top reflection, fixed
diagonal glint, glossy progress ring and glossy pill buttons) in a frameless
window that fills the whole screen — titlebar flush to the top, footer flush
to the bottom, no floating card or margins.

Everything the mockup animated with placeholders is live-bound instead:

  * the percentage counter climbs with the real check (capped short of 100
    until the server answers, so the number always reflects actual state);
  * the "Latest" version chip resolves to whatever ``updater.fetch_update()``
    actually returns (a newer build, "you're up to date", or "unavailable").

The window hands control back through the ``finished`` signal so the rest of
the boot sequence (license/splash/gate) proceeds as usual.
"""
from __future__ import annotations

import json
import sys
import time as _time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QObject, QPropertyAnimation, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QVBoxLayout, QWidget
from PySide6.QtWebChannel import QWebChannel

from config.app_config import APP_NAME, APP_VERSION, DIRS, ENGINE_NAME, LICENSE_API_URL, ROOT
from engine.state import LOGO_CACHE_FILE
from ui.pages._web import make_webview

HTML_REL = "ui/updater_fullscreen.html"

SERVER_CONN_TIMEOUT_MS = 9000          # per request
SERVER_CONN_BACKOFF_MS = (3000, 6000, 12000, 20000, 20000, 20000)
SERVER_CONN_MAX_ATTEMPTS = 6           # ~1 minute of total waking time
MIN_BOOT_MS = 5000                     # visible hold after the check resolves


class _ServerProbeThread(QThread):
    """Lightweight GET /health probe against the license API.

    Runs on the updater screen (the only boot screen now) so the admin "Online
    now" column stays accurate even though the splash no longer exists.  Never
    touches the key or the local session — pure connectivity.
    """

    done = Signal(str, bool, str)  # (url, ok, message)

    def __init__(self, base: str, parent=None):
        super().__init__(parent)
        self._base = str(base or "").rstrip("/")

    def run(self):
        base = self._base
        if not base or not base.startswith("https://"):
            self.done.emit(base, False,
                           "License server not configured (https required).")
            return
        url = base + "/health"
        try:
            req = urllib.request.Request(url, method="GET", headers={
                "User-Agent": "MaximumTweaks/" + APP_VERSION,
                "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=SERVER_CONN_TIMEOUT_MS / 1000.0) as resp:  # noqa: E501
                if resp.status == 200:
                    self.done.emit(base, True, "")
                    return
                self.done.emit(base, False, f"Server returned HTTP {resp.status}.")
        except urllib.error.HTTPError as exc:
            self.done.emit(base, False, f"Server returned HTTP {exc.code}.")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            self.done.emit(base, False, f"Can\u2019t reach server \u2014 {reason}.")
        except Exception as exc:  # noqa: BLE001
            self.done.emit(base, False, f"Can\u2019t reach server \u2014 {exc}.")


def _html_path() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    base = Path(meipass) if meipass else ROOT
    return base / HTML_REL


def _fonts_dir() -> Path:
    """The bundled font directory (dev: ``ROOT/assets/fonts``, frozen:
    ``_MEIPASS/assets/fonts``)."""
    meipass = getattr(sys, "_MEIPASS", None)
    base = Path(meipass) if meipass else ROOT
    return base / "assets" / "fonts"


def _brand_logo_uri() -> str:
    """Base64 data URI for the official Maximum logo, or ''.

    Mirrors ``AppLogo`` (ui/monitor_widgets.py): prefers the official art
    fetched from the website (cached in the state dir; survives exe upgrades in
    frozen builds), else the bundled ``assets/logo.png``.  Embedding a data URI
    is the same trick the category logos use so the brand mark renders with no
    filesystem-path dependence in dev or frozen (PyInstaller extraction-dir)
    builds.
    """
    import base64

    candidates = [Path(LOGO_CACHE_FILE), DIRS["assets"] / "logo.png"]
    for p in candidates:
        try:
            if p.is_file():
                raw = p.read_bytes()
                return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
        except OSError:
            continue
    return ""


class _Bridge(QObject):
    """Registered as ``window.pywebview.api`` on the updater page."""

    def __init__(self, window: "UpdaterWindow"):
        super().__init__(window)
        self._window = window

    @Slot()
    def skip(self):
        self._window._on_skip()

    @Slot()
    def minimize(self):
        self._window.showMinimized()

    @Slot()
    def closeClicked(self):
        self._window._on_skip()


class UpdaterWindow(QWidget):
    """The step-1 updater screen, full-bleed and frameless.

    This is the only boot screen: it runs the live update check, probes the
    license API so the admin panel stays fresh, and hands off through the
    ``finished`` signal once the step is done (check resolved, or skipped).

    Signals:
        finished: emitted once with ``{"info": dict|None, "error": str,
            "skipped": bool}`` when the step is done — either because the
            check resolved (up to date / newer build) or the user skipped.
        server_connected: emitted with the host once GET /health answers 200.
    """

    finished = Signal(object)
    server_connected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent, self.frameless_flags())
        self.setWindowTitle(f"{APP_NAME} — Updater")
        self._ready = False
        self._worker = None
        self._resolved = False
        self._done_emitted = False
        self._t0: float = 0.0
        self._latest_text: str | None = None
        self._sub_text: str | None = None
        self._server_base = (LICENSE_API_URL or "").rstrip("/")
        self._server_host = self._clean_host(self._server_base)
        self._server_attempt = 0
        self._server_timer: QTimer | None = None
        self._server_probe: _ServerProbeThread | None = None

        self._web = make_webview(self)
        self._web.setStyleSheet("background:#06050a; border:none;")
        self._web.page().setBackgroundColor(QColor("#06050a"))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._web)

        settings = self._web.settings()
        settings.setAttribute(settings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(settings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        settings.setAttribute(settings.WebAttribute.JavascriptCanOpenWindows, False)

        self._bridge = _Bridge(self)
        self._channel = QWebChannel(self)
        self._channel.registerObject("api", self._bridge)
        self._web.page().setWebChannel(self._channel)

        html = _html_path()
        if html.is_file():
            # QtWebEngine's file:// page cannot resolve *relative* file URLs
            # for @font-face src (the whole screen fell back to a system font
            # and looked soft). Rewrite the font paths to absolute file:///
            # URLs and load via setHtml with a file base, so the bundled
            # Inter/JetBrains Mono actually render.
            text = html.read_text(encoding="utf-8")
            fonts_uri = _fonts_dir().as_uri().rstrip("/") + "/"
            text = text.replace("../../assets/fonts/", fonts_uri)
            text = text.replace("__MAX_LOGO_URI__", _brand_logo_uri())
            self._web.setHtml(text, QUrl.fromLocalFile(str(html)))
        else:
            self._web.setHtml(
                "<body style='background:#06050a;color:#9a93b8;font-family:sans-serif;"
                "display:flex;align-items:center;justify-content:center;height:100vh'>"
                "updater_fullscreen.html not found at<br><code>" + str(html) +
                "</code></body>")
        self._web.loadFinished.connect(self._on_load_finished)

    @staticmethod
    def frameless_flags():
        from PySide6.QtCore import Qt
        return (Qt.FramelessWindowHint | Qt.Window)

    # ------------------------------------------------------------------ API

    def start(self):
        """Begin the live update check on this window."""
        self._push_show()
        self._t0 = _time.monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

        from ui.updater_dialog import FetchWorker
        worker = FetchWorker(self)
        worker.done.connect(self._on_check_done)
        self._worker = worker  # keep a strong ref until finished
        worker.start()

    def begin_server_check(self, base_url: str | None = None):
        """Probe the license API /health so the admin "Online now" panel stays
        fresh.  Purely a liveness GET — never touches the key or session.
        """
        base = str(base_url or self._server_base or "").rstrip("/")
        self._server_base = base
        self._server_host = self._clean_host(base)
        self._server_attempt = 0
        self._schedule_server_probe(0)

    @staticmethod
    def _clean_host(base_url: str) -> str:
        host = (base_url or "").strip().rstrip("/")
        try:
            if "://" in host:
                host = urllib.parse.urlsplit(host).netloc or host
        except Exception:  # noqa: BLE001
            pass
        return host

    def _schedule_server_probe(self, delay_ms: int):
        if self._server_timer is not None:
            self._server_timer.stop()
        self._server_timer = QTimer(self)
        self._server_timer.setSingleShot(True)
        self._server_timer.timeout.connect(self._run_server_probe)
        self._server_timer.start(max(0, int(delay_ms)))

    def _run_server_probe(self):
        if self._server_probe is not None and self._server_probe.isRunning():
            return
        self._server_probe = _ServerProbeThread(self._server_base, self)
        self._server_probe.done.connect(self._on_server_probe)
        self._server_probe.start()

    def _on_server_probe(self, _base, ok: bool, _message: str):
        if ok:
            self._server_attempt = 0
            self._stop_server_timer()
            self.server_connected.emit(self._server_host)
            return
        self._server_attempt += 1
        if self._server_attempt >= SERVER_CONN_MAX_ATTEMPTS:
            self._stop_server_timer()
            return
        idx = min(self._server_attempt - 1, len(SERVER_CONN_BACKOFF_MS) - 1)
        self._schedule_server_probe(SERVER_CONN_BACKOFF_MS[idx])

    def _stop_server_timer(self):
        if self._server_timer is not None:
            self._server_timer.stop()
            self._server_timer = None

    def fade_out(self, duration_ms: int = 700, on_done=None):
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(duration_ms)
        anim.setStartValue(self.windowOpacity())
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)

        def _finish():
            self.hide()
            self._stop_server_timer()
            if getattr(self, "_timer", None) is not None:
                self._timer.stop()
            if on_done:
                on_done()
        anim.finished.connect(_finish)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    # -------------------------------------------------------- internals

    def _js(self, script: str):
        self._web.page().runJavaScript(script)

    def _push_show(self):
        payload = {
            "installed": "v" + APP_VERSION,
            "latest": "checking…",
            "engine": f"{ENGINE_NAME} · v{APP_VERSION}",
            "railLabel": "Setup",
            "step": 1,
            "total": 4,
            "pct": self._live_pct(),
        }
        if self._resolved and self._latest_text:
            payload["latest"] = self._latest_text or "checking…"
        self._js(f"window.mx && window.mx.show({json.dumps(payload)})")
        if self._resolved and self._sub_text:
            self._js(f"window.mx && window.mx.setSub({json.dumps(self._sub_text)})")

    def _live_pct(self) -> float:
        """Same asymptotic curve the ticker drives.  Seeds a late-loading page
        at the current offset instead of showing 100% just because the check
        already resolved — the very thing that made the loader look done from
        the first frame."""
        elapsed = max(0.0, _time.monotonic() - self._t0)
        return min(97.0, 97.0 * (1.0 - 2.71828 ** (-elapsed / 2.0)))

    def _on_load_finished(self, _ok):
        self._ready = True
        self._push_show()
        if self._resolved:
            self._tick()

    def _tick(self):
        """Asymptotic live progress: climbs like the mockup (towards ~97, not
        100) so the loader visibly moves even for an instant up-to-date check;
        only reaches 100 the moment we hand off."""
        self._js(f"window.mx && window.mx.setProgress({self._live_pct():.1f})")

    def _on_check_done(self, payload):
        if self._resolved:
            return
        self._resolved = True
        info = payload.get("info")
        error = payload.get("error") or ""
        if info is not None:
            version = str(info.get("version") or "").lstrip("v")
            self._latest_text = "v" + version
            self._js(f"window.mx && window.mx.setLatest({json.dumps(self._latest_text)})")
        elif error:
            self._latest_text = "unavailable"
            self._js("window.mx && window.mx.setLatest('unavailable')")
            self._sub_text = ("We couldn't reach the update server right now — "
                              "we'll check again on the next launch.")
            self._js("window.mx && window.mx.setSub(" + json.dumps(self._sub_text) + ")")
        else:
            self._latest_text = "v" + APP_VERSION
            self._js(f"window.mx && window.mx.setLatest({json.dumps(self._latest_text)})")
        self._hold_then_finish(info, error, False)

    def _hold_then_finish(self, info, error, skipped):
        """Visible hold so the only boot screen feels like a boot screen: the
        update check usually resolves in ~1-2s (up to date) — that would flash
        the whole animation in an instant.  Wait until at least ``MIN_BOOT_MS``
        has passed since the screen appeared, then hand off."""
        elapsed = (_time.monotonic() - self._t0) * 1000.0
        remaining = max(0, MIN_BOOT_MS - elapsed)
        QTimer.singleShot(int(remaining), lambda: self._emit_finished(info, error, skipped))

    def _on_skip(self):
        if self._resolved:
            return
        self._resolved = True
        if getattr(self, "_timer", None) is not None:
            self._timer.stop()
        QTimer.singleShot(120, lambda: self._emit_finished(None, "", True))

    def _emit_finished(self, info, error, skipped):
        if self._done_emitted:
            return
        self._done_emitted = True
        if getattr(self, "_timer", None) is not None:
            self._timer.stop()
        self._js("window.mx && window.mx.setProgress(100)")
        self.finished.emit({"info": info, "error": error, "skipped": skipped})