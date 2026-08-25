"""Network Intelligence dashboard - 2D route comparison view.

Powered by the engine.intel orchestrator pipeline:
    Game Process -> Process Identification -> Live TCP/UDP Observation ->
    Lobby Baseline -> Matchmaking Inference -> Endpoint Scoring ->
    Session Endpoint Selection -> Public Route vs Optimized Route Comparison.

The page owns an IntelOrchestrator (background QThread). The orchestrator is
started when the page becomes visible and stopped when hidden, so no CPU is
burned while the user is on another page.
"""
from __future__ import annotations

import time
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QFrame, QSplitter, QScrollArea, QTabWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView,
)

from config.app_config import THEME as T
from engine.intel.orchestrator import IntelOrchestrator, IntelSnapshot
from engine.intel.process_detector import ProcessInfo
from engine.intel.endpoint_scorer import EndpointCandidate, EndpointClassification
from engine.intel.network_observer import TrackedEndpoint
from engine.intel.game_state_machine import GameState
from engine.intel.enrichment import (
    detect_user_location, detect_isp, lookup_geo, lookup_asn,
)
from engine.intel.traceroute import measure_route
from engine.intel.models import AsnInfo, GeoInfo, MeasuredRoute, RouteHop
from engine.intel.optimized_route import OptimizedRouteEngine, OptimizedRoute
from ui.route_visualization import RouteVisualizationWidget, RouteNode


def _s(key, alpha=0xFF):
    hex_color = T.get(key, "#94a3b8").lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    return QColor(r, g, b, alpha)


_POLL_MS = 5000
_POLL_MS_GAMING = 15000
_ACTIVE_WINDOW = 30.0

_CLS_LABELS = {
    EndpointClassification.GAME_SESSION: "GAME SESSION",
    EndpointClassification.LIKELY_GAME_SESSION: "LIKELY SESSION",
    EndpointClassification.RELAY: "RELAY",
    EndpointClassification.MATCHMAKING: "MATCHMAKING",
    EndpointClassification.BACKEND: "BACKEND",
    EndpointClassification.AUTHENTICATION: "AUTH",
    EndpointClassification.CDN: "CDN",
    EndpointClassification.VOICE: "VOICE",
    EndpointClassification.TELEMETRY: "TELEMETRY",
    EndpointClassification.UNKNOWN: "UNKNOWN",
}

_CLS_COLORS = {
    EndpointClassification.GAME_SESSION: "#34d399",
    EndpointClassification.LIKELY_GAME_SESSION: "#60a5fa",
    EndpointClassification.RELAY: "#c084fc",
    EndpointClassification.MATCHMAKING: "#fbbf24",
    EndpointClassification.BACKEND: "#5F6178",
    EndpointClassification.AUTHENTICATION: "#5F6178",
    EndpointClassification.CDN: "#5F6178",
    EndpointClassification.VOICE: "#c084fc",
    EndpointClassification.TELEMETRY: "#5F6178",
    EndpointClassification.UNKNOWN: "#5F6178",
}

_CONF_COLORS = {
    "high": "#34d399",
    "medium": "#fbbf24",
    "low": "#60a5fa",
    "unknown": "#5F6178",
}

_EVENT_COLORS = {
    "match_started": "#34d399",
    "match_ended": "#F87979",
    "endpoint_selected": "#8B5CF6",
    "session_started": "#60a5fa",
    "session_ended": "#F87979",
}


def _latency_color(ms: float) -> str:
    if ms <= 0:
        return T["text_faint"]
    if ms < 60:
        return "#34d399"
    if ms < 120:
        return "#fbbf24"
    return "#F87979"


# -- Workers ------------------------------------------------------------------

class _LocationWorker(QThread):
    located = Signal(float, float, str, str, str, int)

    def run(self):
        lat, lon, city, country = detect_user_location()
        isp = detect_isp()
        self.located.emit(
            float(lat), float(lon), str(city), str(country),
            str(isp.name or ""), int(isp.asn or 0),
        )


class _RouteWorker(QThread):
    geo_ready = Signal(object, object, int)
    route_ready = Signal(object, int)

    def __init__(self, ip: str, gen: int, parent=None):
        super().__init__(parent)
        self._ip = ip
        self._gen = gen

    def run(self):
        try:
            geo = lookup_geo(self._ip)
            asn = lookup_asn(self._ip)
            self.geo_ready.emit(geo, asn, self._gen)
        except Exception:
            pass
        try:
            route = measure_route(self._ip)
            if route and route.hops:
                import sys
                print(f"[RouteWorker] {self._ip}: {len(route.hops)} hops, {route.total_latency_ms:.0f}ms", file=sys.stderr)
            else:
                import sys
                print(f"[RouteWorker] {self._ip}: no hops returned", file=sys.stderr)
            self.route_ready.emit(route, self._gen)
        except Exception as e:
            import sys
            print(f"[RouteWorker] {self._ip}: exception {e}", file=sys.stderr)
            self.route_ready.emit(None, self._gen)


class _OptimizedRouteWorker(QThread):
    optimized_ready = Signal(object, object, int)

    def __init__(self, public_route, destination_ip, user_loc, gen, parent=None):
        super().__init__(parent)
        self._public_route = public_route
        self._dest_ip = destination_ip
        self._user_loc = user_loc
        self._gen = gen

    def run(self):
        try:
            engine = OptimizedRouteEngine()
            optimized = engine.compute_optimized(
                self._public_route, self._dest_ip, self._user_loc)
            comparison = engine.get_comparison(self._public_route, optimized)
            self.optimized_ready.emit(optimized, comparison, self._gen)
        except Exception:
            self.optimized_ready.emit(None, {}, self._gen)


# -- Game Status Card ---------------------------------------------------------

class _GameCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"QFrame{{background:{T['card']};border:1px solid {T['border']};"
            f"border-radius:8px;}}")
        self.setFixedHeight(72)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 8, 14, 8)
        lay.setSpacing(12)

        self._dot = QLabel("\u25cf")
        self._dot.setStyleSheet(f"font-size:18px;color:{T['text_faint']};")
        lay.addWidget(self._dot)

        info = QVBoxLayout()
        info.setSpacing(1)
        self._name = QLabel("NO GAME")
        self._name.setStyleSheet(
            f"font-size:14px;font-weight:800;color:{T['text']};letter-spacing:1px;")
        info.addWidget(self._name)
        self._state = QLabel("Waiting for a supported game...")
        self._state.setStyleSheet(f"font-size:10px;color:{T['text_faint']};")
        info.addWidget(self._state)
        self._pid = QLabel("")
        self._pid.setStyleSheet(
            f"font-size:9px;color:{T['text_faint']};font-family:Consolas;")
        info.addWidget(self._pid)
        lay.addLayout(info, 1)

        right = QVBoxLayout()
        right.setSpacing(2)
        right.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._endpoint = QLabel("")
        self._endpoint.setStyleSheet(
            f"font-size:10px;color:#60a5fa;font-family:Consolas;")
        self._endpoint.setAlignment(Qt.AlignmentFlag.AlignRight)
        right.addWidget(self._endpoint)
        self._latency = QLabel("")
        self._latency.setStyleSheet(
            f"font-size:20px;font-weight:700;font-family:Consolas;")
        self._latency.setAlignment(Qt.AlignmentFlag.AlignRight)
        right.addWidget(self._latency)
        lay.addLayout(right)

    def set_game(self, name, state_label, state_color, pid, process_name=""):
        self._name.setText((name or "GAME").upper())
        self._state.setText(state_label or "")
        self._state.setStyleSheet(
            f"font-size:10px;color:{state_color};font-weight:700;")
        pid_txt = f"PID {pid}" if pid else ""
        if process_name:
            pid_txt = f"{process_name} \u00b7 {pid_txt}".rstrip(" \u00b7")
        self._pid.setText(pid_txt)
        self._dot.setStyleSheet(f"font-size:18px;color:{state_color};")

    def set_latency(self, ms: float):
        if ms > 0:
            self._latency.setText(f"{ms:.0f}ms")
            self._latency.setStyleSheet(
                f"font-size:20px;font-weight:700;color:{_latency_color(ms)};"
                f"font-family:Consolas;")
        else:
            self._latency.setText("")

    def set_endpoint(self, ip: str):
        self._endpoint.setText(ip or "")

    def set_capture_status(self, admin: bool, capturing: bool, server_ip: str = ""):
        if not admin:
            self._endpoint.setToolTip("Run as Administrator to capture game server IP via raw socket")
        elif capturing and server_ip:
            self._endpoint.setToolTip(f"Game server IP captured via raw UDP capture: {server_ip}")
        elif capturing:
            self._endpoint.setToolTip("Raw UDP capture active — waiting for game server packets...")
        else:
            self._endpoint.setToolTip("")

    def set_no_game(self):
        self._name.setText("NO GAME")
        self._state.setText("Waiting for a supported game...")
        self._state.setStyleSheet(f"font-size:10px;color:{T['text_faint']};")
        self._pid.setText("")
        self._dot.setStyleSheet(f"font-size:18px;color:{T['text_faint']};")
        self._latency.setText("")
        self._endpoint.setText("")


# -- Route Coming Soon Widget -------------------------------------------------

# -- Route Comparison Stats Bar -----------------------------------------------

class _ComparisonStatsBar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"QFrame{{background:{T['card']};border:1px solid {T['border']};"
            f"border-radius:8px;}}")
        self.setFixedHeight(56)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 6, 14, 6)
        lay.setSpacing(0)

        self._metrics = {}
        for label in ["LATENCY", "JITTER", "HOPS", "LOSS"]:
            col = QVBoxLayout()
            col.setSpacing(0)
            col.setContentsMargins(16, 0, 16, 0)
            lbl = QLabel(label)
            lbl.setStyleSheet(
                f"font-size:8px;font-weight:700;color:{T['text_faint']};letter-spacing:1px;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            col.addWidget(lbl)
            val = QLabel("\u2014")
            val.setStyleSheet(
                f"font-size:14px;font-weight:700;color:{T['text']};font-family:Consolas;")
            val.setAlignment(Qt.AlignmentFlag.AlignCenter)
            col.addWidget(val)
            self._metrics[label] = val
            lay.addLayout(col)

            sep = QFrame()
            sep.setFrameShape(QFrame.Shape.VLine)
            sep.setStyleSheet(f"color:{T['border']};")
            lay.addWidget(sep)

        lay.addStretch()

        est_lbl = QLabel("OPTIMIZED ROUTE: ESTIMATED")
        est_lbl.setStyleSheet(
            f"font-size:9px;font-weight:700;color:#fbbf24;letter-spacing:1px;")
        lay.addWidget(est_lbl)

    def set_comparison(self, comp: dict):
        if not comp:
            return
        pub_lat = comp.get("public_latency", 0)
        opt_lat = comp.get("optimized_latency", 0)
        imp = comp.get("latency_improvement", 0)
        color = "#34d399" if imp > 0 else "#F87979" if imp < 0 else T["text_faint"]
        self._metrics["LATENCY"].setText(
            f"{pub_lat:.0f} -> {opt_lat:.0f} ms")
        self._metrics["LATENCY"].setStyleSheet(
            f"font-size:14px;font-weight:700;color:{color};font-family:Consolas;")

        pub_jit = comp.get("public_jitter", 0)
        opt_jit = comp.get("optimized_jitter", 0)
        jit_imp = comp.get("jitter_improvement", 0)
        jit_color = "#34d399" if jit_imp > 0 else "#F87979" if jit_imp < 0 else T["text_faint"]
        self._metrics["JITTER"].setText(
            f"{pub_jit:.1f} -> {opt_jit:.1f} ms")
        self._metrics["JITTER"].setStyleSheet(
            f"font-size:14px;font-weight:700;color:{jit_color};font-family:Consolas;")

        pub_hops = comp.get("public_hops", 0)
        opt_hops = comp.get("optimized_hops", 0)
        hop_imp = pub_hops - opt_hops
        hop_color = "#34d399" if hop_imp > 0 else "#F87979" if hop_imp < 0 else T["text_faint"]
        self._metrics["HOPS"].setText(f"{pub_hops} -> {opt_hops}")
        self._metrics["HOPS"].setStyleSheet(
            f"font-size:14px;font-weight:700;color:{hop_color};font-family:Consolas;")

        pub_loss = comp.get("public_loss", 0)
        opt_loss = comp.get("optimized_loss", 0)
        self._metrics["LOSS"].setText(f"{pub_loss:.1f}% -> {opt_loss:.1f}%")

    def clear(self):
        for lbl in self._metrics.values():
            lbl.setText("\u2014")
            lbl.setStyleSheet(
                f"font-size:14px;font-weight:700;color:{T['text_faint']};font-family:Consolas;")


# -- Endpoint Detail Panel ----------------------------------------------------

class _EndpointDetailPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"QFrame{{background:{T['card']};border:1px solid {T['border']};"
            f"border-radius:8px;}}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(5)

        title = QLabel("SESSION ENDPOINT")
        title.setStyleSheet(
            f"font-size:9px;font-weight:700;color:{T['text_faint']};letter-spacing:1px;")
        lay.addWidget(title)

        self._ip = QLabel("\u2014")
        self._ip.setStyleSheet(
            f"font-size:14px;font-weight:700;color:{_s('accent').name()};"
            f"font-family:Consolas;")
        self._ip.setWordWrap(True)
        lay.addWidget(self._ip)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(3)
        self._rows = {}
        for i, key in enumerate(("PROTOCOL", "PORT", "ASN", "LOCATION")):
            lbl = QLabel(key)
            lbl.setStyleSheet(
                f"font-size:8px;font-weight:700;color:{T['text_faint']};letter-spacing:.5px;")
            val = QLabel("\u2014")
            val.setStyleSheet(
                f"font-size:9px;color:{T['text']};font-family:Consolas;")
            val.setWordWrap(True)
            grid.addWidget(lbl, i // 2 * 2, i % 2)
            grid.addWidget(val, i // 2 * 2 + 1, i % 2)
            self._rows[key] = val
        lay.addLayout(grid)

        self._cls = QLabel("\u2014")
        self._cls.setStyleSheet(f"font-size:9px;font-weight:700;")
        lay.addWidget(self._cls)

        self._conf = QLabel("\u2014")
        self._conf.setStyleSheet(f"font-size:9px;")
        lay.addWidget(self._conf)

        sig_title = QLabel("SCORING SIGNALS")
        sig_title.setStyleSheet(
            f"font-size:8px;font-weight:700;color:{T['text_faint']};letter-spacing:.5px;")
        lay.addWidget(sig_title)

        self._signals = QLabel("No candidate selected.")
        self._signals.setWordWrap(True)
        self._signals.setStyleSheet(
            f"font-size:8px;color:{T['text_faint']};font-family:Consolas;line-height:1.4;")
        lay.addWidget(self._signals, 1)
        lay.addStretch()

    def set_candidate(self, ep: EndpointCandidate):
        self._ip.setText(ep.ip or "\u2014")
        self._rows["PROTOCOL"].setText(ep.protocol or "\u2014")
        self._rows["PORT"].setText(str(ep.port) if ep.port else "\u2014")
        self._rows["ASN"].setText("\u2014")
        self._rows["LOCATION"].setText("\u2014")

        cls_label = _CLS_LABELS.get(ep.classification, "UNKNOWN")
        cls_color = _CLS_COLORS.get(ep.classification, T["text_faint"])
        self._cls.setText(f"CLASSIFICATION  {cls_label}  \u00b7  SCORE {ep.score}")
        self._cls.setStyleSheet(f"font-size:9px;font-weight:700;color:{cls_color};")

        conf_color = _CONF_COLORS.get(ep.confidence, T["text_faint"])
        self._conf.setText(f"CONFIDENCE  {ep.confidence.upper()}")
        self._conf.setStyleSheet(f"font-size:9px;font-weight:700;color:{conf_color};")

        lines = ep.signal_summary
        if lines:
            colored = []
            for line in lines[:8]:
                color = "#34d399" if line.startswith("+") else "#F87979"
                colored.append(f'<span style="color:{color};">{line}</span>')
            self._signals.setText("<br>".join(colored))
        else:
            self._signals.setText("No scoring signals recorded.")

    def set_geo(self, geo, asn):
        if asn is not None and asn.asn:
            self._rows["ASN"].setText(f"AS{asn.asn} {asn.name}".strip())
        if geo is not None:
            parts = [p for p in (geo.city, geo.country_code) if p]
            self._rows["LOCATION"].setText(", ".join(parts) if parts else "Unknown")

    def clear(self):
        self._ip.setText("\u2014")
        for val in self._rows.values():
            val.setText("\u2014")
        self._cls.setText("\u2014")
        self._cls.setStyleSheet(f"font-size:9px;font-weight:700;color:{T['text_faint']};")
        self._conf.setText("\u2014")
        self._conf.setStyleSheet(f"font-size:9px;color:{T['text_faint']};")
        self._signals.setText("No candidate selected.")


# -- Candidates Table ---------------------------------------------------------

class _CandidateTable(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"QFrame{{background:{T['card']};border:1px solid {T['border']};"
            f"border-radius:8px;}}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(4)

        self._header = QLabel("CANDIDATES")
        self._header.setStyleSheet(
            f"font-size:9px;font-weight:700;color:{T['text_faint']};letter-spacing:1px;")
        lay.addWidget(self._header)

        self._table = QTableWidget()
        self._table.setColumnCount(7)
        self._table.setHorizontalHeaderLabels(
            ["Score", "IP", "Protocol", "Port", "Classification", "Status", "Signals"])
        self._table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)
        self._table.setAlternatingRowColors(False)
        self._table.setStyleSheet(f"""
            QTableWidget{{background:transparent;border:none;color:{T['text']};
                font-size:9px;}}
            QHeaderView::section{{background:{T['card_alt']};color:{T['text_faint']};
                border:none;border-bottom:1px solid {T['border']};
                font-size:8px;font-weight:700;letter-spacing:.5px;padding:4px;}}
            QTableWidget::item{{padding:3px;border-bottom:1px solid {T['border']};}}
        """)
        lay.addWidget(self._table, 1)

    def set_candidates(self, candidates):
        self._header.setText(
            f"CANDIDATES  \u00b7  {len(candidates)} SCORED ENDPOINTS")
        self._table.setRowCount(len(candidates))
        for i, c in enumerate(candidates):
            if c.score >= 60:
                score_color = "#34d399"
            elif c.score >= 40:
                score_color = "#60a5fa"
            elif c.score >= 20:
                score_color = "#fbbf24"
            elif c.score < 0:
                score_color = "#F87979"
            else:
                score_color = T["text_dim"]

            active = c.last_seen > 0 and (time.time() - c.last_seen) < _ACTIVE_WINDOW
            status_color = "#34d399" if active else T["text_faint"]
            cls_label = _CLS_LABELS.get(c.classification, "UNKNOWN")
            cls_color = _CLS_COLORS.get(c.classification, T["text_faint"])
            signals = "  ".join(c.signal_summary[:3])

            items = [
                (str(c.score), score_color, True),
                (c.ip, T["text"], False),
                (c.protocol or "-", T["text_dim"], False),
                (str(c.port) if c.port else "-", T["text_faint"], False),
                (cls_label, cls_color, False),
                ("ACTIVE" if active else "STALE", status_color, False),
                (signals or "-", T["text_faint"], False),
            ]
            for j, (text, color, bold) in enumerate(items):
                item = QTableWidgetItem(text)
                item.setForeground(QColor(color))
                item.setFont(QFont("Consolas", 9, QFont.Weight.Bold if bold else QFont.Weight.Normal))
                self._table.setItem(i, j, item)

    def clear(self):
        self._table.setRowCount(0)
        self._header.setText("CANDIDATES")


# -- Timeline Panel -----------------------------------------------------------

class _TimelinePanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"QFrame{{background:{T['card']};border:1px solid {T['border']};"
            f"border-radius:8px;}}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(2)

        header = QLabel("SESSION TIMELINE")
        header.setStyleSheet(
            f"font-size:9px;font-weight:700;color:{T['text_faint']};letter-spacing:1px;")
        lay.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")
        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(2)
        scroll.setWidget(self._container)
        lay.addWidget(scroll, 1)

        self._empty = QLabel("No session events yet.")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setStyleSheet(f"font-size:9px;color:{T['text_faint']};")
        self._layout.addWidget(self._empty)
        self._layout.addStretch()

    def set_events(self, events):
        for i in reversed(range(self._layout.count())):
            item = self._layout.itemAt(i)
            w = item.widget()
            if w is not None and w is not self._empty:
                w.deleteLater()
        self._empty.setVisible(not events)
        if not events:
            return
        for event in reversed(events[-50:]):
            ts = time.strftime("%H:%M:%S", time.localtime(event.timestamp))
            etype = getattr(event, "event_type", "") or ""
            color = _EVENT_COLORS.get(etype, T["text_faint"])
            row = QLabel(f"[{ts}] {event.description}")
            row.setStyleSheet(
                f"font-size:8px;color:{color};font-family:Consolas;padding:1px 4px;")
            row.setWordWrap(True)
            self._layout.addWidget(row)
        self._layout.addStretch()

    def clear(self):
        self.set_events([])


# -- Debug Panel --------------------------------------------------------------

class _DebugPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"QFrame{{background:{T['card']};border:1px solid {T['border']};"
            f"border-radius:8px;}}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(2)

        header = QLabel("ORCHESTRATOR DEBUG")
        header.setStyleSheet(
            f"font-size:9px;font-weight:700;color:{T['text_faint']};letter-spacing:1px;")
        lay.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")
        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(0, 0, 0, 0)
        self._content = QLabel("No debug data.")
        self._content.setWordWrap(True)
        self._content.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._content.setStyleSheet(
            f"font-size:8px;color:{T['text_faint']};font-family:Consolas;line-height:1.4;")
        cl.addWidget(self._content)
        scroll.setWidget(content)
        lay.addWidget(scroll, 1)

    def set_debug(self, text):
        self._content.setText(text or "No debug data.")

    def clear(self):
        self.set_debug("")


# -- Main Page ----------------------------------------------------------------

class NetworkMonitorPage(QWidget):
    def __init__(self, ctx=None, parent=None):
        super().__init__(parent)
        self.ctx = ctx

        self._orchestrator = IntelOrchestrator(poll_interval=3.0, parent=self)
        self._orchestrator.snapshot_updated.connect(self._on_snapshot)
        self._orchestrator.status_update.connect(self._on_status_msg)

        self._user_loc = None
        self._user_isp_name = ""
        self._user_isp_asn = 0
        self._have_user_loc = False
        self._location_worker = None

        self._last_endpoint_key = ""
        self._last_route_target = ""
        self._route_gen = 0
        self._route_workers = []
        self._optimized_workers = []
        self._last_route = None
        self._last_optimized = None
        self._last_comparison = {}
        self._route_cache = {}
        self._endpoint_geo = None
        self._endpoint_asn = None
        self._had_game = False
        self._last_snap_ts = 0.0
        self._scan_dots = 0
        self._gaming_mode = False
        self._npcap_installer_path = ""

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._on_poll_tick)

        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(10, 6, 10, 10)
        bl.setSpacing(6)

        self._game_card = _GameCard()
        bl.addWidget(self._game_card)

        self._npcap_banner = QFrame()
        self._npcap_banner.setStyleSheet(
            f"QFrame{{background:#1a1520;border:1px solid #8B5CF6;"
            f"border-radius:8px;padding:8px;}}")
        nb_lay = QHBoxLayout(self._npcap_banner)
        nb_lay.setContentsMargins(12, 8, 12, 8)
        nb_lay.setSpacing(10)
        nb_icon = QLabel("\u26a0")
        nb_icon.setStyleSheet("font-size:18px;color:#fbbf24;")
        nb_lay.addWidget(nb_icon)
        nb_text = QLabel(
            "Npcap is required for game server IP capture.\n"
            "Click Install — it takes 10 seconds, then come back and click Retry.")
        nb_text.setStyleSheet(
            f"font-size:10px;color:{T['text']};line-height:1.4;")
        nb_text.setWordWrap(True)
        nb_lay.addWidget(nb_text, 1)
        self._npcap_install_btn = QPushButton("INSTALL NPCAP")
        self._npcap_install_btn.setStyleSheet(
            f"QPushButton{{background:#8B5CF6;color:white;border:none;"
            f"border-radius:5px;padding:8px 16px;font-size:10px;font-weight:700;}}"
            f"QPushButton:hover{{background:#7c3aed;}}")
        self._npcap_install_btn.clicked.connect(self._on_npcap_install)
        nb_lay.addWidget(self._npcap_install_btn)
        self._npcap_retry_btn = QPushButton("RETRY")
        self._npcap_retry_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{T['text_faint']};"
            f"border:1px solid {T['border']};border-radius:5px;"
            f"padding:8px 14px;font-size:10px;font-weight:600;}}"
            f"QPushButton:hover{{color:{T['text']};border-color:{T['accent']};}}")
        self._npcap_retry_btn.clicked.connect(self._on_npcap_retry)
        nb_lay.addWidget(self._npcap_retry_btn)
        self._npcap_banner.setVisible(False)
        bl.addWidget(self._npcap_banner)

        center = QWidget()
        cl = QVBoxLayout(center)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(6)

        self._stats_bar = _ComparisonStatsBar()
        cl.addWidget(self._stats_bar)

        bl.addWidget(center, 3)

        bottom = QTabWidget()
        bottom.setMinimumHeight(170)
        bottom.setStyleSheet(
            f"QTabWidget::pane{{border:1px solid {T['border']};border-radius:6px;"
            f"background:{T['card']};}}"
            f"QTabBar::tab{{background:{T['card_alt']};color:{T['text_faint']};"
            f"padding:6px 14px;border:1px solid {T['border']};"
            f"border-bottom:none;border-radius:4px 4px 0 0;"
            f"font-size:9px;font-weight:600;letter-spacing:0.5px;}}"
            f"QTabBar::tab:selected{{background:{T['card']};color:{T['text']};"
            f"border-bottom:2px solid {_s('accent').name()};}}"
            f"QTabBar::tab:hover{{color:{T['text']};}}")

        self._candidates = _CandidateTable()
        bottom.addTab(self._candidates, "CANDIDATES")

        self._endpoint_panel = _EndpointDetailPanel()
        bottom.addTab(self._endpoint_panel, "ENDPOINT")

        self._timeline = _TimelinePanel()
        bottom.addTab(self._timeline, "TIMELINE")

        self._debug_panel = _DebugPanel()
        bottom.addTab(self._debug_panel, "DEBUG")

        bl.addWidget(bottom, 2)
        root.addWidget(body, 1)

    def _build_header(self):
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame{{background:{T['card']};border-bottom:1px solid {T['border']};}}")
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(14, 8, 14, 8)
        lay.setSpacing(10)

        ico = QLabel("\u2637")
        ico.setStyleSheet(f"font-size:18px;color:{_s('accent').name()};")
        lay.addWidget(ico)

        title = QLabel("NETWORK INTELLIGENCE")
        title.setStyleSheet(
            f"font-size:13px;font-weight:800;color:{T['text']};"
            f"letter-spacing:2px;font-family:'Segoe UI';")
        lay.addWidget(title)

        self._status_badge = QLabel("STANDBY")
        self._set_badge("STANDBY", T["text_faint"])
        lay.addWidget(self._status_badge)

        lay.addStretch()

        self._gaming_btn = QPushButton("GAMING MODE")
        self._gaming_btn.setCheckable(True)
        self._gaming_btn.setFixedHeight(26)
        self._gaming_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._gaming_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{T['text_faint']};"
            f"border:1px solid {T['border']};border-radius:13px;"
            f"font-size:9px;font-weight:700;letter-spacing:1px;padding:0 12px;}}"
            f"QPushButton:hover{{border-color:{_s('accent').name()};color:{T['text']};}}"
            f"QPushButton:checked{{background:{_s('accent_dark').name()};"
            f"color:{_s('accent').name()};border-color:{_s('accent').name()};}}")
        self._gaming_btn.toggled.connect(self._on_gaming_toggled)
        lay.addWidget(self._gaming_btn)

        reset_btn = QPushButton("RESET")
        reset_btn.setFixedHeight(26)
        reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{T['text_faint']};"
            f"border:1px solid {T['border']};border-radius:13px;"
            f"font-size:9px;font-weight:700;letter-spacing:1px;padding:0 12px;}}"
            f"QPushButton:hover{{border-color:{_s('accent').name()};color:{T['text']};}}")
        reset_btn.clicked.connect(self._on_reset)
        lay.addWidget(reset_btn)

        return frame

    # -- Visibility lifecycle -------------------------------------------------

    def showEvent(self, event):
        super().showEvent(event)
        if not self._have_user_loc:
            self._fetch_user_location()
        if not self._orchestrator.isRunning():
            self._orchestrator.start()
        self._poll_timer.start(_POLL_MS_GAMING if self._gaming_mode else _POLL_MS)

    def hideEvent(self, event):
        super().hideEvent(event)
        self._poll_timer.stop()
        if self._orchestrator.isRunning():
            self._orchestrator.stop()

    # -- User location --------------------------------------------------------

    def _fetch_user_location(self):
        if self._location_worker is not None:
            return
        worker = _LocationWorker(self)
        worker.located.connect(self._on_user_located)
        worker.finished.connect(worker.deleteLater)
        self._location_worker = worker
        worker.start()

    def _on_user_located(self, lat, lon, city, country, isp_name, isp_asn):
        self._location_worker = None
        if lat == 0.0 and lon == 0.0:
            return
        self._have_user_loc = True
        self._user_loc = (lat, lon, city, country)
        self._user_isp_name = isp_name
        self._user_isp_asn = isp_asn
        self._orchestrator.set_user_location(
            lat, lon, city, country, isp_name, isp_asn)

    # -- Heartbeat ------------------------------------------------------------

    def _on_poll_tick(self):
        if not self.isVisible():
            return
        if not self._orchestrator.isRunning():
            self._orchestrator.start()
            return
        snap = self._orchestrator.snapshot
        if snap.game_state == GameState.NOT_RUNNING:
            if self._had_game:
                self._clear_game_ui()
            self._scan_dots = (self._scan_dots + 1) % 4
            self._set_badge(f"SCANNING{'.' * self._scan_dots}", T["text_faint"])

    # -- Snapshot handling ----------------------------------------------------

    def _on_snapshot(self, snap):
        self._last_snap_ts = time.time()
        state = snap.game_state
        proc = snap.game_process
        has_game = state != GameState.NOT_RUNNING and proc is not None

        self._set_badge(snap.status or snap.state_label, snap.state_color)

        if not has_game:
            if self._had_game:
                self._clear_game_ui()
            return
        self._had_game = True

        display = snap.game_display or proc.display_name
        self._game_card.set_game(
            display, snap.state_label, snap.state_color, proc.pid, proc.name)

        ep = snap.game_endpoint
        if ep is not None:
            key = f"{ep.ip}:{ep.port}-{ep.protocol}"
            if key != self._last_endpoint_key:
                self._last_endpoint_key = key
                self._endpoint_geo = None
                self._endpoint_asn = None
                self._endpoint_panel.set_candidate(ep)
                self._game_card.set_endpoint(ep.ip)
        else:
            self._game_card.set_endpoint("")

        captured_ip = snap.captured_game_server.ip if snap.captured_game_server else ""
        self._game_card.set_capture_status(snap.udp_capture_admin, snap.udp_capture_active, captured_ip)
        self._npcap_banner.setVisible(snap.npcap_missing)
        self._npcap_installer_path = snap.npcap_installer_path

        target = snap.route_target
        if target and target != self._last_route_target:
            self._maybe_measure_route(target)
        elif not target:
            self._last_route_target = ""

        self._candidates.set_candidates(snap.all_candidates)
        self._timeline.set_events(snap.timeline)
        self._debug_panel.set_debug("\n".join(snap.debug_lines))

    def _on_status_msg(self, msg):
        if msg.startswith("Error"):
            self._set_badge(msg[:28], T["red"])

    def _on_npcap_install(self):
        path = getattr(self, "_npcap_installer_path", "")
        if not path:
            return
        from engine.intel.npcap_installer import launch_installer
        launch_installer(path)
        self._npcap_install_btn.setText("OPENED — COMPLETE INSTALL, THEN CLICK RETRY")

    def _on_npcap_retry(self):
        from engine.intel.npcap_installer import is_npcap_installed
        if is_npcap_installed():
            self._npcap_banner.setVisible(False)
            cap = self._orchestrator._udp_capture
            cap._has_npcap = True
            cap._start_error = ""
            cap._has_admin = True
            if not cap.is_capturing:
                if cap.start():
                    self._npcap_install_btn.setText("INSTALLED — CAPTURE ACTIVE")
                else:
                    self._npcap_install_btn.setText(f"START FAILED: {cap.start_error}")
        else:
            self._npcap_install_btn.setText("STILL NOT INSTALLED — TRY AGAIN")

    # -- Route measurement ----------------------------------------------------

    def _maybe_measure_route(self, ip):
        if not ip:
            return
        if ip == self._last_route_target:
            if ip in self._route_cache:
                self._display_route(ip, self._route_cache[ip])
            return
        self._last_route_target = ip
        self._route_gen += 1

    def _on_endpoint_geo(self, geo, asn, gen):
        if geo is None:
            return
        self._endpoint_geo = geo
        self._endpoint_asn = asn
        self._endpoint_panel.set_geo(geo, asn)

    def _on_route_ready(self, route, gen):
        if route is None or not route.hops:
            return
        ip = route.destination_ip
        self._route_cache[ip] = route

    def _display_route(self, ip, route):
        if route is None or not route.hops:
            return
        self._last_route = route
        self._game_card.set_latency(route.total_latency_ms)

    def _compute_optimized(self, public_route):
        pass

    def _on_optimized_ready(self, optimized, comparison, gen):
        if gen != self._route_gen:
            return
        self._last_optimized = optimized
        self._last_comparison = comparison
        self._stats_bar.set_comparison(comparison)

    # -- Controls -------------------------------------------------------------

    def _on_gaming_toggled(self, checked):
        self._gaming_mode = checked
        if self._poll_timer.isActive():
            self._poll_timer.start(_POLL_MS_GAMING if checked else _POLL_MS)

    def _on_reset(self):
        self._route_gen += 1
        self._last_endpoint_key = ""
        self._last_route_target = ""
        self._last_route = None
        self._last_optimized = None
        self._last_comparison = {}
        self._endpoint_geo = None
        self._endpoint_asn = None
        self._had_game = False

        self._orchestrator.reset()
        if self._user_loc is not None:
            self._orchestrator.set_user_location(
                self._user_loc[0], self._user_loc[1],
                self._user_loc[2], self._user_loc[3],
                self._user_isp_name, self._user_isp_asn,
            )

        self._stats_bar.clear()
        self._game_card.set_no_game()
        self._endpoint_panel.clear()
        self._candidates.clear()
        self._timeline.clear()
        self._debug_panel.clear()
        self._set_badge("SCANNING", T["text_faint"])

    def _clear_game_ui(self):
        self._had_game = False
        self._last_endpoint_key = ""
        self._last_route_target = ""
        self._game_card.set_no_game()
        self._endpoint_panel.clear()
        self._stats_bar.clear()

    # -- Helpers --------------------------------------------------------------

    def _set_badge(self, text, color):
        self._status_badge.setText((text or "").upper())
        self._status_badge.setStyleSheet(
            f"QLabel{{font-size:8px;font-weight:700;color:{color};"
            f"letter-spacing:1px;padding:3px 10px;border-radius:9px;"
            f"background:{T['accent_dark']};border:1px solid {T['border']};}}")

    def cleanup(self):
        self._poll_timer.stop()
        if self._orchestrator.isRunning():
            self._orchestrator.stop()
        if self._location_worker is not None:
            self._location_worker.wait(4000)
            self._location_worker = None
        for worker in list(self._route_workers):
            worker.wait(1000)
        self._route_workers.clear()
        for worker in list(self._optimized_workers):
            worker.wait(1000)
        self._optimized_workers.clear()
