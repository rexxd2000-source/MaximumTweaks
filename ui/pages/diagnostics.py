"""Diagnostics page — port of diagnostics-category.html.

Every "test or scan" tool lives here. Six cards, each with the reference
anatomy: cyan icon chip + title, description, mono status line (idle gray ->
running cyan pulse -> done green), cyan->violet progress bar while running,
result rows with a grade letter (A green / B cyan / C amber), and a run button
that becomes a ghost "Run again" after the test finishes — matching the
reference button behavior exactly. Runners are real measurements (engine.
diagnostics); nothing here happens automatically.
"""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QRadialGradient
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from engine import diagnostics as eng

_BG = "#08060F"
_CYAN = "#4BE8D8"
_VIOLET = "#8B6BFF"
_VIOLET_SOFT = "#C9C0FF"
_GREEN = "#3DDC97"
_RED = "#FF6F6F"
_TEXT_1 = "#F6F4FC"
_TEXT_4 = "#928AAD"
_TEXT_6 = "#514A70"
_BORDER = "rgba(255,255,255,0.09)"
_BORDER_SOFT = "rgba(255,255,255,0.06)"
_GLASS = "rgba(255,255,255,0.03)"
_DISPLAY = '"Segoe UI", sans-serif'
_MONO = '"JetBrains Mono", monospace'

# id -> (title, desc, svg paths, stroke width, run label, est seconds)
TESTS = {
    "bufferbloat": (
        "Bufferbloat Test",
        "Measures how much your ping increases under network load — the "
        "leading cause of lag spikes during downloads or uploads.",
        '<path d="M4 18l4-8 4 5 3-9 5 12"/>', 1.7,
        "Run test", 3.0),
    "dns": (
        "DNS Benchmark",
        "Tests several DNS providers for real latency from your location and "
        "shows which one actually resolves fastest.",
        '<circle cx="12" cy="12" r="9"/>'
        '<path d="M12 3v3M12 18v3M3 12h3M18 12h3"/>', 1.7,
        "Run test", 2.0),
    "speed": (
        "Speed Test",
        "Download, upload, and ping — a standard connection speed test.",
        '<path d="M13 2L4 14h6l-1 8 9-12h-6z"/>', 1.7,
        "Run test", 5.5),
    "benchmark": (
        "Benchmark",
        "Short synthetic stress test — SHA-256 throughput per core and "
        "scheduling fairness under full load.",
        '<rect x="4" y="4" width="16" height="16" rx="2"/>'
        '<path d="M9 9h6v6H9z"/>', 1.7,
        "Run test", 2.5),
    "drivers": (
        "Driver Check",
        "Scans GPU, network, audio and chipset drivers for stale versions "
        "and flags devices Windows reports as having problems.",
        '<path d="M12 3v10M8 7l4-4 4 4"/>'
        '<rect x="4" y="14" width="16" height="7" rx="2"/>', 1.7,
        "Run scan", 3.5),
    "disk": (
        "Disk Health",
        "Reads SMART data from your drives to catch early signs of failure "
        "before they cost you data.",
        '<rect x="3" y="4" width="18" height="6" rx="1"/>'
        '<rect x="3" y="14" width="18" height="6" rx="1"/>', 1.7,
        "Run scan", 4.0),
    "jitter": (
        "Network Jitter Test",
        "Latency variation and packet loss across 30 live probes \u2014 jitter "
        "and loss are what actually cause rubber-banding, not raw ping.",
        '<path d="M3 12h4l3-7 4 14 3-7h4"/>', 1.7,
        "Run test", 3.0),
    "throttle": (
        "GPU Throttling Scan",
        "Reads live perf state, SM clocks, thermals and active throttle "
        "reasons straight from the GPU (NVIDIA).",
        '<path d="M14 14.76V5a2 2 0 00-4 0v9.76a4 4 0 104 0z"/>', 1.7,
        "Run scan", 3.0),
    "recorders": (
        "Recorder Process Scan",
        "Finds game recorders and capture clients running in the background "
        "(ShadowPlay, Game DVR, OBS...) \u2014 they steal frames and input budget.",
        '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="3.5"/>', 1.7,
        "Run scan", 2.5),
    "pcie": (
        "PCIe Link Diagnostic",
        "Shows your GPU's current vs maximum PCIe link width and speed \u2014 a "
        "lane-drop to x4 or Gen1 silently costs frames.",
        '<rect x="4" y="4" width="16" height="16" rx="2"/>'
        '<path d="M4 10h16M10 4v16"/>', 1.7,
        "Run scan", 2.0),
    "memory": (
        "Memory Pressure Check",
        "Live RAM, commit and page-in rate \u2014 hard faults during gaming "
        "come from memory pressure, not capacity alone.",
        '<rect x="4" y="9" width="16" height="6" rx="1"/>', 1.7,
        "Run test", 2.5),
    "refresh": (
        "Refresh Rate Verify",
        "Verifies each display is actually running at its maximum supported "
        "refresh rate \u2014 Windows quietly falls back to 60 Hz surprisingly often.",
        '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>', 1.7,
        "Run scan", 2.0),
}
ORDER = ("bufferbloat", "dns", "speed", "benchmark", "drivers", "disk",
         "jitter", "throttle", "recorders", "pcie", "memory", "refresh")
GRADE_COLORS = {"a": _GREEN, "b": _CYAN, "c": "#E0A944"}
GRADE_LETTER = {"a": "A", "b": "B", "c": "C"}


def _icon(paths: str, color: str, size: int, sw: float) -> QLabel:
    from PySide6.QtGui import QPixmap
    from PySide6.QtSvg import QSvgRenderer
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
           f'fill="none" stroke="{color}" stroke-width="{sw}" '
           f'stroke-linecap="round" stroke-linejoin="round">{paths}</svg>')
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    r = QSvgRenderer()
    r.load(svg.encode("utf-8"))
    r.render(p, QRectF(0, 0, size, size))
    p.end()
    lbl = QLabel()
    lbl.setFixedSize(size, size)
    lbl.setPixmap(pm)
    lbl.setStyleSheet("background:transparent;border:none;")
    return lbl


class _Atmosphere(QWidget):
    """#08060F + cyan blob (top-left) + violet blob (bottom-right) + the
    masked 34px dot grid at 60%/20% (reference .main for this category)."""

    def paintEvent(self, _):
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor(_BG))
        ga = QRadialGradient(QPointF(360, 40), 380)
        ga.setColorAt(0.0, QColor(75, 232, 216, 31))
        ga.setColorAt(0.7, QColor(75, 232, 216, 0))
        p.fillRect(self.rect(), ga)
        gb = QRadialGradient(QPointF(w - 140, h), 340)
        gb.setColorAt(0.0, QColor(139, 107, 255, 26))
        gb.setColorAt(0.7, QColor(139, 107, 255, 0))
        p.fillRect(self.rect(), gb)
        cx, cy = 0.60 * w, 0.20 * h
        rx, ry = 0.70 * w, 0.60 * h
        if rx > 0 and ry > 0:
            y = 17.0
            while y < h:
                x = 17.0
                while x < w:
                    t = (((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2) ** 0.5
                    if t < 0.85:
                        a = int(45 * (1.0 - t / 0.85))
                        if a > 3:
                            p.setPen(QColor(200, 190, 240, a))
                            p.drawPoint(QPointF(x, y))
                    x += 34.0
                y += 34.0
        p.end()


class _RunWorker(QThread):
    done = Signal(str, object)

    def __init__(self, key, runner, parent=None):
        super().__init__(parent)
        self.key = key
        self.runner = runner

    def run(self):
        try:
            self.done.emit(self.key, self.runner())
        except Exception as exc:  # noqa: BLE001
            self.done.emit(self.key, {"rows": [], "grade": None,
                                      "error": str(exc)})


class _TestCard(QFrame):
    def __init__(self, key, parent=None):
        super().__init__(parent)
        self.key = key
        title, desc, paths, sw, run_lbl, est = TESTS[key]
        self._est = est
        self._running = False
        self._done_once = False
        self._t_run = 0.0
        self.run_label = run_lbl

        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("TestCard")
        self.setStyleSheet(
            "#TestCard{background:rgba(255,255,255,0.03);"
            " border:1px solid rgba(255,255,255,0.09); border-radius:16px;}")
        self.setMinimumHeight(232)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 22, 22, 20)
        lay.setSpacing(0)

        top = QHBoxLayout()
        top.setSpacing(12)
        chip = QFrame()
        chip.setFixedSize(36, 36)
        chip.setAttribute(Qt.WA_StyledBackground, True)
        chip.setObjectName("TIcon")
        chip.setStyleSheet(
            "#TIcon{background:rgba(75,232,216,0.10);"
            " border:1px solid rgba(75,232,216,0.28); border-radius:10px;}")
        cl = QHBoxLayout(chip)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setAlignment(Qt.AlignCenter)
        cl.addWidget(_icon(paths, _CYAN, 16, sw))
        top.addWidget(chip, 0, Qt.AlignVCenter)
        t = QLabel(title)
        t.setStyleSheet(
            f"font-family:{_DISPLAY}; font-size:14.5px; font-weight:600;"
            f" color:{_TEXT_1}; background:transparent;")
        top.addWidget(t, 0, Qt.AlignVCenter)
        top.addStretch()
        lay.addLayout(top)
        lay.addSpacing(14)

        d = QLabel(desc)
        d.setWordWrap(True)
        d.setStyleSheet(
            f"font-size:12px; color:{_TEXT_4}; background:transparent;")
        lay.addWidget(d)
        lay.addSpacing(16)

        # status line: dot + mono text
        self.status = QLabel()
        self.status.setStyleSheet(
            f"font-family:{_MONO}; font-size:10.5px; color:{_TEXT_6};"
            f" background:transparent;")
        self._dot = QLabel("\u25cf")
        self._dot.setStyleSheet(
            f"font-family:{_MONO}; font-size:10.5px; color:{_TEXT_6};"
            f" background:transparent;")
        sl = QHBoxLayout()
        sl.setSpacing(7)
        sl.addWidget(self._dot, 0, Qt.AlignVCenter)
        sl.addWidget(self.status, 0, Qt.AlignVCenter)
        sl.addStretch()
        lay.addLayout(sl)
        self._set_status("idle")
        lay.addSpacing(12)

        # progress bar (only visible while running)
        self.bar = QFrame()
        self.bar.setFixedHeight(4)
        self.bar.setAttribute(Qt.WA_StyledBackground, True)
        self.bar.setObjectName("ProgTrack")
        self.bar.setStyleSheet(
            "#ProgTrack{background:rgba(255,255,255,0.06);"
            " border:none; border-radius:2px;}")
        self.bar.hide()
        blay = QHBoxLayout(self.bar)
        blay.setContentsMargins(0, 0, 0, 0)
        self.fill = QFrame()
        self.fill.setStyleSheet(
            "background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f" stop:0 {_CYAN}, stop:1 {_VIOLET});"
            " border:none; border-radius:2px;")
        self.fill.setFixedWidth(0)
        blay.addWidget(self.fill, 0, Qt.AlignLeft)
        blay.addStretch()
        lay.addWidget(self.bar)
        lay.addSpacing(14)

        # results block
        self.result = QWidget()
        self.result.setStyleSheet("background:transparent;")
        self.res_lay = QVBoxLayout(self.result)
        self.res_lay.setContentsMargins(0, 0, 0, 0)
        self.res_lay.setSpacing(3)
        self.result.hide()
        lay.addWidget(self.result)
        lay.addStretch(1)

        # run button
        self.btn = QPushButton(run_lbl)
        self.btn.setCursor(Qt.PointingHandCursor)
        self.btn.setMinimumHeight(38)
        self.btn.clicked.connect(self._on_btn)
        lay.addWidget(self.btn)
        self._paint_btn("idle")

        self._pulse = QTimer(self)
        self._pulse.setInterval(90)
        self._pulse.timeout.connect(self._tick_run)
        self._worker: _RunWorker | None = None

    # ---- status ----

    def _set_status(self, mode, text=""):
        if mode == "idle":
            self._dot.setStyleSheet(
                f"font-family:{_MONO}; font-size:10.5px; color:{_TEXT_6};"
                f" background:transparent;")
            self.status.setText("Never run")
            self.status.setStyleSheet(
                f"font-family:{_MONO}; font-size:10.5px; color:{_TEXT_6};"
                f" background:transparent;")
        elif mode == "running":
            self._dot.setStyleSheet(
                f"font-family:{_MONO}; font-size:10.5px; color:{_CYAN};"
                f" background:transparent;")
            self.status.setText(text or "Running\u2026")
            self.status.setStyleSheet(
                f"font-family:{_MONO}; font-size:10.5px; color:{_CYAN};"
                f" background:transparent;")
        elif mode == "done":
            self._dot.setStyleSheet(
                f"font-family:{_MONO}; font-size:10.5px; color:{_GREEN};"
                f" background:transparent;")
            self.status.setText(text or "Just now")
            self.status.setStyleSheet(
                f"font-family:{_MONO}; font-size:10.5px; color:{_GREEN};"
                f" background:transparent;")
        else:  # error
            self._dot.setStyleSheet(
                f"font-family:{_MONO}; font-size:10.5px; color:{_RED};"
                f" background:transparent;")
            self.status.setText(text or "Failed")
            self.status.setStyleSheet(
                f"font-family:{_MONO}; font-size:10.5px; color:{_RED};"
                f" background:transparent;")

    def _paint_btn(self, mode):
        if mode == "again":
            self.btn.setStyleSheet(
                "QPushButton{font-size:12.5px; font-weight:600; color:#F6F4FC;"
                " background:rgba(255,255,255,0.04);"
                " border:1px solid rgba(255,255,255,0.09); border-radius:10px;"
                " padding:11px;}"
                "QPushButton:hover:enabled{background:rgba(255,255,255,0.07);"
                " border-color:rgba(255,255,255,0.18);}"
                "QPushButton:disabled{opacity:0.6;}")
        else:
            self.btn.setStyleSheet(
                "QPushButton{font-size:12.5px; font-weight:600; color:#FFFFFF;"
                " border:none; border-radius:10px; padding:11px;"
                " background:qlineargradient(x1:0,y1:0,x2:1,y2:0.35,"
                " stop:0 #8B6BFF, stop:1 #6D4FE0);}"
                "QPushButton:hover:enabled{background:qlineargradient("
                "x1:0,y1:0,x2:1,y2:0.35, stop:0 #9C80FF, stop:1 #7C5FF0);}"
                "QPushButton:disabled{background:rgba(139,107,255,0.30);"
                " color:rgba(255,255,255,0.5);}")

    # ---- run flow (exact reference: run -> running/progress -> result/run again)

    def _on_btn(self):
        if self._running:
            return
        runner = getattr(eng, "run_" + self.key)
        self._running = True
        self._t_run = time.monotonic()
        self.btn.setEnabled(False)
        self.btn.setText("Running\u2026")
        self.bar.show()
        self.fill.setFixedWidth(2)
        self.result.hide()
        clear_layout = _clear_layout
        clear_layout(self.res_lay)
        self._set_status("running")
        self._pulse.start()
        self._worker = _RunWorker(self.key, runner, self)
        self._worker.done.connect(self._on_done)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _tick_run(self):
        if not self._running:
            return
        el = time.monotonic() - self._t_run
        frac = min(0.92, el / self._est)
        self.fill.setFixedWidth(max(2, int(self.bar.width() * frac)))
        # pulse dot opacity (CSS pulse 1.4s)
        ph = 0.5 + 0.5 * math.sin(el / 1.4 * 2 * math.pi)
        a = int(90 + 165 * ph)
        self._dot.setStyleSheet(
            f"font-family:{_MONO}; font-size:10.5px; color:rgba(75,232,216,"
            f"{a}); background:transparent;")

    def _on_done(self, key, res):
        self._running = False
        self._pulse.stop()
        self.fill.setFixedWidth(self.bar.width())
        self.btn.setEnabled(True)
        err = res.get("error")
        rows = res.get("rows") or []
        grade = res.get("grade")
        _clear_layout(self.res_lay)
        if err or not rows:
            self._set_status("error", err or "No data")
            self.btn.setText("Run again" if self._done_once else self.run_label)
            self.bar.hide()
            return
        if grade:
            grow = QHBoxLayout()
            gc = QLabel(GRADE_LETTER.get(grade, ""))
            gc.setStyleSheet(
                f"font-family:{_DISPLAY}; font-size:20px; font-weight:700;"
                f" color:{GRADE_COLORS.get(grade, _TEXT_1)};"
                f" background:transparent;")
            grow.addWidget(gc)
            grow.addStretch()
            self.res_lay.addLayout(grow)
        for label, value in rows:
            row = QHBoxLayout()
            l = QLabel(label)
            l.setStyleSheet(
                f"font-size:11.5px; color:{_TEXT_4}; background:transparent;")
            v = QLabel(value)
            v.setStyleSheet(
                f"font-size:11.5px; color:{_TEXT_1}; font-weight:600;"
                f" background:transparent;")
            row.addWidget(l)
            row.addStretch()
            row.addWidget(v)
            self.res_lay.addLayout(row)
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background:{_BORDER_SOFT}; border:none;")
        self.res_lay.insertWidget(0, sep)
        self.result.show()
        self._done_once = True
        self._set_status("done", "Just now")
        self.btn.setText("Run again")
        self._paint_btn("again")

    def _on_finished(self):
        QTimer.singleShot(600, lambda: self.bar.hide())

    def focus_card(self):
        """Brief cyan flash so the sidebar test-click lands visibly."""
        self.setStyleSheet(
            "#TestCard{background:rgba(255,255,255,0.03);"
            " border:1px solid rgba(75,232,216,0.55); border-radius:16px;}")
        QTimer.singleShot(900, lambda: self.setStyleSheet(
            "#TestCard{background:rgba(255,255,255,0.03);"
            " border:1px solid rgba(255,255,255,0.09); border-radius:16px;}"))


def _clear_layout(lay):
    while lay.count():
        it = lay.takeAt(0)
        if it is None:
            break
        w = it.widget()
        if w is not None:
            w.deleteLater()
        sub = it.layout()
        if sub is not None:
            _clear_layout(sub)


class DiagnosticsPage(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.cards: dict[str, _TestCard] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._atmo = _Atmosphere(self)
        self._atmo.lower()

        scroll = QScrollArea()
        self._scroll = scroll
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}"
            "QScrollArea>QWidget>QWidget{background:transparent;}")
        body = QWidget()
        # Full-screen: no 1320 cap — the grid uses the entire pane width.
        wrap = QVBoxLayout(body)
        wrap.setContentsMargins(44, 40, 44, 60)
        wrap.setSpacing(0)
        inner = QWidget()
        root = QVBoxLayout(inner)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        wrap.addWidget(inner)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        # top bar
        bar = QHBoxLayout()
        left = QVBoxLayout()
        left.setSpacing(5)
        h1 = QLabel("Diagnostics")
        h1.setStyleSheet(
            f"font-family:{_DISPLAY}; font-size:26px; font-weight:600;"
            f" color:{_TEXT_1}; background:transparent;")
        p = QLabel("Tests and scanners \u2014 click to run, nothing here "
                   "happens automatically.")
        p.setStyleSheet(
            f"font-size:13px; color:{_TEXT_4}; background:transparent;")
        left.addWidget(h1)
        left.addWidget(p)
        bar.addLayout(left, 1)
        stat = QLabel()
        stat.setTextFormat(Qt.RichText)
        stat.setStyleSheet("background:transparent;")
        stat.setText(f"<span style='color:{_CYAN};'>\u25cf</span>"
                     f"<span style='color:{_TEXT_4};'> {len(ORDER)} available"
                     "</span>")
        bar.addWidget(stat, 0, Qt.AlignTop)
        root.addLayout(bar)
        root.addSpacing(28)

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)
        for i, key in enumerate(ORDER):
            card = _TestCard(key)
            self.cards[key] = card
            grid.addWidget(card, i // 3, i % 3)
        for c in range(3):
            grid.setColumnStretch(c, 1)
        root.addLayout(grid)

    def focus_card(self, key):
        card = self.cards.get(key)
        if card is not None:
            card.focus_card()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._atmo.setGeometry(self.rect())
        self._atmo.lower()
