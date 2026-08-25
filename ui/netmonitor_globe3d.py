"""Lightweight canvas-based 3D globe via QWebEngineView.

Pure Canvas 2D renderer — no WebGL, no Three.js, no globe.gl.
Targets 15 FPS, reduces in gaming mode, pauses when hidden.
"""
from __future__ import annotations

import json
import os
from typing import Optional

from PySide6.QtCore import Qt, QUrl, Signal, QTimer, QSize
from PySide6.QtGui import QDesktopServices, QColor
from PySide6.QtWidgets import QWidget, QVBoxLayout, QSizePolicy
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings

from config.app_config import THEME as T


def _s(key, alpha=0xFF):
    hex_color = T.get(key, "#94a3b8").lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    return QColor(r, g, b, alpha)


def _esc(val: str) -> str:
    return val.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')


def _globe_html_path() -> str:
    import sys
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS
        path = os.path.join(base, "assets", "globe_canvas.html")
        if os.path.isfile(path):
            return path
    base = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(base)
    for candidate in [
        os.path.join(root, "assets", "globe_canvas.html"),
        os.path.join(root, "assets", "globe.html"),
        os.path.join(os.path.dirname(root), "assets", "globe_canvas.html"),
    ]:
        if os.path.isfile(candidate):
            return candidate
    return ""


class GlobeWebPage(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, line, sourceId):
        import logging
        logging.getLogger("globe").warning(f"JS [{level}] {sourceId}:{line} - {message}")

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        if is_main_frame and url != self.url():
            QDesktopServices.openUrl(url)
            return False
        return True


class Globe3DWidget(QWidget):
    """QWebEngineView-based 3D globe using globe.gl.

    New API matches the rebuilt globe.html for Network Intelligence.
    """

    node_clicked = Signal(dict)
    route_selected = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(400, 300)

        self._web = QWebEngineView(self)
        self._web.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._web.setPage(GlobeWebPage(self._web))

        settings = self._web.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.PluginsEnabled, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.ScreenCaptureEnabled, False)
        try:
            settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
        except AttributeError:
            pass
        try:
            settings.setAttribute(QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled, True)
        except AttributeError:
            pass

        self._web.setStyleSheet("background: #0a0e1a; border: none;")
        layout.addWidget(self._web)

        html_path = _globe_html_path()
        if html_path:
            self._web.setUrl(QUrl.fromLocalFile(html_path))
        else:
            self._web.setHtml(self._fallback_html(), QUrl("about:blank"))

        self._js_queue: list[str] = []
        self._ready = False
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._check_ready)
        self._poll_timer.start(500)

    def _check_ready(self):
        self._web.page().runJavaScript(
            "typeof globe !== 'undefined' ? 'ok' : 'wait'",
            lambda result: self._on_ready_check(result),
        )

    def _on_ready_check(self, result):
        if result == "ok" and not self._ready:
            self._ready = True
            self._poll_timer.stop()
            self._flush_queue()

    def _flush_queue(self):
        while self._js_queue:
            js = self._js_queue.pop(0)
            self._web.page().runJavaScript(js)

    def _run_js(self, js_code: str):
        if self._ready:
            self._web.page().runJavaScript(js_code)
        else:
            self._js_queue.append(js_code)

    # ── New Intel Engine API ─────────────────────────────────────────────────

    def set_game(self, name: str, state: str, process: str, region: str = "", pid: int = 0):
        self._run_js(f"window.setGame('{_esc(name)}', '{_esc(state)}', '{_esc(process)}', '{_esc(region)}', {pid});")

    def clear_game(self):
        self._run_js("window.clearGame();")

    def set_user_location(self, lat: float, lng: float, city: str = "", country: str = "", isp: str = "", asn: int = 0):
        self._run_js(f"window.setUser({lat}, {lng}, '{_esc(city)}', '{_esc(country)}', '{_esc(isp)}', {asn});")

    def set_game_endpoint(self, ip: str, lat: float, lng: float,
                          city: str = "", country: str = "",
                          asn: int = 0, asn_name: str = "",
                          classification: str = "GAME ENDPOINT",
                          score: int = 0, confidence: str = "unknown"):
        self._run_js(
            f"window.setGameEndpoint('{_esc(ip)}', {lat}, {lng}, "
            f"'{_esc(city)}', '{_esc(country)}', {asn}, '{_esc(asn_name)}', "
            f"'{_esc(classification)}', {score}, '{_esc(confidence)}');"
        )

    def clear_game_endpoint(self):
        self._run_js("window.clearGameEndpoint();")

    def set_hops(self, hops: list[dict]):
        hops_json = json.dumps(hops)
        self._run_js(f"window.setHops({hops_json});")

    def set_route_info(self, hops: list[dict], latency: float = 0, jitter: float = 0,
                       loss: float = 0, as_path: list[int] = None):
        hops_json = json.dumps(hops)
        as_path_json = json.dumps(as_path or [])
        self._run_js(
            f"window.setRouteInfo({hops_json}, {latency}, {jitter}, {loss}, {as_path_json});"
        )

    def set_latency(self, ms: float):
        self._run_js(f"window.setLatency({ms});")

    def focus_on(self, lat: float, lng: float, altitude: float = 1.0):
        self._run_js(f"window.focusOn({lat}, {lng}, {altitude});")

    def close_info_panel(self):
        self._run_js("window.closeInfoPanel();")

    def set_gaming_mode(self, enabled: bool):
        self._run_js(f"window.setGamingMode({'true' if enabled else 'false'});")

    # ── Legacy compat ────────────────────────────────────────────────────────

    def set_optimizer(self, name: str, lat: float, lng: float, city: str = ""):
        pass

    def set_game_server(self, ip: str, lat: float, lng: float,
                        city: str = "", country: str = "",
                        asn: int = 0, asn_name: str = ""):
        self.set_game_endpoint(ip, lat, lng, city, country, asn, asn_name, "GAME ENDPOINT", 0, "unknown")

    # ── Fallback ─────────────────────────────────────────────────────────────

    def _fallback_html(self) -> str:
        return """<!DOCTYPE html>
<html><head><style>
body { background:#0a0e1a; color:#94a3b8; font-family:'Segoe UI',sans-serif;
       display:flex; align-items:center; justify-content:center; height:100vh; margin:0; }
.msg { text-align:center; }
.msg h2 { color:#6395ff; margin-bottom:8px; }
</style></head><body>
<div class="msg">
<h2>Network Intelligence Globe</h2>
<p>Could not load globe.html</p>
<p style="font-size:11px;color:#475569;">Check that assets/globe.html exists</p>
</div>
</body></html>"""
