"""Route Analyzer page — traceroute visualization with hop timeline, map, and metrics."""
from __future__ import annotations

import threading
import time
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QFrame, QSplitter, QScrollArea,
)

from config.app_config import THEME as T
from engine.netmonitor.comparison import build_route_comparison, comparison_verdict
from engine.netmonitor.engine import NetworkMonitorEngine
from engine.netmonitor.targeting import supported_games
from engine.netmonitor.types import Route, RouteEvent, MonitorState, ProbeMethod
from ui.netmonitor_widgets import RouteMapWidget
from ui.netmonitor_panels import HopTimelineWidget, LatencyGraphWidget
from ui.route_visualization import RouteVisualizationWidget


def _s(key, alpha=0xFF):
    hex_color = T.get(key, "#928AAD").lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    return QColor(r, g, b, alpha)


class _MonitorWorker(QThread):
    route_updated = Signal(object)
    event_emitted = Signal(object)

    def __init__(self, engine: NetworkMonitorEngine, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._engine.on_route_update(lambda r: self.route_updated.emit(r))
        self._engine.on_event(lambda e: self.event_emitted.emit(e))

    def run(self):
        pass


class _DetectWorker(QThread):
    """Background target-resolution: sniff live UDP + port-signature match."""
    done = Signal(object)

    def __init__(self, engine: NetworkMonitorEngine, game: str, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._game = game
        self._stop_event = threading.Event()

    def cancel(self):
        self._stop_event.set()

    def run(self):
        try:
            from engine.netmonitor.targeting import _diag
            _diag("[worker] run begin")
        except Exception:
            pass
        try:
            result = self._engine.resolve_game_server(
                self._game, duration=8.0, stop_event=self._stop_event
            )
        except Exception as exc:
            try:
                from engine.netmonitor.targeting import _diag
                _diag(f"[worker] resolve_game_server raised: {exc!r}")
            except Exception:
                pass
            result = None
        try:
            from engine.netmonitor.targeting import _diag
            _diag(f"[worker] run end, emitting result={result}")
        except Exception:
            pass
        self.done.emit(result)


class RouteAnalyzerPage(QWidget):
    def __init__(self, ctx, navigate=None, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.navigate = navigate
        self._engine = NetworkMonitorEngine()
        self._worker: Optional[_MonitorWorker] = None
        self._selected_hop: int = -1
        self._last_target = None
        self._last_compared_route_id: str = ""
        # Throttle for the spec Step 3.3 auto re-detect when the locked server
        # goes stale so a choppy match never spins a detection loop.
        self._auto_redetect_ts = 0.0
        # Cinematic Route Analyzer gate — a fully-opaque, non-skippable loading
        # overlay that plays once per session when this page is first shown,
        # hides the page completely, and then returns the user to the Dashboard
        # (the analyzer UI itself is never exposed while it is being reworked).
        self._intro_played = False
        self._page_ready = False
        self._gate_return_done = False
        self._intro: Optional["RouteTeaserOverlay"] = None

        # Route updates + events arrive from the monitor thread. Qt widgets
        # must only be touched on the GUI thread, so every engine callback is
        # marshalled through this worker's queued signals (never mutated
        # directly from the scan/sniff threads — that hard-crashes the app).
        self._worker = _MonitorWorker(self._engine, parent=self)
        self._worker.route_updated.connect(self._on_route_update)
        self._worker.event_emitted.connect(self._on_event)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 16)
        root.setSpacing(14)

        title = QLabel("Route Analyzer")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        sub = QLabel("Trace the live ISP path to your game server and analyze "
                     "latency, jitter, and packet loss per hop.")
        sub.setObjectName("PageSub")
        root.addWidget(sub)

        # ── Unified control bar: destination + game target + actions ──
        ctrl = self._make_card()
        ctrl_lay = QHBoxLayout(ctrl)
        ctrl_lay.setContentsMargins(14, 12, 14, 12)
        ctrl_lay.setSpacing(10)

        dest_label = QLabel("DESTINATION")
        dest_label.setStyleSheet(
            f"font-size: 9px; font-weight: 700; color: {T['text_faint']};"
            " letter-spacing: 1.2px; background: transparent;")
        ctrl_lay.addWidget(dest_label)

        self._dest_input = QLineEdit()
        self._dest_input.setPlaceholderText("google.com, 8.8.8.8, 1.1.1.1, or detected IP")
        self._dest_input.setStyleSheet(
            f"background: transparent; border: none; color: {T['text']};"
            " font-size: 13px; padding: 4px 0;")
        self._dest_input.returnPressed.connect(self._start_trace)
        ctrl_lay.addWidget(self._dest_input, 1)

        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet(f"color: {T['border']};")
        ctrl_lay.addWidget(sep)

        game_label = QLabel("TARGET")
        game_label.setStyleSheet(
            f"font-size: 9px; font-weight: 700; color: {T['text_faint']};"
            " letter-spacing: 1.2px; background: transparent;")
        ctrl_lay.addWidget(game_label)

        self._game_combo = QComboBox()
        games = supported_games()
        self._game_combo.addItems(games if games else ["Fortnite"])
        self._game_combo.setStyleSheet(
            f"background: transparent; border: none; color: {T['text']};"
            " font-size: 13px; padding: 4px 0;")
        self._game_combo.setFrame(False)
        ctrl_lay.addWidget(self._game_combo)

        self._detect_btn = QPushButton("\U0001f50d  Detect Live Server")
        self._detect_btn.setObjectName("Primary")
        self._detect_btn.setCursor(Qt.PointingHandCursor)
        self._detect_btn.setFixedWidth(170)
        self._detect_btn.clicked.connect(self._start_detect)
        ctrl_lay.addWidget(self._detect_btn)

        self._start_btn = QPushButton("\u25b6  Start Trace")
        self._start_btn.setObjectName("Primary")
        self._start_btn.setCursor(Qt.PointingHandCursor)
        self._start_btn.setFixedWidth(130)
        self._start_btn.clicked.connect(self._start_trace)
        ctrl_lay.addWidget(self._start_btn)

        self._stop_btn = QPushButton("\u25a0  Stop")
        self._stop_btn.setObjectName("Danger")
        self._stop_btn.setCursor(Qt.PointingHandCursor)
        self._stop_btn.setFixedWidth(100)
        self._stop_btn.setVisible(False)
        self._stop_btn.clicked.connect(self._stop_trace)
        ctrl_lay.addWidget(self._stop_btn)

        root.addWidget(ctrl)

        # ── Status line ──
        self._status = QLabel("Ready — enter a destination, or Detect Live Server "
                              "while in a match to bind to the real server.")
        self._status.setStyleSheet(
            f"font-size: 12px; color: {T['text_dim']}; background: transparent;"
            " padding: 2px 4px;")
        root.addWidget(self._status)

        # ── Scrollable body ──
        # The comparison + detail instruments are tall; if the window is short
        # they must scroll, never bleed over each other (a plain QVBoxLayout
        # keeps each widget at its minimum even when the parent runs out of
        # space, so the map's paint area was sliding under the RTT gauge).
        self._body_scroll = QScrollArea()
        self._body_scroll.setWidgetResizable(True)
        self._body_scroll.setFrameShape(QFrame.NoFrame)
        self._body_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._body_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollArea > QWidget > QWidget { background: transparent; }")
        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(14)
        self._body_lay = body_lay
        self._body_scroll.setWidget(body)
        root.addWidget(self._body_scroll, 1)

        # ════════════════════════════════════════════════════════════════
        # SECTION 1 — Route comparison (public vs optimized)
        # ════════════════════════════════════════════════════════════════
        cmp_frame = self._make_card()
        cmp_lay = QVBoxLayout(cmp_frame)
        cmp_lay.setContentsMargins(16, 12, 16, 14)
        cmp_lay.setSpacing(8)

        cmp_header = QHBoxLayout()
        cmp_header.setSpacing(10)
        cmp_title = QLabel("ROUTE COMPARISON")
        cmp_title.setStyleSheet(
            f"font-size: 11px; font-weight: 700; color: {T['text']};"
            " letter-spacing: 2px; background: transparent;")
        cmp_header.addWidget(cmp_title)
        self._cmp_verdict = QLabel("Trace a route to see public vs optimized routing")
        self._cmp_verdict.setStyleSheet(
            f"font-size: 11px; color: {T['text_faint']}; background: transparent;")
        cmp_header.addWidget(self._cmp_verdict, 1)
        self._cmp_badge = QLabel("")
        self._cmp_badge.setStyleSheet(
            f"font-size: 9px; font-weight: 700; color: {T['text_faint']};"
            " background: transparent; padding: 0 6px;")
        cmp_header.addWidget(self._cmp_badge)
        cmp_lay.addLayout(cmp_header)

        pub_header = QHBoxLayout()
        pub_label = QLabel("\u25c8  PUBLIC INTERNET ROUTE")
        pub_label.setStyleSheet(
            f"font-size: 9px; font-weight: 700; color: #7dd3fc;"
            " letter-spacing: 1.6px; background: transparent;"
            " padding: 2px 0;")
        pub_header.addWidget(pub_label)
        self._pub_stats = QLabel("trace to see stats")
        self._pub_stats.setStyleSheet(
            f"font-size: 9px; color: {T['text_faint']}; background: transparent;")
        pub_header.addWidget(self._pub_stats, 1)
        cmp_lay.addLayout(pub_header)
        self._pub_viz = RouteVisualizationWidget()
        self._pub_viz.set_route_color("#60a5fa")
        self._pub_viz.setFixedHeight(110)
        cmp_lay.addWidget(self._pub_viz)

        opt_header = QHBoxLayout()
        self._opt_label = QLabel("OPTIMIZED ROUTE  \u00b7  REAL TUNNEL")
        self._opt_label.setStyleSheet(
            f"font-size: 9px; font-weight: 700; color: #9C80FF;"
            " letter-spacing: 1px; background: transparent;")
        opt_header.addWidget(self._opt_label)
        self._opt_stats = QLabel("trace to see stats")
        self._opt_stats.setStyleSheet(
            f"font-size: 9px; color: {T['text_faint']}; background: transparent;")
        opt_header.addWidget(self._opt_stats, 1)
        cmp_lay.addLayout(opt_header)
        self._opt_viz = RouteVisualizationWidget()
        self._opt_viz.set_route_color("#9C80FF")
        self._opt_viz.setFixedHeight(110)
        cmp_lay.addWidget(self._opt_viz)

        self._cmp_frame = cmp_frame
        body_lay.addWidget(cmp_frame)

        # ════════════════════════════════════════════════════════════════
        # SECTION 2 — Detailed latency & hop timeline
        # ════════════════════════════════════════════════════════════════
        detail_frame = self._make_card()
        detail_lay = QVBoxLayout(detail_frame)
        detail_lay.setContentsMargins(16, 12, 16, 14)
        detail_lay.setSpacing(8)

        detail_header = QHBoxLayout()
        detail_header.setSpacing(10)
        detail_title = QLabel("DETAILED LATENCY & HOP TIMELINE")
        detail_title.setStyleSheet(
            f"font-size: 11px; font-weight: 700; color: {T['text']};"
            " letter-spacing: 2px; background: transparent;")
        detail_header.addWidget(detail_title)
        self._detail_hint = QLabel("")
        self._detail_hint.setStyleSheet(
            f"font-size: 10px; color: {T['text_faint']}; background: transparent;")
        detail_header.addWidget(self._detail_hint, 1)
        detail_lay.addLayout(detail_header)

        self._stats_line = QLabel("")
        self._stats_line.setTextFormat(Qt.RichText)
        self._stats_line.setStyleSheet(
            f"font-size: 11px; color: {T['text_faint']};"
            " background: transparent; padding: 3px 8px;")
        stats_bg = QFrame()
        stats_bg.setObjectName("StatsShell")
        stats_bg.setStyleSheet(
            "#StatsShell { background-color: #0e1428;"
            " border: 1px solid #2a3752; border-radius: 8px; }")
        stats_lay = QVBoxLayout(stats_bg)
        stats_lay.setContentsMargins(0, 0, 0, 0)
        stats_lay.addWidget(self._stats_line)
        detail_lay.addWidget(stats_bg)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setStyleSheet(
            "QSplitter::handle { background: transparent; width: 2px; }")
        self._splitter = splitter

        # Left pane: map + latency instrument
        left_widget = QWidget()
        left_lay = QVBoxLayout(left_widget)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(10)

        map_shell = QFrame()
        map_shell.setObjectName("InstShell")
        map_shell.setStyleSheet(
            "#InstShell { background-color: #0a0e1c;"
            " border: 1px solid #28354e; border-radius: 10px; }")
        map_lay = QVBoxLayout(map_shell)
        map_lay.setContentsMargins(0, 8, 0, 6)
        map_lay.setSpacing(4)
        map_head = QHBoxLayout()
        map_head.setContentsMargins(12, 0, 12, 0)
        map_title = QLabel("> ROUTE MAP // PATH")
        map_title.setStyleSheet(
            "font-size: 8px; font-weight: 700; color: #7dd3fc;"
            " letter-spacing: 2px; background: transparent;")
        map_head.addWidget(map_title)
        self._map_src = QLabel("")
        self._map_src.setStyleSheet(
            "font-size: 9px; color: #5e7198; background: transparent;")
        map_head.addWidget(self._map_src, 1)
        map_lay.addLayout(map_head)
        self._route_map = RouteMapWidget()
        self._route_map.hop_clicked.connect(self._on_hop_clicked)
        map_lay.addWidget(self._route_map, 1)
        left_lay.addWidget(map_shell, 1)

        # Latency instrument.
        self._latency_graph = LatencyGraphWidget()
        left_lay.addWidget(self._latency_graph)

        splitter.addWidget(left_widget)

        # Right pane: hop route instrument
        right_widget = QWidget()
        right_widget.setMinimumWidth(340)
        right_lay = QVBoxLayout(right_widget)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(0)

        self._hop_timeline = HopTimelineWidget()
        self._hop_timeline.hop_clicked.connect(self._on_hop_clicked)
        right_lay.addWidget(self._hop_timeline, 1)

        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)

        detail_lay.addWidget(splitter, 1)
        self._detail_frame = detail_frame
        body_lay.addWidget(detail_frame, 1)

        # ── Events log ──
        self._events_log = QLabel("")
        self._events_log.setStyleSheet(
            f"font-size: 11px; color: {T['text_faint']}; background: transparent;"
            " padding: 4px; max-height: 48px;")
        self._events_log.setWordWrap(True)
        body_lay.addWidget(self._events_log)

    @staticmethod
    def _make_card() -> QFrame:
        frame = QFrame()
        frame.setObjectName("Card")
        frame.setStyleSheet(
            f"#Card {{ background-color: {T['card']};"
            f" border: 1px solid {T['border']};"
            f" border-radius: 12px; }}")
        return frame

    def _start_detect(self):
        if getattr(self, "_detect_worker", None) is not None:
            return
        try:
            from engine.netmonitor.targeting import _diag
            _diag("[page] _start_detect begin")
        except Exception:
            pass
        game = self._game_combo.currentText()
        self._detect_btn.setEnabled(False)
        self._detect_btn.setText("\U0001f4e1  Capturing UDP \u2026")
        self._status.setText(f"Capturing live UDP traffic to find the {game} match server...")
        self._status.setStyleSheet(
            f"font-size: 12px; color: {T['accent']}; background: transparent;"
            " padding: 2px 4px;")

        self._detect_worker = _DetectWorker(self._engine, game, parent=self)
        self._detect_worker.done.connect(self._on_detect_done)
        self._detect_worker.start()
        try:
            from engine.netmonitor.targeting import _diag
            _diag("[page] _DetectWorker started")
        except Exception:
            pass

    def _on_detect_done(self, result):
        try:
            from engine.netmonitor.targeting import _diag
            _diag("[page] _on_detect_done begin")
        except Exception:
            pass
        self._detect_worker = None
        self._detect_btn.setEnabled(True)
        self._detect_btn.setText("\U0001f50d  Detect Live Server")
        if result is None:
            self._status.setText("Detection failed — capture returned nothing.")
            return
        if result.found and result.ip and result.protocol is not ProbeMethod.UDP:
            # Bug 18 hard guard (UI boundary): a non-UDP candidate is never
            # the in-match server (CDN/backend edge at best). Reject it the
            # same way as a failed detection — never trace it as the game.
            from engine.netmonitor.targeting import _diag
            _diag(f"[page] _on_detect_done REJECTED non-UDP target {result.ip}")
            self._status.setText(
                f"Detection rejected {result.ip} (non-UDP connection — not the "
                "game server). Keep the match running and retry.")
            self._status.setStyleSheet(
                f"font-size: 12px; color: {T['text_dim']}; background: transparent;"
                " padding: 2px 4px;")
            return
        if result.found and result.ip:
            self._last_target = result
            self._dest_input.setText(result.ip)
            relay_note = ""
            if result.relay_candidates:
                relay_note = (
                    f"  (ignored relay candidates: {', '.join(result.relay_candidates)})"
                )
            self._status.setText(f"{result.reason}{relay_note}")
            self._status.setStyleSheet(
                f"font-size: 12px; color: {T['accent']}; background: transparent;"
                " padding: 2px 4px;")
            self._start_trace()
        else:
            self._status.setText(
                f"{result.reason} — note: requires elevated + Npcap, run while in "
                "a live match.")
            self._status.setStyleSheet(
                f"font-size: 12px; color: {T['text_dim']}; background: transparent;"
                " padding: 2px 4px;")

    def _cancel_detect(self):
        if getattr(self, "_detect_worker", None) is not None:
            self._detect_worker.cancel()

    def _start_trace(self):
        try:
            from engine.netmonitor.targeting import _diag
            _diag("[page] _start_trace begin")
        except Exception:
            pass
        dest = self._dest_input.text().strip()
        if not dest:
            return
        self._stop_trace()
        self._status.setText(f"Tracing the live path to {dest}...")
        self._status.setStyleSheet(
            f"font-size: 12px; color: {T['accent']}; background: transparent;"
            " padding: 2px 4px;")
        self._start_btn.setVisible(False)
        self._stop_btn.setVisible(True)

        # Route/event callbacks are registered once in __init__ via the
        # _MonitorWorker (queued signals -> GUI thread). Never re-register the
        # page methods directly here: they would run on the monitor thread and
        # mutate Qt widgets off-thread, which hard-crashes the app.
        self._engine.start_monitoring(dest, target=self._last_target)
        try:
            from engine.netmonitor.targeting import _diag
            _diag("[page] start_monitoring returned")
        except Exception:
            pass

        if self._last_target is not None:
            target_now = self._last_target
            np_ = len(target_now.remote_ports)
            self._detail_hint.setText(
                f"Live target {target_now.ip} \u00b7 "
                f"{np_} live game port{'' if np_ == 1 else 's'} detected"
                f" ({'/'.join(str(p) for p in sorted(target_now.remote_ports))})"
                f" \u2014 these are the real remote ports your game session uses")

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_state)
        self._poll_timer.start(2000)

    def _stop_trace(self):
        self._cancel_detect()
        self._engine.stop()
        if hasattr(self, "_poll_timer"):
            self._poll_timer.stop()
        self._start_btn.setVisible(True)
        self._stop_btn.setVisible(False)
        self._detail_hint.setText("")
        self._map_src.setText("")

    def _poll_state(self):
        state = self._engine.state
        if state.active_route:
            self._on_route_update(state.active_route)
        # Spec Step 3.3: the locked server stopped receiving traffic — re-run
        # the detection pipeline fresh instead of tracing a dead connection.
        self._maybe_auto_redetect()

    def _maybe_auto_redetect(self):
        state = self._engine.state
        if not getattr(state, "live_stale", False):
            return
        now = time.time()
        if now - self._auto_redetect_ts < 10.0:
            return
        if getattr(self, "_detect_worker", None) is not None:
            return
        if not getattr(state, "monitoring", False):
            return
        self._auto_redetect_ts = now
        try:
            from engine.netmonitor.targeting import _diag
            _diag("[page] live target stale — auto re-detecting fresh server")
        except Exception:
            pass
        self._status.setText(
            "Server match ended or rotated — re-running live-server "
            "detection to relock the real match server...")
        self._start_detect()

    def _on_route_update(self, route: Route, changes=None):
        try:
            self._apply_route_to_ui(route, changes)
        except Exception as exc:
            # Never leak raw traceback text into the UI (Bug 16): log the real
            # cause internally, show the user a calm, actionable fallback.
            try:
                from engine.netmonitor.targeting import _diag
                _diag(f"[_on_route_update] render failed: {exc!r}")
            except Exception:
                pass
            try:
                msg = (
                    f"Route {route.destination if route else '?'} is scanning — "
                    "summary paused this update"
                )
                if self._status is not None:
                    self._status.setText(msg)
            except Exception:
                pass

    def _apply_route_to_ui(self, route: Route, changes=None):
        self._route_map.set_route(route)
        self._hop_timeline.set_route(route)
        self._latency_graph.set_route(route)
        self._map_src.setText(
            f"{route.destination_ip or route.destination or ''} \u00b7 "
            f"{len(route.hops)} HOP{'' if len(route.hops) == 1 else 'S'}")

        self._update_comparison(route)

        # Bug 19: a confirmed live game target has NO honest latency until the
        # passive match-RTT monitor delivers samples — probe-sourced numbers
        # through a tunnel/rate-limiter are fabric ("1600 ms" against a 136 ms
        # in-game ping). Show "awaiting live RTT" instead of a fake figure.
        awaiting_live = (
            route.rtt_source == "live_game" or route.probe_silent_endpoint
        ) and (
            route.live_rtt is None or route.live_rtt.samples == 0
        )
        lat = route.total_latency if not awaiting_live else 0.0
        jitter = route.route_jitter
        loss = route.route_packet_loss
        hops = len(route.hops)
        jitter_txt = f"{jitter:.1f} ms"
        loss_txt = f"{loss:.0f}%"
        if awaiting_live:
            jitter_txt = "n/a"
            loss_txt = "n/a"

        health_color = {
            "good": "#34d399",
            "degraded": "#FFB454",
            "critical": "#FF6F6F",
        }.get(route.health.value, T["text_dim"])

        # Sample basis + confidence tier for the number actually shown. A
        # headline resting on a sliver of probes (or on a ratio where timeouts
        # drowned replies) is coloured, never presented as a straight fact.
        # Computed FIRST — every branch below, including the physics-floor one,
        # needs it (Bug 16: this used to be referenced before assignment).
        conf_tier, conf_basis = route.confidence
        conf_color = {
            "high": "#34d399",
            "medium": "#FFB454",
            "low": "#FF6F6F",
            "none": T["text_faint"],
        }.get(conf_tier, T["text_faint"])
        # Precision matches sample quality: no fake tenths on a number built
        # from a thin/unreliable sample set (Bug 2).
        lat_fmt = f"{lat:.1f}" if conf_tier == "high" else f"{lat:.0f}"

        # Speed-of-light gate: an impossible sub-floor total must never be
        # displayed as fact — surface the physical floor as the honest minimum.
        # Self-clears once live RTT rises back above the floor.
        _implausible_now = (
            route.physics_implausible
            and route.latency_floor_ms > 0
            and route.total_latency < route.latency_floor_ms
        )
        phys_note = ""
        if _implausible_now:
            shown_lat = f"~{route.latency_floor_ms:.0f} ms (floor)"
            lat_color = "#FFB454"
            phys_note = (
                f"  |  {route.physics_reason}"
                if route.physics_reason
                else f"  |  below speed-of-light floor (~{route.latency_floor_ms:.0f} ms)"
            )
        else:
            shown_lat = f"{lat_fmt} ms"
            lat_color = health_color
        if awaiting_live:
            shown_lat = "awaiting live RTT"
            lat_color = T["text_faint"]
            conf_tier = "none"
            conf_basis = "waiting for live-game RTT samples"
        if conf_tier == "low":
            lat_color = conf_color
        self._stats_line.setText(
            "<span style='color:%s;'>TOTAL</span>"
            " <span style='color:%s; font-weight:700;'>%s</span>"
            " &nbsp;&nbsp;|&nbsp;&nbsp;"
            "<span style='color:%s;'>JITTER</span> <b>%s</b>"
            " &nbsp;&nbsp;|&nbsp;&nbsp;"
            "<span style='color:%s;'>LOSS</span> <b>%s</b>"
            " &nbsp;&nbsp;|&nbsp;&nbsp;"
            "<span style='color:%s;'>HOPS</span> <b>%d</b>"
            " &nbsp;&nbsp;|&nbsp;&nbsp;"
            "<span style='color:%s;'>CONF</span>"
            " <span style='color:%s; font-weight:700;'>%s</span>"
            " <span style='color:%s; font-size:10px;'>(%s)</span>"
            % (T["text_faint"], lat_color, shown_lat,
               T["text_faint"], jitter_txt,
               T["text_faint"], loss_txt,
               T["text_faint"], hops,
               T["text_faint"], conf_color, conf_tier, T["text_faint"], conf_basis)
        )

        if awaiting_live:
            stale_note = ""
            if getattr(self._engine.state, "live_stale", False):
                stale_note = "  |  match ended/rotated — re-detecting server"
            self._status.setText(
                f"Route to {route.destination} — {hops} hops | "
                f"awaiting live match RTT — synthetic game-port probes are "
                f"not shown as the server latency{stale_note}")
        elif route.rtt_source == "live_game" and route.live_rtt and route.live_rtt.samples:
            rtt = route.live_rtt
            rtt_fmt = f"{rtt.median_ms:.1f}" if conf_tier == "high" else f"{rtt.median_ms:.0f}"
            src_desc = (
                "game-port round trip" if getattr(rtt, "source", "") == "active_game_port"
                else "live stream"
            )
            best = getattr(rtt, "best_ms", 0.0) or 0.0
            if best > 0:
                # The game's HUD shows a smoothed BEST-case RTT (side-by-side
                # test: game "144" vs tool best "143.5"; window median was
                # ~8 ms higher under active traffic). Headline the BEST round
                # trip so the app's number and the in-game counter agree, and
                # keep the typical/worst spread visible right behind it.
                head = (
                    f"LIVE ping ~{best:.0f} ms (best round trip "
                    f"— what your game's ping shows)"
                )
                spread = f"typical {rtt.median_ms:.0f} · worst {rtt.max_ms:.0f}"
            else:
                head = f"LIVE match RTT {rtt_fmt} ms ({src_desc})"
                spread = f"min {rtt.min_ms:.0f} / max {rtt.max_ms:.0f}"
            trt = ""
            if route.os_tracert_match and route.os_tracert_match.get("note"):
                trt = f" | {route.os_tracert_match['note']}"
            self._status.setText(
                f"Route to {route.destination} — {hops} hops | "
                f"{head} "
                f"({spread} · {rtt.samples} samples) | {loss:.0f}% loss "
                f"| {conf_tier.upper()} confidence ({conf_basis}){phys_note}{trt}")
        else:
            self._status.setText(f"Route to {route.destination} — {hops} hops, "
                                 f"{lat_fmt}ms avg, {loss:.0f}% loss "
                                 f"| {conf_tier.upper()} confidence ({conf_basis})"
                                 f"{phys_note}")
        self._status.setStyleSheet(
            f"font-size: 12px; color: {health_color}; background: transparent;"
            " padding: 2px 4px;")

    def _on_event(self, event: RouteEvent):
        self._events_log.setText(f"[{event.level}] {event.message}")

    def _update_comparison(self, route: Route):
        # Rebuild on EVERY route update (live-RTT polls fold in immediately),
        # so the comparison summary and the detail footer always read the same
        # fields. build_route_comparison only walks already-enriched hops —
        # cheap enough for a 2 s poll beat.
        if not route or not route.hops:
            self._clear_comparison()
            return
        try:
            data = build_route_comparison(
                route,
                destination_ip=route.destination_ip,
            )
        except Exception as exc:
            self._clear_comparison()
            self._cmp_verdict.setText(f"Comparison unavailable: {exc}")
            return

        self._pub_viz.set_nodes(data["public_nodes"])
        self._pub_viz.set_title("", "")
        comp = data["comparison"]
        pub_hops = comp.get("public_hops", len(data["public_nodes"]) or 0)
        pub_ms = data.get("public_latency_ms") or route.total_latency
        pub_loss = comp.get("public_loss", route.route_packet_loss)
        # Bug 11: the comparison MUST report the same headline figure and LOSS%
        # the detail stats line shows — route.total_latency and
        # route.route_packet_loss are the single source for both panels.
        pub_ms = route.total_latency
        pub_loss = route.route_packet_loss
        phys = ""
        if (
            route.physics_implausible
            and route.latency_floor_ms > 0
            and route.total_latency < route.latency_floor_ms
        ):
            phys = f"  \u00b7  ~{route.latency_floor_ms:.0f} ms floor (fiber min)"
        _ct, _cb = route.confidence
        _pub_ms_txt = f"{pub_ms:.1f}" if _ct == "high" else f"{pub_ms:.0f}"
        budget_txt = (data.get("latency_budget") or {}).get("summary") or ""
        _stat = (
            f"{pub_hops} hops \u00b7 {_pub_ms_txt} ms \u00b7 {pub_loss:.0f}% loss"
            f"\u00b7 {_ct.upper()} conf: {_cb}{phys}"
        )
        if budget_txt:
            _stat += f"\n\n{budget_txt}"
        self._pub_stats.setText(_stat)

        if data.get("has_tunnel"):
            # A real, measured path through the active tunnel.
            self._opt_viz.set_nodes(data["optimized_nodes"])
            self._opt_viz.set_title("", "")
            self._opt_viz.set_route_color("#9C80FF")
            opt_hops = comp.get("optimized_hops", len(data["optimized_nodes"]) or 0)
            opt_ms = data.get("optimized_latency_ms") or 0.0
            opt_loss = comp.get("optimized_loss", 0.0)
            self._opt_label.setText("OPTIMIZED ROUTE  \u00b7  REAL TUNNEL")
            self._opt_stats.setText(
                f"{opt_hops} hops \u00b7 {opt_ms:.0f} ms \u00b7 {opt_loss:.0f}% loss")
            self._cmp_verdict.setText(comparison_verdict(comp))
            imp = comp.get("latency_improvement", 0)
            verdict_color = (
                "#34d399" if imp > 0 else "#FF6F6F" if imp < 0 else T["text_faint"]
            )
            self._cmp_verdict.setStyleSheet(
                f"font-size: 11px; color: {verdict_color}; background: transparent;")
            self._cmp_badge.setText(
                (data.get("provider") or "TUNNEL").upper())
        else:
            # Honest state: no GPN/VPN tunnel actively carries this server.
            # The optimized side is suppressed — never a static mock. When the
            # scan actually ran, its result is shown as evidence so the absence
            # is attributable, not a silent static claim.
            tin = route.tunnel_info or {}
            evidence = ""
            if tin.get("checked"):
                reason = tin.get("reason") or ""
                if tin.get("active") and not tin.get("routes_server"):
                    evidence = f"Tunnel scan \u2713 active {tin.get('kind', 'vpn') or 'vpn'} '{tin.get('name') or '?'}' does not carry this server"
                else:
                    evidence = "Tunnel scan \u2713 no active GPN/VPN tunnel"
                if reason and "no active" not in reason:
                    evidence += f" ({reason})"
            self._opt_viz.set_coming_soon(
                "No active GPN/VPN tunnel \u2014 optimized route is not shown.\n"
                "Enable a GPN/VPN tunnel to compare paths." + (
                    f"\n\n{evidence}" if evidence else ""
                )
            )
            self._opt_viz.set_route_color("#9C80FF")
            self._opt_label.setText("OPTIMIZED ROUTE")
            self._opt_stats.setText(
                evidence or "no active GPN/VPN tunnel detected")
            self._cmp_verdict.setText(
                data.get(
                    "description",
                    "No active GPN/VPN tunnel \u2014 optimized path not shown",
                )
            )
            self._cmp_verdict.setStyleSheet(
                f"font-size: 11px; color: {T['text_faint']}; background: transparent;")
            self._cmp_badge.setText("")

    def _clear_comparison(self):
        self._pub_viz.clear()
        self._opt_viz.clear()
        if hasattr(self, "_opt_label"):
            self._opt_label.setText("OPTIMIZED ROUTE  \u00b7  REAL TUNNEL")
        self._pub_stats.setText("trace to see stats")
        self._opt_stats.setText("trace to see stats")
        self._cmp_verdict.setText("Trace a route to see public vs optimized routing")
        self._cmp_verdict.setStyleSheet(
            f"font-size: 11px; color: {T['text_faint']}; background: transparent;")
        self._cmp_badge.setText("")

    def _on_hop_clicked(self, hop_number: int):
        self._selected_hop = hop_number
        self._hop_timeline.select_hop(hop_number)
        self._route_map.select_hop(hop_number)

    def showEvent(self, event):
        super().showEvent(event)
        if not getattr(self, "_splitter_tuned", False):
            self._splitter_tuned = True
            w = self._splitter.width()
            if w > 760:
                self._splitter.setSizes([w - 420, 420])
        # The page is now laid out and fully interactive — this is the explicit
        # state transition that authorises the loading gate to dismiss.
        self._page_ready = True
        if not getattr(self, "_intro_played", False):
            self._intro_played = True
            self._start_intro()

    def _start_intro(self):
        """Show the gate synchronously inside showEvent so the opaque overlay
        is painted with the page's very first frame — the Route Analyzer can
        never be glimpsed behind or before it."""
        try:
            from ui.route_teaser import RouteTeaserOverlay
            ov = RouteTeaserOverlay(self.rect(), parent=self, embedded=True)
            ov.set_ready_check(lambda: bool(getattr(self, "_page_ready", False)))
            ov.finished_dismiss.connect(self._return_after_gate)
            self._intro = ov
            ov.start()
        except Exception:
            self._intro = None

    def _return_after_gate(self):
        """Once the loading gate ends, leave the analyzer: the Route Analyzer
        is not publicly exposed yet, so the user lands back on the Dashboard
        instead of being dropped into the hidden page."""
        if getattr(self, "_gate_return_done", False):
            return
        self._gate_return_done = True
        if getattr(self, "_detect_worker", None) is not None:
            self._cancel_detect()
        nav = self.navigate
        if callable(nav):
            try:
                nav("dashboard")
            except Exception:
                pass

    def hideEvent(self, event):
        super().hideEvent(event)
        self._stop_trace()